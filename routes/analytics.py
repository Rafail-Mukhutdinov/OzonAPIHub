from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from datetime import datetime, timedelta, timezone
from db.database import OrderPosting, OrderProduct, Order, get_db, User
import logging
import json
from utils.common import to_msk, parse_ozon_datetime
from utils.auth import get_current_user

router = APIRouter(prefix="/analytics", tags=["analytics"])
logger = logging.getLogger("OzonAPIHub")

def parse_msk_date(value: str, end_of_day: bool = False, tz_offset_hours: int = 3) -> datetime | None:
    """Интерпретирует дату без времени как день в зоне с указанным смещением.
    Если передан полный ISO-таймстамп — парсим как есть.
    """
    if not value or not isinstance(value, str):
        return None
    trimmed = value.strip()
    if len(trimmed) > 10 or 'T' in trimmed or '+' in trimmed or 'Z' in trimmed:
        return parse_ozon_datetime(trimmed)

    try:
        parts = trimmed.split('-')
        if len(parts) == 3:
            year, month, day = map(int, parts)
            tz = timezone(timedelta(hours=tz_offset_hours))
            if end_of_day:
                return datetime(year, month, day, 23, 59, 59, 999999, tzinfo=tz)
            return datetime(year, month, day, 0, 0, 0, 0, tzinfo=tz)
    except ValueError:
        pass

    return parse_ozon_datetime(trimmed)

def is_cancelled(st):
    status = (st or "").lower()
    return any(x in status for x in ["cancelled", "отменен", "отменён", "canceled"])

def _get_unified_postings(db: Session, user_id: int, since_utc: datetime, to_utc: datetime, include_cancelled: bool = True):
    """
    Собирает уникальные постинги из сырых (Order) и нормализованных (OrderPosting) таблиц.
    """
    # native datetime objects are now used for filtering
    search_since = since_utc.replace(tzinfo=None)
    search_to = to_utc.replace(tzinfo=None)

    # 1. Собираем данные из сырой таблицы
    raw_orders = db.query(Order.posting_number, Order.created_at, Order.status, Order.data).filter(
        Order.user_id == user_id,
        or_(
            Order.created_at.between(search_since, search_to),
            Order.updated_at.between(search_since, search_to)
        )
    ).all()

    # 2. Собираем данные из нормализованной таблицы
    norm_orders = db.query(OrderPosting.posting_number, OrderPosting.created_at, OrderPosting.status, OrderPosting.in_process_at).filter(
        OrderPosting.user_id == user_id,
        or_(
            OrderPosting.created_at.between(search_since, search_to),
            OrderPosting.in_process_at.between(search_since, search_to)
        )
    ).all()

    postings_map = {}

    # Сначала заполняем из сырых
    for pn, cr, st, data in raw_orders:
        if not pn: continue
        if not include_cancelled and is_cancelled(st): continue

        in_proc = None
        if data and isinstance(data, dict):
            in_proc = data.get("in_process_at")

        postings_map[pn] = {
            "posting_number": pn,
            "created_at": cr,
            "in_process_at": in_proc,
            "status": st,
            "source": "raw"
        }

    # Затем перезаписываем из нормализованных (приоритет)
    for pn, cr, st, in_proc in norm_orders:
        if not pn: continue
        if not include_cancelled and is_cancelled(st):
            if pn in postings_map: del postings_map[pn]
            continue

        postings_map[pn] = {
            "posting_number": pn,
            "created_at": cr,
            "in_process_at": in_proc,
            "status": st,
            "source": "normalized"
        }

    return postings_map

@router.get("/daily_stats")
async def daily_stats(
    since: str,
    to: str,
    include_cancelled: bool = Query(True),
    tz_offset_hours: int = Query(3),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Аналитика по дням.
    """
    since_dt = parse_msk_date(since, tz_offset_hours=tz_offset_hours)
    to_dt = parse_msk_date(to, end_of_day=True, tz_offset_hours=tz_offset_hours)

    if not since_dt or not to_dt:
        raise HTTPException(status_code=400, detail="Некорректный формат даты.")

    # Приводим к UTC для поиска в БД
    since_utc = since_dt.astimezone(timezone.utc)
    to_utc = to_dt.astimezone(timezone.utc)

    # Расширяем окно поиска на +/- 24 часа для безопасности
    search_since_dt = since_utc - timedelta(hours=24)
    search_to_dt = to_utc + timedelta(hours=24)

    postings_map = _get_unified_postings(db, current_user.id, search_since_dt, search_to_dt, include_cancelled)

    if not postings_map:
        return {"data": []}

    # Группируем постинги по местным датам
    valid_pns_by_date = {}
    date_since_local = since_dt.astimezone(timezone(timedelta(hours=tz_offset_hours))).date()
    date_to_local = to_dt.astimezone(timezone(timedelta(hours=tz_offset_hours))).date()

    for pn, data in postings_map.items():
        # ПРИОРИТЕТ ДАТЫ:
        # Если есть in_process_at, используем его (важно для B2B заказов, которые Озон
        # считает в отчетах по дате обработки). Если нет - берем дату создания.
        best_date = data.get("in_process_at") or data["created_at"]
        dt_local = to_msk(best_date, tz_offset_hours)
        if not dt_local: continue

        local_date_obj = dt_local.date()
        if date_since_local <= local_date_obj <= date_to_local:
            local_date_str = local_date_obj.strftime("%Y-%m-%d")
            if local_date_str not in valid_pns_by_date: valid_pns_by_date[local_date_str] = []
            valid_pns_by_date[local_date_str].append(pn)

    # Пытаемся взять агрегированные данные по всем нужным постингам одним запросом
    # Группируем по номеру постинга, чтобы потом сопоставить с датами
    product_stats = db.query(
        OrderProduct.posting_number,
        func.sum(OrderProduct.quantity).label("q"),
        func.sum(OrderProduct.price * OrderProduct.quantity).label("r")
    ).filter(
        OrderProduct.user_id == current_user.id,
        OrderProduct.posting_number.in_(list(postings_map.keys()))
    ).group_by(OrderProduct.posting_number).all()

    # Создаем быстрый маппинг: номер постинга -> (кол-во, выручка)
    stats_by_pn = {r[0]: (int(r[1] or 0), int(r[2] or 0)) for r in product_stats}

    # ФОЛЛБЕК для тех постингов, которых нет в нормализованной таблице товаров
    missing_pns = set(postings_map.keys()) - set(stats_by_pn.keys())
    if missing_pns:
        raw_rows = db.query(Order.posting_number, Order.data).filter(
            Order.user_id == current_user.id,
            Order.posting_number.in_(list(missing_pns))
        ).all()
        for pn, data in raw_rows:
            if data and isinstance(data, dict):
                q_sum, r_sum = 0, 0
                for p in data.get("products", []):
                    q = int(p.get("quantity") or 0)
                    pr = int(float(p.get("price") or 0))
                    q_sum += q
                    r_sum += (q * pr)
                stats_by_pn[pn] = (q_sum, r_sum)

    result_data = []
    for local_date, pns in valid_pns_by_date.items():
        day_items = 0
        day_revenue = 0
        for pn in pns:
            q, r = stats_by_pn.get(pn, (0, 0))
            day_items += q
            day_revenue += r

        result_data.append({
            "date": local_date,
            "items": day_items,
            "revenue": day_revenue,
            "orders_count": len(pns)
        })

    result_data.sort(key=lambda x: x["date"])
    return {"data": result_data}

@router.get("/sales_report")
@router.get("/sales_today_raw")
@router.get("/sales_range")
async def sales_report_universal(
    since: str,
    to: str,
    include_cancelled: bool = Query(True),
    tz_offset_hours: int = Query(3),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Универсальный отчет по продажам с поддержкой фоллбека на сырые данные.
    """
    since_dt = parse_msk_date(since, tz_offset_hours=tz_offset_hours)
    to_dt = parse_msk_date(to, end_of_day=True, tz_offset_hours=tz_offset_hours)

    if not since_dt or not to_dt:
        raise HTTPException(status_code=400, detail="Некорректный формат даты")

    since_utc = since_dt.astimezone(timezone.utc)
    to_utc = to_dt.astimezone(timezone.utc)

    search_since_dt = since_utc - timedelta(hours=24)
    search_to_dt = to_utc + timedelta(hours=24)

    postings_map = _get_unified_postings(db, current_user.id, search_since_dt, search_to_dt, include_cancelled)

    local_tz = timezone(timedelta(hours=tz_offset_hours))
    date_since_local = since_dt.astimezone(local_tz).date()
    date_to_local = to_dt.astimezone(local_tz).date()

    final_postings = []
    for pn, data in postings_map.items():
        # Аналогичный приоритет даты для универсального отчета
        best_date = data.get("in_process_at") or data["created_at"]
        dt_local = to_msk(best_date, tz_offset_hours)
        if not dt_local: continue
        if date_since_local <= dt_local.date() <= date_to_local:
            final_postings.append(pn)

    if not final_postings:
        return {"items": [], "total_items": 0, "total_orders": 0, "total_amount_raw": 0}

    # Считаем из OrderProduct
    rows = db.query(
        OrderProduct.offer_id, OrderProduct.sku, OrderProduct.name,
        func.sum(OrderProduct.quantity).label("q"),
        func.sum(OrderProduct.price * OrderProduct.quantity).label("r"),
        func.max(OrderProduct.image_url).label("img") # Берем любой URL картинки для этого SKU
    ).filter(
        OrderProduct.user_id == current_user.id,
        OrderProduct.posting_number.in_(final_postings)
    ).group_by(OrderProduct.offer_id, OrderProduct.sku, OrderProduct.name).all()

    items_map = {}
    for r in rows:
        key = (r.offer_id, r.sku)
        items_map[key] = {
            "offer_id": r.offer_id, "sku": r.sku, "name": r.name,
            "quantity": int(r.q or 0), "amount_raw": int(r.r or 0),
            "image_url": r.img
        }

    # ФОЛЛБЕК
    pns_with_products = {r[0] for r in db.query(OrderProduct.posting_number).filter(
        OrderProduct.user_id == current_user.id,
        OrderProduct.posting_number.in_(final_postings)
    ).all()}

    missing_pns = set(final_postings) - pns_with_products
    if missing_pns:
        raw_rows = db.query(Order.data).filter(
            Order.user_id == current_user.id,
            Order.posting_number.in_(list(missing_pns))
        ).all()
        for row in raw_rows:
            if row[0] and isinstance(row[0], dict):
                for p in row[0].get("products", []):
                    oid, sku = p.get("offer_id"), p.get("sku")
                    qty = int(p.get("quantity") or 0)
                    pr = int(float(p.get("price") or 0))
                    key = (oid, sku)
                    if key in items_map:
                        items_map[key]["quantity"] += qty
                        items_map[key]["amount_raw"] += (qty * pr)
                    else:
                        items_map[key] = {
                            "offer_id": oid, "sku": sku, "name": p.get("name"),
                            "quantity": qty, "amount_raw": qty * pr
                        }

    items = list(items_map.values())
    items.sort(key=lambda x: -x["quantity"])

    # Вычисляем суммарные финансовые показатели (payout/commission)
    # ПРИМЕЧАНИЕ: финансовые показатели по-прежнему берем только из нормализованных данных,
    # так как в сыром списке FBO их может не быть в полном объеме.
    totals = db.query(
        func.coalesce(func.sum(OrderProduct.payout), 0),
        func.coalesce(func.sum(OrderProduct.commission_amount), 0)
    ).filter(
        OrderProduct.user_id == current_user.id,
        OrderProduct.posting_number.in_(final_postings)
    ).first()

    total_payout = int(totals[0] or 0)
    total_commission = int(totals[1] or 0)
    profit = total_payout - total_commission

    # Считаем отмены отдельно
    def _is_cancelled_local(st):
        status = (st or "").lower()
        return any(x in status for x in ["cancelled", "отменен", "отменён", "canceled"])

    cancelled_pns = [pn for pn in final_postings if _is_cancelled_local(postings_map.get(pn, {}).get("status"))]
    total_cancelled_amount = 0
    total_cancelled_count = 0

    if cancelled_pns:
        c_res = db.query(
            func.sum(OrderProduct.quantity),
            func.sum(OrderProduct.price * OrderProduct.quantity)
        ).filter(
            OrderProduct.user_id == current_user.id,
            OrderProduct.posting_number.in_(cancelled_pns)
        ).first()
        total_cancelled_count = int(c_res[0] or 0)
        total_cancelled_amount = int(c_res[1] or 0)

    return {
        "items": items,
        "total_items": sum(i["quantity"] for i in items),
        "total_orders": len(final_postings),
        "total_amount_raw": sum(i["amount_raw"] for i in items),
        "total_cancelled_amount": total_cancelled_amount,
        "total_cancelled_count": total_cancelled_count,
        "total_payout": total_payout,
        "total_commission": total_commission,
        "profit": profit
    }
