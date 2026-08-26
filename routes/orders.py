"""
Эндпоинты для управления заказами и отправлениями (Postings).
Позволяет искать заказы по фильтрам, получать детальную информацию и сводки по заказам.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List
from collections import defaultdict
from db.database import Order, OrderHeader, OrderPosting, OrderProduct, get_db, User, OzonCredential, OzonDeliveryMethodMapping
from utils.auth import get_current_user
from datetime import datetime, timezone
from utils.logging_config import log_user_event
from utils.common import normalize_iso

# Настройка логирования
logger = logging.getLogger("OzonAPIHub")

# Роутер для управления заказами
router = APIRouter(tags=["orders"])

@router.get("/orders")
def list_orders(
    since: str | None = None,
    to: str | None = None,
    status: str | None = None,
    scheme: str | None = None, # fbo, fbs, rfbs
    posting_number: str | None = None,
    contains: str | None = None,
    limit: int = 50,
    offset: int = 0,
    sort: str = "-created_at",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Получает список всех заказов пользователя из таблицы Orders.
    """
    try:
        since_iso = normalize_iso(since) if since else None
        to_iso = normalize_iso(to) if to else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректный формат даты.")

    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    filters = []
    if status: filters.append(f"status={status}")
    if scheme: filters.append(f"scheme={scheme}")
    if posting_number: filters.append(f"pn={posting_number}")
    
    log_user_event(current_user.id, f"Запрос списка заказов. Фильтры: {', '.join(filters)}. Limit: {limit}")

    q = db.query(Order).filter(Order.user_id == current_user.id)

    if since_iso: q = q.filter(Order.created_at >= since_iso)
    if to_iso: q = q.filter(Order.created_at <= to_iso)
    if status: q = q.filter(Order.status == status)
    if scheme and scheme != 'all': q = q.filter(Order.scheme == scheme)
    if posting_number: q = q.filter(Order.posting_number == posting_number)
    if contains: q = q.filter(Order.posting_number.like(f"%{contains}%"))

    total = q.count()

    # Сортировка
    if sort == "created_at":
        q = q.order_by(Order.created_at.asc())
    else:
        q = q.order_by(Order.created_at.desc())

    rows = q.offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": r.id,
                "order_id": r.order_id,
                "posting_number": r.posting_number,
                "status": r.status,
                "scheme": r.scheme,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
                "data": r.data, # Возвращаем сырой JSON от Ozon
            }
            for r in rows
        ]
    }

@router.get("/orders/unfulfilled")
async def list_unfulfilled_fbs_orders(
    raw: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Получает список 'горящих' FBS заказов, которые нужно собрать или отгрузить.
    Данные нормализуются в плоский список для удобства UI.
    """
    cred = db.query(OzonCredential).filter(
        OzonCredential.user_id == current_user.id,
        OzonCredential.is_active == True
    ).first()
    
    if not cred:
        raise HTTPException(status_code=400, detail="API ключи не настроены")

    from services.ozon import ozon_fbs_unfulfilled_list_async
    from utils.encryption import decrypt_credential
    try:
        data = await ozon_fbs_unfulfilled_list_async(
            client_id=decrypt_credential(cred.client_id_encrypted),
            api_key=decrypt_credential(cred.api_key_encrypted)
        )
        
        # Проверяем ошибки API Ozon
        if data.get("error"):
            err_msg = data.get("error")
            logger.error(f"Ozon API error in unfulfilled: {err_msg}")
            raise HTTPException(status_code=502, detail=f"Ozon API error: {err_msg}")

        if raw: return data

        # 🟡 Загружаем маппинги имен доставки (защищенно)
        mapping_dict = {}
        try:
            mappings = db.query(OzonDeliveryMethodMapping).filter(OzonDeliveryMethodMapping.user_id == current_user.id).all()
            mapping_dict = {m.delivery_method_id: m.custom_name for m in mappings}
        except SQLAlchemyError as se:
            db.rollback() # Очищаем сессию после ошибки БД
            logger.warning(f"Could not load delivery mappings (migration or DB issue): {se}")

        result_raw = data.get("result")
        flat_postings = []

        if isinstance(result_raw, dict):
            # Формат v3 или специфичный v2 dict
            postings = result_raw.get("postings", [])
            for p in postings:
                dm = p.get("delivery_method") or {}
                dm_id = dm.get("id")
                # Fallback: если маппинга нет, берем оригинальное имя
                dm_name = mapping_dict.get(dm_id) or dm.get("name")

                flat_postings.append({
                    "posting_number": p.get("posting_number"),
                    "status": p.get("status"),
                    "shipment_date": p.get("shipment_date"),
                    "in_process_at": p.get("in_process_at"),
                    "is_express": p.get("is_express", False),
                    "products_count": len(p.get("products", [])),
                    "products": p.get("products", []),
                    "tpl_provider": dm.get("tpl_provider"),
                    "delivery_method_name": dm_name,
                })
        elif isinstance(result_raw, list):
            # Формат v2 list of status groups
            for status_group in result_raw:
                status = status_group.get("status")
                postings = status_group.get("postings", [])
                for p in postings:
                    dm = p.get("delivery_method") or {}
                    dm_id = dm.get("id")
                    dm_name = mapping_dict.get(dm_id) or dm.get("name")

                    flat_postings.append({
                        "posting_number": p.get("posting_number"),
                        "status": status,
                        "shipment_date": p.get("shipment_date"),
                        "in_process_at": p.get("in_process_at"),
                        "is_express": p.get("is_express", False),
                        "products_count": len(p.get("products", [])),
                        "products": p.get("products", []),
                        "tpl_provider": dm.get("tpl_provider"),
                        "delivery_method_name": dm_name,
                    })
        else:
            return []
        
        # Сортируем: горящие (ближайшая дата отгрузки) — первыми
        flat_postings.sort(key=lambda x: x.get("shipment_date") or "9999")
        return flat_postings
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error fetching unfulfilled orders: {error_msg}")
        raise HTTPException(
            status_code=500, 
            detail=f"Ошибка при обработке запроса: {error_msg}"
        )


@router.get("/orders/{posting_number}")
def get_order_by_posting(
    posting_number: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Возвращает детальную информацию об одном отправлении по его номеру.
    """
    row = db.query(Order).filter(
        Order.user_id == current_user.id,
        Order.posting_number == posting_number
    ).first()

    if not row:
        log_user_event(current_user.id, f"Заказ {posting_number} не найден", "warning")
        raise HTTPException(status_code=404, detail="Заказ не найден")

    return row


@router.get("/order/{order_number}")
def get_order_summary(
    order_number: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Возвращает полную сводку по номеру заказа.
    Один заказ Ozon может содержать несколько отправлений (Postings).
    Этот эндпоинт собирает всё воедино: заголовок, все отправления и все товары в них.
    """
    log_user_event(current_user.id, f"Запрос сводки по заказу {order_number}")

    # 1. Берем агрегированные данные (если есть)
    header = db.query(OrderHeader).filter(
        OrderHeader.user_id == current_user.id,
        OrderHeader.order_number == order_number
    ).first()

    # 2. Берем все отправления этого заказа
    postings = db.query(OrderPosting).filter(
        OrderPosting.user_id == current_user.id,
        OrderPosting.order_number == order_number
    ).order_by(OrderPosting.created_at.asc()).all()

    # 🟡 Загружаем маппинги (защищенно)
    mapping_dict = {}
    try:
        mappings = db.query(OzonDeliveryMethodMapping).filter(OzonDeliveryMethodMapping.user_id == current_user.id).all()
        mapping_dict = {m.delivery_method_id: m.custom_name for m in mappings}
    except SQLAlchemyError as se:
        db.rollback()
        logger.warning(f"Could not load delivery mappings: {se}")

    # 3. Берем все товары для всех найденных отправлений
    posting_numbers = [p.posting_number for p in postings]
    products = []
    products_by_posting = defaultdict(list)
    
    if posting_numbers:
        products = db.query(OrderProduct).filter(
            OrderProduct.user_id == current_user.id,
            OrderProduct.posting_number.in_(posting_numbers)
        ).all()
        
        # Группируем товары по номеру отправления для O(1) поиска
        for pr in products:
            products_by_posting[pr.posting_number].append(pr)

    # Считаем промежуточные итоги, если заголовка нет в БД
    total_payout = sum((p.payout or 0) for p in products)
    total_commission = sum((p.commission_amount or 0) for p in products)
    profit = total_payout - total_commission

    return {
        "order_number": order_number,
        "header": {
            "first_created_at": header.first_created_at if header else None,
            "last_delivery_at": header.last_delivery_at if header else None,
            "total_payout": header.total_payout if header and header.total_payout is not None else total_payout,
            "total_commission": header.total_commission if header and header.total_commission is not None else total_commission,
            "profit": profit,
        },
        "postings": [
            {
                "posting_number": p.posting_number,
                "status": p.status,
                "scheme": p.scheme,
                "is_express": p.is_express,
                "shipment_date": p.shipment_date,
                "tpl_provider": p.tpl_provider,
                "delivery_method_name": mapping_dict.get(p.delivery_method_id) or p.delivery_method_name,
                "created_at": p.created_at,
                "in_process_at": p.in_process_at,
                "fact_delivery_date": p.fact_delivery_date,
                "substatus": p.substatus,
                "analytics_data": p.analytics_data,
                "financial_data": p.financial_data,
                "products": [
                    {
                        "sku": pr.sku,
                        "offer_id": pr.offer_id,
                        "name": pr.name,
                        "quantity": pr.quantity,
                        "price": pr.price,
                        "currency_code": pr.currency_code,
                        "commission_amount": pr.commission_amount,
                        "commission_percent": pr.commission_percent,
                        "payout": pr.payout,
                        "total_discount_value": pr.total_discount_value,
                        "total_discount_percent": pr.total_discount_percent,
                    }
                    for pr in products_by_posting.get(p.posting_number, [])
                ],
            }
            for p in postings
        ],
    }

@router.get("/order/{order_number}/postings")
def list_order_postings(
    order_number: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Возвращает список только отправлений (без товаров) для конкретного заказа.
    """
    postings = db.query(OrderPosting).filter(
        OrderPosting.user_id == current_user.id,
        OrderPosting.order_number == order_number
    ).order_by(OrderPosting.created_at.asc()).all()

    # Фоллбек: если данных в OrderPosting еще нет, ищем в сырых Orders по префиксу номера
    if not postings:
        prefix = order_number + "-"
        legacy_postings = db.query(Order.posting_number).filter(
            Order.user_id == current_user.id,
            Order.posting_number.like(f"{prefix}%")
        ).all()
        postings = [
            OrderPosting(order_number=order_number, posting_number=p[0], status=None, created_at=None)
            for p in legacy_postings
        ]

    if not postings:
        return {"order_number": order_number, "count": 0, "items": []}

    # Оптимизировано: загружаем все товары для всех постингов заказа одним запросом (устраняем N+1)
    pns = [p.posting_number for p in postings]
    all_prods = db.query(OrderProduct).filter(
        OrderProduct.user_id == current_user.id,
        OrderProduct.posting_number.in_(pns)
    ).all()

    # Группируем товары по номеру постинга в памяти
    prods_by_pn = {}
    for pr in all_prods:
        if pr.posting_number not in prods_by_pn:
            prods_by_pn[pr.posting_number] = []
        prods_by_pn[pr.posting_number].append(pr)

    result = []
    for p in postings:
        pn_prods = prods_by_pn.get(p.posting_number, [])
        total_payout = sum((pr.payout or 0) for pr in pn_prods)
        total_commission = sum((pr.commission_amount or 0) for pr in pn_prods)

        result.append({
            "posting_number": p.posting_number,
            "status": p.status,
            "created_at": p.created_at,
            "products_count": len(pn_prods),
            "total_payout": round(total_payout, 2),
            "total_commission": round(total_commission, 2),
        })
    return {"order_number": order_number, "count": len(result), "items": result}
