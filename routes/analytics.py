from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from db.database import OrderPosting, OrderProduct, Order, get_db, SessionLocal
import asyncio
from services.sync import fetch_and_save_orders, _valid_posting_number
from services.enrichment import enrich_posting_from_ozon

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _parse_iso(dt: str) -> datetime:
    return datetime.fromisoformat(dt.replace("Z", ""))


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
        pns = [o.get("posting_number") for o in orders if _valid_posting_number(o.get("posting_number"))]
        if pns:
            existing = set(r[0] for r in db.query(OrderPosting.posting_number).filter(OrderPosting.posting_number.in_(pns)).all())
            targets = [pn for pn in set(pns) if pn not in existing]
            if targets:
                sem = asyncio.Semaphore(4)
                async def run_one(pn):
                    async with sem:
                        def _work():
                            local_db = SessionLocal()
                            try:
                                enrich_posting_from_ozon(pn, local_db)
                            finally:
                                local_db.close()
                        await asyncio.to_thread(_work)
                await asyncio.gather(*(run_one(pn) for pn in targets))
@router.get("/sales_by_date")
async def sales_by_date(date: str, tz_offset_hours: int = 0, db: Session = Depends(get_db)):
    """Агрегаты по delivered за конкретную локальную дату (с учётом tz_offset_hours)."""
    target = datetime.fromisoformat(date)  # YYYY-MM-DD
    local_start = datetime(target.year, target.month, target.day)
    start = local_start - timedelta(hours=tz_offset_hours)
    end = start + timedelta(days=1)
    return await sales_today(since=start.isoformat() + "Z", to=end.isoformat() + "Z", tz_offset_hours=0, db=db)

@router.get("/sales_range")
async def sales_range(since: str, to: str, tz_offset_hours: int = 0, db: Session = Depends(get_db)):
    """Агрегаты по delivered за диапазон с учётом tz_offset_hours.
    Если offset != 0 — считаем, что since/to локальные и конвертируем в UTC.
    """
    start, end = _range_with_tz(since, to, tz_offset_hours)
    return await sales_today(since=start.isoformat() + "Z", to=end.isoformat() + "Z", tz_offset_hours=0, db=db)

@router.get("/sales_today")
async def sales_today(
    since: str | None = None,
    to: str | None = None,
    tz_offset_hours: int = 0,
    db: Session = Depends(get_db),
):
    # Диапазон в UTC с учётом локального смещения
    start, end = _range_with_tz(since, to, tz_offset_hours)
    await _ensure_data_for_range(db, start, end)
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
    products = db.query(OrderProduct).filter(OrderProduct.posting_number.in_(posting_numbers)).all()
    agg = {}
    for pr in products:
        key = pr.offer_id or (str(pr.sku) if pr.sku is not None else "<no-offer>")
        if key not in agg:
            agg[key] = {
                "offer_id": pr.offer_id,
                "sku": pr.sku,
                "name": pr.name,
                "quantity_sold": 0,
                "total_payout": 0,
                "orders_count": 0,
                "_postings": set(),
            }
        q = pr.quantity or 0
        agg[key]["quantity_sold"] += q
        agg[key]["total_payout"] += pr.payout or 0
        pn = getattr(pr, "posting_number", None)
        if pn and pn not in agg[key]["_postings"]:
            agg[key]["_postings"].add(pn)
            agg[key]["orders_count"] += 1
    # Очистим служебные поля
    for v in agg.values():
        v.pop("_postings", None)
    items = sorted(agg.values(), key=lambda x: (-x["quantity_sold"], x.get("offer_id") or ""))
    total_items = sum(i["quantity_sold"] for i in items)
    total_orders = sum(i.get("orders_count", 0) for i in items)
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
    db: Session = Depends(get_db),
):
    """
    Считает продажи за сегодня по незавершённым статусам: только количество единиц,
    без финансовых показателей. Полезно для оперативной витрины до доставки.
    Параметр include_statuses — через запятую.
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
    products = db.query(OrderProduct).filter(OrderProduct.posting_number.in_(posting_numbers)).all()
    agg = {}
    for pr in products:
        key = pr.offer_id or str(pr.sku)
        if key not in agg:
            agg[key] = {
                "offer_id": pr.offer_id,
                "sku": pr.sku,
                "name": pr.name,
                "quantity": 0,
                "amount_raw": 0,
                "orders_count": 0,
                "_postings": set(),
            }
        q = pr.quantity or 0
        agg[key]["quantity"] += q
        # Учёт количества заказов (уникальных постингов) по артикулу
        pn = getattr(pr, "posting_number", None)
        if pn and pn not in agg[key]["_postings"]:
            agg[key]["_postings"].add(pn)
            agg[key]["orders_count"] += 1
        # Если есть цена товара (unit_price), оценим сумму заказа как цена * количество
        # В некоторых интеграциях цена хранится в pr.price; используем, если поле существует
        unit_price = getattr(pr, "price", None)
        if unit_price is not None:
            try:
                agg[key]["amount_raw"] += (unit_price or 0) * q
            except Exception:
                pass
    # Очистим служебные поля
    for v in agg.values():
        if "_postings" in v:
            v.pop("_postings", None)
    # Уникальные отправления по всему выбору для корректного тотала заказов
    unique_postings_total = len(set(posting_numbers))
    return {
        "range": {"since": start.isoformat() + "Z", "to": end.isoformat() + "Z"},
        "items": sorted(agg.values(), key=lambda x: (-x["quantity"], x.get("offer_id") or "")),
        "total_items": sum(v["quantity"] for v in agg.values()),
        "total_orders": unique_postings_total,
        "total_amount_raw": sum(v.get("amount_raw", 0) for v in agg.values()),
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
