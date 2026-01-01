from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from db.database import OrderPosting, OrderProduct, Order, get_db
import asyncio
from services.sync import fetch_and_save_orders, run_enrichment_batch
from utils.common import valid_posting_number

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _parse_iso(dt: str) -> datetime:
    return datetime.fromisoformat(dt.replace("Z", ""))


def _filter_items_by_status(items: list, postings_q, status_filter: str | None, db: Session) -> list:
    """Фильтр товаров по статусу постинга. Если status_filter = None, возвращает все."""
    if not status_filter:
        posting_numbers = [p[0] for p in postings_q.all()]
        return posting_numbers
    # Берём только постинги с указанным статусом
    filtered = [p[0] for (p, st) in postings_q.all() if st and st.lower() == status_filter.lower()]
    return filtered


def _range_with_tz(since: str | None, to: str | None, tz_offset_hours: int) -> tuple[datetime, datetime]:
    """
    Возвращает границы интервала в UTC с учётом локального смещения (tz_offset_hours).
    Если since/to заданы (ISO), трактуем их как локальные и сдвигаем в UTC на -offset.
    Если не заданы — берём текущие сутки по локальному времени и возвращаем эквивалент в UTC.
    """
    if since and to:
        start_local = _parse_iso(since)
        end_local = _parse_iso(to)
        start_utc = start_local - timedelta(hours=tz_offset_hours)
        end_utc = end_local - timedelta(hours=tz_offset_hours)
        return start_utc, end_utc
    now_utc = datetime.utcnow()
    if tz_offset_hours:
        local_now = now_utc + timedelta(hours=tz_offset_hours)
        local_start = datetime(local_now.year, local_now.month, local_now.day)
        start_utc = local_start - timedelta(hours=tz_offset_hours)
        end_utc = start_utc + timedelta(days=1)
    else:
        start_utc = datetime(now_utc.year, now_utc.month, now_utc.day)
        end_utc = start_utc + timedelta(days=1)
    return start_utc, end_utc

async def _ensure_data_for_range(db: Session, start: datetime, end: datetime):
    """
    Если за диапазон нет данных в БД, подтянуть их из Ozon и обогатить постинги.
    """
    since_iso = start.isoformat() + "Z"
    to_iso = end.isoformat() + "Z"
    has_orders = db.query(Order).filter(Order.created_at >= since_iso).filter(Order.created_at < to_iso).count() > 0
    has_postings = db.query(OrderPosting).filter(OrderPosting.created_at >= since_iso).filter(OrderPosting.created_at < to_iso).count() > 0
    if not (has_orders or has_postings):
        res = await asyncio.to_thread(fetch_and_save_orders, since_iso, to_iso, "", 50, 0, True, True, False, db)
        orders = res.get("orders") or []
        pns = [o.get("posting_number") for o in orders if valid_posting_number(o.get("posting_number"))]
        if pns:
            existing = set(r[0] for r in db.query(OrderPosting.posting_number).filter(OrderPosting.posting_number.in_(pns)).all())
            targets = [pn for pn in set(pns) if pn not in existing]
            if targets:
                await run_enrichment_batch(targets)
@router.get("/sales_by_date")
async def sales_by_date(date: str, tz_offset_hours: int = 0, db: Session = Depends(get_db)):
    """Агрегаты по delivered за конкретную локальную дату (с учётом tz_offset_hours)."""
    target = datetime.fromisoformat(date)  # YYYY-MM-DD
    local_start = datetime(target.year, target.month, target.day)
    start = local_start - timedelta(hours=tz_offset_hours)
    end = start + timedelta(days=1)
    return await sales_today(since=start.isoformat() + "Z", to=end.isoformat() + "Z", tz_offset_hours=0, db=db)

@router.get("/sales_range")
async def sales_range(since: str, to: str, tz_offset_hours: int = 0, status: str | None = None, db: Session = Depends(get_db)):
    """Агрегаты по delivered за диапазон с учётом tz_offset_hours.
    Если offset != 0 — считаем, что since/to локальные и конвертируем в UTC.
    status — фильтр по статусу (если передан, override на delivered).
    """
    start, end = _range_with_tz(since, to, tz_offset_hours)
    return await sales_today(since=start.isoformat() + "Z", to=end.isoformat() + "Z", tz_offset_hours=0, status=status, db=db)

@router.get("/sales_today")
async def sales_today(
    since: str | None = None,
    to: str | None = None,
    tz_offset_hours: int = 0,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    # Диапазон в UTC с учётом локального смещения
    start, end = _range_with_tz(since, to, tz_offset_hours)
    await _ensure_data_for_range(db, start, end)
    
    if status:
        # Фильтруем по указанному статусу
        postings_q = (
            db.query(OrderPosting.posting_number, OrderPosting.status)
            .filter(OrderPosting.in_process_at >= start.isoformat() + "Z")
            .filter(OrderPosting.in_process_at < end.isoformat() + "Z")
        )
        posting_numbers = _filter_items_by_status([], postings_q, status, db)
    else:
        # По умолчанию delivered
        postings = (
            db.query(OrderPosting.posting_number)
            .filter(OrderPosting.status == "delivered")
            .filter(OrderPosting.fact_delivery_date >= start.isoformat() + "Z")
            .filter(OrderPosting.fact_delivery_date < end.isoformat() + "Z")
            .all()
        )
        posting_numbers = [p[0] for p in postings]
    # Fallback: если по in_process_at ничего не нашли (старая история без обогащения),
    # возьмём posting_number из таблицы orders по created_at
    if not posting_numbers:
        orders_fallback = (
            db.query(Order.posting_number)
            .filter(Order.created_at >= start.isoformat() + "Z")
            .filter(Order.created_at < end.isoformat() + "Z")
            .all()
        )
        posting_numbers = [o[0] for o in orders_fallback if o and o[0]]
    if not posting_numbers:
        return {
            "range": {"since": start.isoformat() + "Z", "to": end.isoformat() + "Z"},
            "items": [],
            "total_items": 0,
            "total_orders": 0,
        }
    # Агрегируем на стороне БД, чтобы не тянуть все строки в память
    rows = (
        db.query(
            OrderProduct.offer_id,
            OrderProduct.sku,
            OrderProduct.name,
            func.sum(OrderProduct.quantity).label("quantity_sold"),
            func.sum(OrderProduct.payout).label("total_payout"),
            func.count(func.distinct(OrderProduct.posting_number)).label("orders_count"),
        )
        .filter(OrderProduct.posting_number.in_(posting_numbers))
        .group_by(OrderProduct.offer_id, OrderProduct.sku, OrderProduct.name)
        .all()
    )

    items = [
        {
            "offer_id": r.offer_id,
            "sku": r.sku,
            "name": r.name,
            "quantity_sold": r.quantity_sold or 0,
            "total_payout": r.total_payout or 0,
            "orders_count": r.orders_count or 0,
        }
        for r in rows
    ]

    items = sorted(items, key=lambda x: (-x["quantity_sold"], x.get("offer_id") or ""))
    total_items = sum(i["quantity_sold"] for i in items)
    total_orders = len(set(posting_numbers))
    return {
        "range": {"since": start.isoformat() + "Z", "to": end.isoformat() + "Z"},
        "items": items,
        "total_items": total_items,
        "total_orders": total_orders,
    }

@router.get("/sales_today_raw")
async def sales_today_raw(
    include_statuses: str = "awaiting_assembly,awaiting_packaging,awaiting_deliver,delivering,delivered,canceled",
    since: str | None = None,
    to: str | None = None,
    tz_offset_hours: int = 0,
    include_canceled: bool = True,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Считает продажи за сегодня по незавершённым статусам: только количество единиц,
    без финансовых показателей. Полезно для оперативной витрины до доставки.
    Параметр include_statuses — через запятую.
    status — фильтр по одному статусу (если передан, override include_statuses).
    """
    statuses = {s.strip() for s in include_statuses.split(",") if s.strip()}
    start, end = _range_with_tz(since, to, tz_offset_hours)
    await _ensure_data_for_range(db, start, end)
    # Считаем по дате "Принят в обработку" (in_process_at), как в отчёте Ozon
    postings_q = (
        db.query(OrderPosting.posting_number, OrderPosting.status)
        .filter(OrderPosting.in_process_at >= start.isoformat() + "Z")
        .filter(OrderPosting.in_process_at < end.isoformat() + "Z")
    )
    rows = postings_q.all()
    
    if status:
        # Фильтруем только по указанному статусу
        postings = [(pn, st) for (pn, st) in rows if st and st.lower() == status.lower()]
    else:
        # Не фильтруем по статусам: считаем все заказы за день принятия в обработку
        # Если нужно скрыть отменённые, можно использовать include_canceled=false
        postings = [
            (pn, st) for (pn, st) in rows
            if include_canceled or (st is None or ("cancel" not in st.lower()))
        ]
    # Подготовим сводку по статусам в выборке
    status_counts = {}
    for _, st in postings:
        label = st or "unknown"
        status_counts[label] = status_counts.get(label, 0) + 1
    posting_numbers = [p[0] for p in postings]
    # Агрегируем на стороне БД
    amount_expr = func.sum(func.coalesce(OrderProduct.price, 0) * func.coalesce(OrderProduct.quantity, 0))
    rows_products = (
        db.query(
            OrderProduct.offer_id,
            OrderProduct.sku,
            OrderProduct.name,
            func.sum(OrderProduct.quantity).label("quantity"),
            func.count(func.distinct(OrderProduct.posting_number)).label("orders_count"),
            amount_expr.label("amount_raw"),
        )
        .filter(OrderProduct.posting_number.in_(posting_numbers))
        .group_by(OrderProduct.offer_id, OrderProduct.sku, OrderProduct.name)
        .all()
    )

    items = [
        {
            "offer_id": r.offer_id,
            "sku": r.sku,
            "name": r.name,
            "quantity": r.quantity or 0,
            "amount_raw": r.amount_raw or 0,
            "orders_count": r.orders_count or 0,
        }
        for r in rows_products
    ]

    unique_postings_total = len(set(posting_numbers))
    return {
        "range": {"since": start.isoformat() + "Z", "to": end.isoformat() + "Z"},
        "items": sorted(items, key=lambda x: (-x["quantity"], x.get("offer_id") or "")),
        "total_items": sum(v["quantity"] for v in items),
        "total_orders": unique_postings_total,
        "total_amount_raw": sum(v.get("amount_raw", 0) for v in items),
        "statuses": sorted({st for _, st in rows if st}),
        "by_status": [{"status": k, "count": v} for k, v in sorted(status_counts.items(), key=lambda x: (-x[1], x[0]))],
    }

@router.get("/orders_today")
async def orders_today(db: Session = Depends(get_db)):
    start = datetime.utcnow().date().isoformat() + 'T00:00:00Z'
    end = datetime.utcnow().date().isoformat() + 'T23:59:59Z'
    q = db.query(Order).filter(Order.created_at >= start).filter(Order.created_at <= end)
    total = q.count()
    rows = q.all()
    stats = {}
    for r in rows:
        st = r.status or "unknown"
        stats[st] = stats.get(st, 0) + 1
    by_status = [{"status": k, "count": v} for k, v in sorted(stats.items(), key=lambda x: (-x[1], x[0]))]
    return {"date": start[:10], "total": total, "by_status": by_status}
