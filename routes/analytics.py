"""
Эндпоинты для аналитики и отчетов.
Содержит логику расчета продаж, группировки по SKU и управления временными зонами.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime, timedelta, timezone
from db.database import OrderPosting, OrderProduct, Order, get_db, User
import asyncio
import logging
from services.sync import fetch_and_save_orders, run_enrichment_batch
from services.enrichment import enrich_posting_from_ozon
from utils.common import valid_posting_number
from utils.auth import get_current_user
from utils.logging_config import log_user_event

router = APIRouter(prefix="/analytics", tags=["analytics"])
logger = logging.getLogger("OzonAPIHub")


# =====================================================================
# Вспомогательные функции (Утилиты)
# =====================================================================

def _parse_iso(dt: str) -> datetime:
    """Парсит ISO-строку даты (с Z или без) в объект datetime."""
    return datetime.fromisoformat(dt.replace("Z", ""))


def _filter_items_by_status(items: list, postings_q, status_filter: str | None) -> list:
    """Фильтр номеров постингов по их статусу."""
    if not status_filter:
        return [p[0] for p in postings_q.all()]
    # Возвращаем только те номера постингов, статус которых совпадает с фильтром
    return [p[0] for (p, st) in postings_q.all() if st and st.lower() == status_filter.lower()]


def _range_with_tz(since: str | None, to: str | None, tz_offset_hours: int) -> tuple[datetime, datetime]:
    """
    Рассчитывает временной диапазон в UTC на основе локального времени пользователя.
    Ozon API и база данных работают в UTC, но пользователь ожидает данные за "свои" сутки.
    """
    if since and to:
        start_local = _parse_iso(since)
        end_local = _parse_iso(to)
        # Сдвигаем назад на офсет, чтобы получить UTC
        start_utc = start_local - timedelta(hours=tz_offset_hours)
        end_utc = end_local - timedelta(hours=tz_offset_hours)
        return start_utc, end_utc

    # По умолчанию берем текущие сутки
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    local_now = now_utc + timedelta(hours=tz_offset_hours)
    local_start = datetime(local_now.year, local_now.month, local_now.day)
    start_utc = local_start - timedelta(hours=tz_offset_hours)
    end_utc = start_utc + timedelta(days=1)
    return start_utc, end_utc


async def _ensure_data_for_range(db: Session, start: datetime, end: datetime, user_id: int):
    """
    Механизм 'Ленивой синхронизации' (Lazy Loading).
    Если пользователь запрашивает аналитику за период, по которому в базе нет данных,
    система автоматически скачивает их из Ozon перед расчетом отчета.
    """
    since_iso = start.isoformat() + "Z"
    to_iso = end.isoformat() + "Z"

    # Проверяем, есть ли хоть одна запись за этот период
    has_orders = db.query(Order).filter(
        Order.user_id == user_id,
        Order.created_at >= since_iso,
        Order.created_at < to_iso
    ).count() > 0

    if not has_orders:
        try:
            log_user_event(user_id, f"Авто-подкачка данных для аналитики: {since_iso} -> {to_iso}")
            # Запускаем синхронизацию (в потоке, чтобы не блокировать)
            res = await asyncio.to_thread(fetch_and_save_orders, since_iso, to_iso, "", 50, 0, True, True, False, user_id, db)
            orders = res.get("orders") or []
            
            # Сразу обогащаем новые заказы деталями (товары, комиссии)
            pns = [o.get("posting_number") for o in orders if valid_posting_number(o.get("posting_number"))]
            if pns:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    for pn in pns:
                        await enrich_posting_from_ozon(pn, user, db)
        except Exception as e:
            logger.error(f"Lazy sync error: {e}")

# =====================================================================
# Эндпоинты API
# =====================================================================

@router.get("/sales_range")
async def sales_range(
    since: str,
    to: str,
    tz_offset_hours: int = 0,
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Получает агрегированный отчет по продажам за произвольный период.
    Группирует данные по SKU/OfferID.
    """
    start, end = _range_with_tz(since, to, tz_offset_hours)
    # Проверяем наличие данных
    await _ensure_data_for_range(db, start, end, current_user.id)

    # Базовая фильтрация постингов по времени и статусу
    # В режиме 'Финансы' (status=None) берем только доставленные (delivered)
    query_p = db.query(OrderPosting.posting_number).filter(OrderPosting.user_id == current_user.id)

    if status:
        # Если статус указан, смотрим по дате перехода в обработку
        query_p = query_p.filter(
            OrderPosting.in_process_at >= start.isoformat() + "Z",
            OrderPosting.in_process_at < end.isoformat() + "Z",
            OrderPosting.status == status
        )
    else:
        # По умолчанию - доставленные заказы по дате создания
        query_p = query_p.filter(
            OrderPosting.status == "delivered",
            OrderPosting.created_at >= start.isoformat() + "Z",
            OrderPosting.created_at < end.isoformat() + "Z"
        )

    posting_numbers = [p[0] for p in query_p.all()]
    if not posting_numbers:
        return {"items": [], "total_items": 0, "total_orders": 0}

    # Подзапрос для получения самых актуальных названий товаров
    latest_names_sq = (
        db.query(OrderProduct.offer_id, OrderProduct.name)
        .filter(OrderProduct.user_id == current_user.id)
        .distinct(OrderProduct.offer_id)
        .order_by(OrderProduct.offer_id, OrderProduct.id.desc())
        .subquery()
    )

    # Группируем продажи по SKU
    rows = (
        db.query(
            OrderProduct.offer_id,
            OrderProduct.sku,
            latest_names_sq.c.name.label("name"),
            func.sum(OrderProduct.quantity).label("quantity_sold"),
            func.sum(OrderProduct.payout).label("total_payout"),
            func.count(func.distinct(OrderProduct.posting_number)).label("orders_count"),
        )
        .join(latest_names_sq, OrderProduct.offer_id == latest_names_sq.c.offer_id)
        .filter(OrderProduct.user_id == current_user.id)
        .filter(OrderProduct.posting_number.in_(posting_numbers))
        .group_by(OrderProduct.offer_id, OrderProduct.sku, latest_names_sq.c.name)
        .all()
    )

    items = [
        {
            "offer_id": r.offer_id,
            "sku": r.sku,
            "name": r.name,
            "quantity_sold": int(r.quantity_sold or 0),
            "total_payout": int(r.total_payout or 0),
            "orders_count": int(r.orders_count or 0),
        }
        for r in rows
    ]

    return {
        "range": {"since": start.isoformat() + "Z", "to": end.isoformat() + "Z"},
        "items": sorted(items, key=lambda x: -x["quantity_sold"]),
        "total_items": sum(i["quantity_sold"] for i in items),
        "total_orders": len(set(posting_numbers)),
    }


@router.get("/sales_today_raw")
async def sales_today_raw(
    since: str | None = None,
    to: str | None = None,
    tz_offset_hours: int = 0,
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Получает сырые данные об отгрузках (режим 'Склад').
    Позволяет видеть заказы в любых статусах (ожидают сборки, едут и т.д.).
    """
    start, end = _range_with_tz(since, to, tz_offset_hours)
    await _ensure_data_for_range(db, start, end, current_user.id)

    # Фильтруем по дате попадания в обработку (in_process_at)
    query_p = db.query(OrderPosting.posting_number, OrderPosting.status).filter(
        OrderPosting.user_id == current_user.id,
        OrderPosting.in_process_at >= start.isoformat() + "Z",
        OrderPosting.in_process_at < end.isoformat() + "Z"
    )

    if status:
        query_p = query_p.filter(OrderPosting.status == status)

    rows_p = query_p.all()
    p_numbers = [r[0] for r in rows_p]

    if not p_numbers:
        return {"items": [], "total_items": 0, "total_orders": 0, "by_status": []}

    # Считаем статистику по статусам для воронки
    status_counts = {}
    for _, st in rows_p:
        status_counts[st] = status_counts.get(st, 0) + 1

    # Группируем товары
    rows_items = (
        db.query(
            OrderProduct.offer_id,
            OrderProduct.sku,
            OrderProduct.name,
            func.sum(OrderProduct.quantity).label("quantity"),
            func.sum(OrderProduct.price * OrderProduct.quantity).label("amount_raw")
        )
        .filter(OrderProduct.user_id == current_user.id)
        .filter(OrderProduct.posting_number.in_(p_numbers))
        .group_by(OrderProduct.offer_id, OrderProduct.sku, OrderProduct.name)
        .all()
    )

    items = [
        {
            "offer_id": r.offer_id,
            "sku": r.sku,
            "name": r.name,
            "quantity": int(r.quantity or 0),
            "amount_raw": int(r.amount_raw or 0)
        }
        for r in rows_items
    ]

    return {
        "items": sorted(items, key=lambda x: -x["quantity"]),
        "total_items": sum(i["quantity"] for i in items),
        "total_orders": len(p_numbers),
        "by_status": [{"status": k, "count": v} for k, v in status_counts.items()]
    }


@router.get("/sales_by_sku_monthly")
def sales_by_sku_monthly(
    offer_id: str | None = None,
    sku: str | None = None,
    months_back: int = 12,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Данные для графика: продажи конкретного товара помесячно.
    """
    if not offer_id and not sku:
        return {"error": "SKU or OfferID required"}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start_date = now - timedelta(days=30 * months_back)

    # Ищем товары этого пользователя за указанный период
    query = db.query(OrderProduct, OrderPosting.in_process_at).join(
        OrderPosting, OrderPosting.posting_number == OrderProduct.posting_number
    ).filter(
        OrderProduct.user_id == current_user.id,
        OrderPosting.in_process_at >= start_date.isoformat() + "Z"
    )

    if offer_id: query = query.filter(OrderProduct.offer_id == offer_id)
    if sku: query = query.filter(OrderProduct.sku == sku)

    results = query.all()

    # Группируем по месяцам (YYYY-MM)
    monthly = {}
    for prod, date_str in results:
        try:
            month_key = date_str[:7] # Вырезаем YYYY-MM
            if month_key not in monthly:
                monthly[month_key] = {"month": month_key, "quantity": 0, "payout": 0}
            monthly[month_key]["quantity"] += (prod.quantity or 0)
            monthly[month_key]["payout"] += (prod.payout or 0)
        except: continue

    return {"data": sorted(monthly.values(), key=lambda x: x["month"])}


@router.get("/shipments")
def get_shipments(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Список последних отгрузок с пагинацией."""
    query = db.query(OrderPosting).filter(OrderPosting.user_id == current_user.id).order_by(desc(OrderPosting.in_process_at))
    total = query.count()
    items = query.limit(limit).offset(offset).all()

    return {
        "total": total,
        "items": [
            {
                "posting_number": i.posting_number,
                "status": i.status,
                "date": i.in_process_at,
                "order_number": i.order_number
            } for i in items
        ]
    }
