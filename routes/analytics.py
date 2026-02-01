from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from db.database import OrderPosting, OrderProduct, Order, get_db, User
import asyncio
import logging
from services.sync import fetch_and_save_orders, run_enrichment_batch
from services.enrichment import enrich_posting_from_ozon
from utils.common import valid_posting_number
from routes.auth_endpoints import get_current_user

router = APIRouter(prefix="/analytics", tags=["analytics"])
logger = logging.getLogger("uvicorn.error")


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

async def _ensure_data_for_range(db: Session, start: datetime, end: datetime, user_id: int):
    """
    Если за диапазон нет данных в БД, подтянуть их из Ozon и обогатить постинги.
    """
    since_iso = start.isoformat() + "Z"
    to_iso = end.isoformat() + "Z"
    has_orders = db.query(Order).filter(Order.user_id == user_id).filter(Order.created_at >= since_iso).filter(Order.created_at < to_iso).count() > 0
    has_postings = db.query(OrderPosting).filter(OrderPosting.user_id == user_id).filter(OrderPosting.created_at >= since_iso).filter(OrderPosting.created_at < to_iso).count() > 0
    if not (has_orders or has_postings):
        try:
            # Синхронизируем заказы для текущего пользователя
            res = await asyncio.to_thread(fetch_and_save_orders, since_iso, to_iso, "", 50, 0, True, True, False, user_id, db)
            orders = res.get("orders") or []
            pns = [o.get("posting_number") for o in orders if valid_posting_number(o.get("posting_number"))]
            if pns:
                existing = set(r[0] for r in db.query(OrderPosting.posting_number).filter(OrderPosting.user_id == user_id).filter(OrderPosting.posting_number.in_(pns)).all())
                targets = [pn for pn in set(pns) if pn not in existing]
                if targets:
                    # Обогащаем постинги для текущего пользователя
                    user = db.query(User).filter(User.id == user_id).first()
                    if user:
                        for pn in targets:
                            try:
                                await enrich_posting_from_ozon(pn, user, db)
                            except Exception as e:
                                logger.debug(f"Ошибка обогащения {pn}: {e}")
        except Exception as e:
            # Если синхронизация не работает (нет API ключа и т.д.), продолжаем работу с пустыми данными
            logger.debug(f"_ensure_data_for_range ошибка для user_id={user_id}: {e}")
            pass
@router.get("/sales_by_date")
async def sales_by_date(
    date: str, 
    tz_offset_hours: int = 0, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Агрегаты по delivered за конкретную локальную дату (с учётом tz_offset_hours)."""
    target = datetime.fromisoformat(date)  # YYYY-MM-DD
    local_start = datetime(target.year, target.month, target.day)
    start = local_start - timedelta(hours=tz_offset_hours)
    end = start + timedelta(days=1)
    return await sales_today(since=start.isoformat() + "Z", to=end.isoformat() + "Z", tz_offset_hours=0, db=db, current_user=current_user)

@router.get("/sales_range")
async def sales_range(
    since: str, 
    to: str, 
    tz_offset_hours: int = 0, 
    status: str | None = None, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Агрегаты по delivered за диапазон с учётом tz_offset_hours.
    Если offset != 0 — считаем, что since/to локальные и конвертируем в UTC.
    status — фильтр по статусу (если передан, override на delivered).
    """
    start, end = _range_with_tz(since, to, tz_offset_hours)
    return await sales_today(since=start.isoformat() + "Z", to=end.isoformat() + "Z", tz_offset_hours=0, status=status, db=db, current_user=current_user)

@router.get("/sales_today")
async def sales_today(
    since: str | None = None,
    to: str | None = None,
    tz_offset_hours: int = 0,
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Диапазон в UTC с учётом локального смещения
    start, end = _range_with_tz(since, to, tz_offset_hours)
    await _ensure_data_for_range(db, start, end, current_user.id)
    
    if status:
        # Фильтруем по указанному статусу
        postings_q = (
            db.query(OrderPosting.posting_number, OrderPosting.status)
            .filter(OrderPosting.user_id == current_user.id)
            .filter(OrderPosting.in_process_at >= start.isoformat() + "Z")
            .filter(OrderPosting.in_process_at < end.isoformat() + "Z")
        )
        posting_numbers = _filter_items_by_status([], postings_q, status, db)
    else:
        # По умолчанию delivered - только реально доставленные (substatus = posting_received)
        postings = (
            db.query(OrderPosting.posting_number)
            .filter(OrderPosting.user_id == current_user.id)
            .filter(OrderPosting.status == "delivered")
            .filter(OrderPosting.substatus == "posting_received")  # Реально получено покупателем
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
            .filter(Order.user_id == current_user.id)
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
        .filter(OrderProduct.user_id == current_user.id)
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
    current_user: User = Depends(get_current_user),
):
    """
    Считает продажи за сегодня по незавершённым статусам: только количество единиц,
    без финансовых показателей. Полезно для оперативной витрины до доставки.
    Параметр include_statuses — через запятую.
    status — фильтр по одному статусу (если передан, override include_statuses).
    """
    statuses = {s.strip() for s in include_statuses.split(",") if s.strip()}
    start, end = _range_with_tz(since, to, tz_offset_hours)
    await _ensure_data_for_range(db, start, end, current_user.id)
    # Считаем по дате "Принят в обработку" (in_process_at), как в отчёте Ozon
    postings_q = (
        db.query(OrderPosting.posting_number, OrderPosting.status)
        .filter(OrderPosting.user_id == current_user.id)
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
async def orders_today(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    start = datetime.utcnow().date().isoformat() + 'T00:00:00Z'
    end = datetime.utcnow().date().isoformat() + 'T23:59:59Z'
    q = db.query(Order).filter(Order.user_id == current_user.id).filter(Order.created_at >= start).filter(Order.created_at <= end)
    total = q.count()
    rows = q.all()
    stats = {}
    for r in rows:
        st = r.status or "unknown"
        stats[st] = stats.get(st, 0) + 1
    by_status = [{"status": k, "count": v} for k, v in sorted(stats.items(), key=lambda x: (-x[1], x[0]))]
    return {"date": start[:10], "total": total, "by_status": by_status}

@router.get("/sales_by_sku_monthly")
async def sales_by_sku_monthly(
    offer_id: str | None = None,
    sku: str | None = None,
    months_back: int = 12,
    mode: str = "delivered",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Получить динамику продаж по месяцам для конкретного артикула.
    Параметры:
    - offer_id: ID предложения (или sku для фильтра)
    - sku: SKU товара (или offer_id для фильтра)
    - months_back: сколько месяцев назад смотреть (по умолчанию 12)
    - mode: 'delivered' (финансы, по дате доставки) или 'shipped' (отгрузки, по дате принятия в обработку)
    
    Возвращает: список объектов {month, quantity_sold, total_payout, orders_count}
    """
    if not offer_id and not sku:
        return {"error": "Укажите offer_id или sku", "data": []}
    
    if mode not in ("delivered", "shipped"):
        mode = "delivered"
    
    # Берём постинги из последних N месяцев
    now = datetime.utcnow()
    start_date = now - timedelta(days=30 * months_back)
    start_iso = start_date.isoformat() + "Z"
    
    # Фильтруем постинги в зависимости от режима
    if mode == "delivered":
        # Режим "Финансы": только delivered, группировка по fact_delivery_date
        posting_q = db.query(OrderPosting.posting_number).filter(
            OrderPosting.user_id == current_user.id,
            OrderPosting.status == "delivered",
            OrderPosting.fact_delivery_date >= start_iso
        )
    else:  # mode == "shipped"
        # Режим "Отгрузки": все, кроме отмененных, группировка по in_process_at
        posting_q = db.query(OrderPosting.posting_number).filter(
            OrderPosting.user_id == current_user.id,
            ~OrderPosting.status.like("%cancel%"),
            OrderPosting.in_process_at >= start_iso
        )
    
    posting_numbers = [p[0] for p in posting_q.all()]
    
    if not posting_numbers:
        return {"data": [], "sku": sku or offer_id, "mode": mode}
    
    # Фильтруем товары по offer_id И sku (оба параметра)
    product_filter = db.query(OrderProduct).filter(
        OrderProduct.user_id == current_user.id,
        OrderProduct.posting_number.in_(posting_numbers)
    )
    
    if offer_id:
        product_filter = product_filter.filter(OrderProduct.offer_id == offer_id)
    if sku:
        product_filter = product_filter.filter(OrderProduct.sku == sku)
    
    products = product_filter.all()
    
    if not products:
        return {"data": [], "sku": sku or offer_id, "mode": mode}
    
    # Группируем по месяцам
    monthly_data = {}
    for prod in products:
        # Берём дату из связанного постинга
        posting = db.query(OrderPosting).filter(
            OrderPosting.posting_number == prod.posting_number
        ).first()
        
        if not posting:
            continue
        
        # Выбираем дату в зависимости от режима
        if mode == "delivered":
            date_field = posting.fact_delivery_date
        else:  # mode == "shipped"
            date_field = posting.in_process_at
        
        if not date_field:
            continue
        
        # Парсим дату
        try:
            target_date = datetime.fromisoformat(date_field.replace("Z", ""))
            month_key = f"{target_date.year}-{target_date.month:02d}"
        except Exception:
            continue
        
        if month_key not in monthly_data:
            monthly_data[month_key] = {
                "month": month_key,
                "quantity_sold": 0,
                "total_payout": 0,
                "orders_count": set(),
            }
        
        monthly_data[month_key]["quantity_sold"] += prod.quantity or 0

        # В режиме отгрузок считаем оборот (price * qty), в финансах — payout
        if mode == "shipped":
            price = prod.price or 0
            qty = prod.quantity or 0
            money_value = price * qty
        else:
            money_value = prod.payout or 0

        monthly_data[month_key]["total_payout"] += money_value
        monthly_data[month_key]["orders_count"].add(prod.posting_number)
    
    # Конвертируем в список и сортируем по месяцам
    result = [
        {
            "month": v["month"],
            "quantity_sold": v["quantity_sold"],
            "total_payout": v["total_payout"],
            "orders_count": len(v["orders_count"]),
        }
        for v in monthly_data.values()
    ]
    result.sort(key=lambda x: x["month"])
    
    # Заполняем недостающие месяцы нулями для красивого графика
    if result:
        first_month = result[0]["month"]
        last_month = result[-1]["month"]
        
        from datetime import date as date_class
        year, month = map(int, first_month.split("-"))
        start_date_obj = date_class(year, month, 1)
        year, month = map(int, last_month.split("-"))
        # Если месяц < 12, то это последний день месяца
        if month == 12:
            end_date_obj = date_class(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date_obj = date_class(year, month + 1, 1) - timedelta(days=1)
        
        all_months = {}
        current = start_date_obj
        while current <= end_date_obj:
            month_key = f"{current.year}-{current.month:02d}"
            if month_key not in all_months:
                all_months[month_key] = {
                    "month": month_key,
                    "quantity_sold": 0,
                    "total_payout": 0,
                    "orders_count": 0,
                }
            current = date_class(current.year, current.month + 1, 1) if current.month < 12 else date_class(current.year + 1, 1, 1)
        
        for item in result:
            all_months[item["month"]] = item
        
        result = sorted(all_months.values(), key=lambda x: x["month"])
    
    return {
        "data": result,
        "sku": sku or offer_id,
        "mode": mode,
        "months_back": months_back,
    }
