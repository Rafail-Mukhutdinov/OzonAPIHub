"""
Модуль обогащения данных (Enrichment).
Отвечает за получение детальной информации по каждому заказу (товары, комиссии, выплаты)
и расчет агрегированных показателей.
"""

import os
import logging
from services.ozon import ozon_fbo_get_async
from sqlalchemy.orm import Session
from db.database import OrderHeader, OrderPosting, OrderProduct, User, OzonCredential
from utils.encryption import decrypt_credential
from datetime import datetime, timezone
from utils.logging_config import log_user_event

logger = logging.getLogger("OzonAPIHub")


def _to_int(val):
    """
    Безопасное преобразование значения в целое число (Integer).
    Обрабатывает None, строки с запятой и float.
    """
    try:
        if val is None:
            return None
        if isinstance(val, (int,)):
            return val
        if isinstance(val, float):
            return int(round(val))
        return int(round(float(str(val).replace(',', '.'))))
    except Exception:
        return None


def recalc_order_header(db: Session, order_number: str, user_id: int):
    """
    Пересчитывает общие финансовые показатели для всего заказа (OrderHeader).
    Один заказ Ozon может состоять из нескольких отправлений (Postings).
    Суммирует выплаты и комиссии по всем товарам всех отправлений заказа.
    """
    # Получаем все товары всех отправлений, связанных с этим номером заказа
    products = db.query(OrderProduct).join(
        OrderPosting,
        (OrderPosting.posting_number == OrderProduct.posting_number) & (OrderPosting.user_id == OrderProduct.user_id)
    ).filter(
        OrderPosting.order_number == order_number,
        OrderPosting.user_id == user_id
    ).all()

    # Суммируем финансы
    total_payout = sum((_to_int(p.payout) or 0) for p in products)
    total_commission = sum((_to_int(p.commission_amount) or 0) for p in products)

    # Получаем все отправления для определения дат
    postings = db.query(OrderPosting).filter(
        OrderPosting.order_number == order_number,
        OrderPosting.user_id == user_id
    ).all()

    first_created = None
    last_delivery = None
    for p in postings:
        if p.created_at:
            # Находим самую раннюю дату создания
            first_created = min(first_created, p.created_at) if first_created else p.created_at
        if p.fact_delivery_date:
            # Находим самую позднюю дату доставки
            last_delivery = max(last_delivery, p.fact_delivery_date) if last_delivery else p.fact_delivery_date

    # Обновляем или создаем запись заголовка
    hdr = db.query(OrderHeader).filter(
        OrderHeader.order_number == order_number,
        OrderHeader.user_id == user_id
    ).first()

    if not hdr:
        hdr = OrderHeader(order_number=order_number, user_id=user_id)
        db.add(hdr)

    hdr.first_created_at = first_created
    hdr.last_delivery_at = last_delivery
    hdr.total_payout = total_payout
    hdr.total_commission = total_commission
    db.commit()


async def enrich_posting_from_ozon(posting_number: str, user: User, db: Session):
    """
    Основная функция обогащения:
    1. Запрашивает детали отправления из Ozon API (/v2/posting/fbo/get).
    2. Сохраняет статус и даты отправления в OrderPosting.
    3. Сохраняет список товаров и их индивидуальные комиссии в OrderProduct.
    4. Запускает пересчет заголовка заказа.
    """
    # Получаем активные API-ключи пользователя
    active_cred = db.query(OzonCredential).filter(
        OzonCredential.user_id == user.id,
        OzonCredential.is_active == True
    ).first()
    
    if not active_cred:
        log_user_event(user.id, f"Обогащение {posting_number} отменено: нет активных ключей", "warning")
        return {"status": "no_credentials"}
    
    # Дешифровка
    client_id = decrypt_credential(active_cred.client_id_encrypted)
    api_key = decrypt_credential(active_cred.api_key_encrypted)
    
    if not client_id or not api_key:
        return {"status": "error", "message": "Decryption failed"}
    
    # Запрос к Ozon API
    try:
        response = await ozon_fbo_get_async(client_id, api_key, posting_number)
        data = response.get("result")
    except Exception as e:
        error_msg = f"Ошибка Ozon API при обогащении {posting_number}: {e}"
        log_user_event(user.id, error_msg, "error")
        return {"status": "api_error", "detail": str(e)}

    if not data:
        return {"status": "no_result"}
    
    order_number = data.get("order_number")

    # Сохраняем данные об отправлении (Posting)
    op = db.query(OrderPosting).filter(
        OrderPosting.posting_number == posting_number,
        OrderPosting.user_id == user.id
    ).first()
    
    if not op:
        op = OrderPosting(posting_number=posting_number, user_id=user.id)
        db.add(op)
    
    op.order_number = order_number
    op.status = data.get("status")
    op.created_at = data.get("created_at")
    op.in_process_at = data.get("in_process_at")
    op.fact_delivery_date = data.get("fact_delivery_date")
    op.substatus = data.get("substatus")
    op.analytics_data = data.get("analytics_data")
    op.financial_data = data.get("financial_data")
    db.commit()
    
    # Очищаем старый список товаров для этого отправления (чтобы избежать дублей)
    db.query(OrderProduct).filter(
        OrderProduct.posting_number == posting_number,
        OrderProduct.user_id == user.id
    ).delete()
    
    # Мапим финансовые данные (из блока financial_data) на список товаров
    products_data = data.get("products", [])
    fin_products = (data.get("financial_data") or {}).get("products") or []
    
    # Создаем быстрый индекс по товарам для сопоставления финансов
    fin_map = {}
    for f in fin_products:
        if f.get("product_id"): fin_map[str(f.get("product_id"))] = f
        if f.get("sku"): fin_map[str(f.get("sku"))] = f
        if f.get("offer_id"): fin_map[str(f.get("offer_id"))] = f

    # Сохраняем каждый товар
    for pr in products_data:
        sku = pr.get("sku")
        offer_id = pr.get("offer_id")

        # Ищем финансовую информацию по SKU или OfferID
        f = fin_map.get(str(sku)) or fin_map.get(str(offer_id))

        obj = OrderProduct(
            user_id=user.id,
            posting_number=posting_number,
            sku=_to_int(sku),
            offer_id=str(offer_id) if offer_id is not None else None,
            name=pr.get("name"),
            quantity=_to_int(pr.get("quantity")),
            price=_to_int(pr.get("price")),
            currency_code=pr.get("currency_code"),
            # Финансы
            commission_amount=_to_int((f or {}).get("commission_amount")),
            commission_percent=_to_int((f or {}).get("commission_percent")),
            payout=_to_int((f or {}).get("payout")),
            total_discount_value=_to_int((f or {}).get("total_discount_value")),
            total_discount_percent=_to_int((f or {}).get("total_discount_percent")),
        )
        db.add(obj)
    
    db.commit()
    
    # После сохранения всех товаров обновляем агрегат заказа
    if order_number:
        recalc_order_header(db, order_number, user.id)

    log_user_event(user.id, f"Постинг {posting_number} успешно обогащен ({len(products_data)} товаров)")
    return {"status": "ok"}
