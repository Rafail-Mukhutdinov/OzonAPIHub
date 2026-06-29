from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from datetime import datetime, timedelta, timezone
from db.database import OrderPosting, OrderProduct, Order, get_db, User, Cost, OzonAccrual
import logging
import json
from utils.common import to_msk, parse_ozon_datetime
from utils.auth import get_current_user

router = APIRouter(prefix="/analytics", tags=["analytics"])
logger = logging.getLogger("OzonAPIHub")

# Маппинг типов услуг Ozon API v1 Accrual
OZON_SERVICE_TYPES = {
    1: "Комиссия Ozon",
    32: "Логистика",
    29: "Сборка заказа",
    98: "Последняя миля",
    74: "Эквайринг",
    45: "Магистраль",
    54: "Логистика возврата",
    12: "Прочие услуги (склад)",
    59: "Магистраль возврата",
}

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
                    oid = p.get("offer_id")
                    try:
                        sku = int(p.get("sku") or 0)
                    except (ValueError, TypeError):
                        sku = 0
                        
                    qty = int(p.get("quantity") or 0)
                    pr = int(float(p.get("price") or 0))
                    key = (oid, sku)
                    
                    if key in items_map:
                        items_map[key]["quantity"] += qty
                        items_map[key]["amount_raw"] += (qty * pr)
                    else:
                        items_map[key] = {
                            "offer_id": oid,
                            "sku": sku,
                            "name": p.get("name") or "Товар",
                            "quantity": qty,
                            "amount_raw": qty * pr,
                            "image_url": None
                        }

    # Попытка восстановить отсутствующие image_url из других заказов того же SKU
    skus_needing_img = [v["sku"] for v in items_map.values() if not v.get("image_url")]
    if skus_needing_img:
        # Ищем в БД по всем заказам пользователя любые картинки для этих SKU
        img_rows = db.query(
            OrderProduct.sku, 
            func.max(OrderProduct.image_url).label("img")
        ).filter(
            OrderProduct.user_id == current_user.id,
            OrderProduct.sku.in_(skus_needing_img),
            OrderProduct.image_url != None,
            OrderProduct.image_url != ""
        ).group_by(OrderProduct.sku).all()
        
        sku_img_map = {r.sku: r.img for r in img_rows}
        for it in items_map.values():
            if not it.get("image_url") and it["sku"] in sku_img_map:
                it["image_url"] = sku_img_map[it["sku"]]

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

    total_payout = abs(int(totals[0] or 0))
    total_commission = abs(int(totals[1] or 0))

    # Считаем логистику и другие услуги из financial_data постингов
    total_logistics = 0
    postings_data = db.query(OrderPosting.financial_data).filter(
        OrderPosting.user_id == current_user.id,
        OrderPosting.posting_number.in_(final_postings)
    ).all()

    for (f_data,) in postings_data:
        if not f_data or not isinstance(f_data, dict):
            continue

        # Помогаем парсить суммы (могут быть строками)
        def _get_val(v):
            try: return abs(float(v or 0))
            except: return 0

        # 1. Проверяем услуги на уровне всего заказа (если есть)
        services = f_data.get("services", {})
        if isinstance(services, dict):
            for s_val in services.values():
                total_logistics += _get_val(s_val)

        # 2. Проверяем услуги на уровне каждого товара (для FBO/FBS)
        products = f_data.get("products", [])
        if isinstance(products, list):
            for p in products:
                if not isinstance(p, dict): continue
                # В Ozon API услуги лежат в item_services
                item_services = p.get("item_services", {})
                if isinstance(item_services, dict):
                    for s_val in item_services.values():
                        total_logistics += _get_val(s_val)

    # Считаем дополнительные расходы (реклама, хранение) из таблицы Cost
    costs_by_type = db.query(
        Cost.type,
        func.sum(Cost.amount)
    ).filter(
        Cost.user_id == current_user.id,
        Cost.date >= since_utc.replace(tzinfo=None),
        Cost.date <= to_utc.replace(tzinfo=None)
    ).group_by(Cost.type).all()

    costs_dict = {t: abs(float(a or 0)) for t, a in costs_by_type}

    total_advertising = costs_dict.get("advertising", 0) + costs_dict.get("adv", 0)
    total_storage = costs_dict.get("storage", 0)

    # Добавляем логистику из транзакций к логистике из заказов
    total_logistics += costs_dict.get("logistics", 0)

    total_acquiring = costs_dict.get("acquiring", 0)

    # Всё остальное относим в прочие
    other_costs_sum = sum(v for k, v in costs_dict.items() if k not in ["advertising", "adv", "storage", "logistics", "acquiring"])

    total_expenses = total_commission + float(total_logistics) + total_advertising + total_storage + total_acquiring + other_costs_sum
    profit = total_payout - total_expenses

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
        "total_expenses": total_expenses,
        "total_advertising": total_advertising,
        "total_storage": total_storage,
        "total_logistics": int(total_logistics),
        "total_acquiring": total_acquiring,
        "total_other": other_costs_sum,
        "total_payout": total_payout,
        "total_commission": total_commission,
        "profit": profit
    }

@router.get("/expenses_breakdown")
async def expenses_breakdown(
    since: str,
    to: str,
    tz_offset_hours: int = Query(3),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Детализация расходов по категориям с использованием новых данных из OzonAccrual.
    """
    since_dt = parse_msk_date(since, tz_offset_hours=tz_offset_hours)
    to_dt = parse_msk_date(to, end_of_day=True, tz_offset_hours=tz_offset_hours)

    if not since_dt or not to_dt:
        raise HTTPException(status_code=400, detail="Некорректный формат даты")

    since_utc = since_dt.astimezone(timezone.utc).replace(tzinfo=None)
    to_utc = to_dt.astimezone(timezone.utc).replace(tzinfo=None)

    # 1. Считаем расходы из НОВОЙ таблицы OzonAccrual (приоритет)
    accruals = db.query(OzonAccrual).filter(
        OzonAccrual.user_id == current_user.id,
        OzonAccrual.date >= since_utc,
        OzonAccrual.date <= to_utc,
        OzonAccrual.operation_type == 'expense' # Только расходы
    ).all()

    by_category = {
        "Комиссия Ozon": 0.0,
        "Логистика": 0.0,
        "Эквайринг": 0.0,
        "Прочие расходы": 0.0
    }
    ops_by_category = {}

    for acc in accruals:
        cat_name = OZON_SERVICE_TYPES.get(acc.type_id)
        
        # Группируем мелкие услуги в крупные категории для чистоты
        if acc.type_id in [32, 29, 98, 45, 54, 59]:
            cat_name = "Логистика"
        elif acc.type_id == 1:
            cat_name = "Комиссия Ozon"
        elif acc.type_id == 74:
            cat_name = "Эквайринг"
        
        if not cat_name:
            cat_name = "Прочие расходы"

        amount = abs(float(acc.amount or 0))
        if cat_name not in by_category: by_category[cat_name] = 0.0
        by_category[cat_name] += amount

        if cat_name not in ops_by_category:
            ops_by_category[cat_name] = {"total": 0.0, "items": []}
        ops_by_category[cat_name]["total"] += amount
        
        # Добавляем в детализацию
        note = f"Заказ {acc.unit_number}" if acc.unit_number else acc.accrued_category
        if acc.type_id and acc.type_id in OZON_SERVICE_TYPES:
            note += f" ({OZON_SERVICE_TYPES[acc.type_id]})"

        ops_by_category[cat_name]["items"].append({
            "amount": amount,
            "date": acc.date.isoformat() if acc.date else None,
            "notes": note,
            "unit_number": acc.unit_number
        })

    # 2. Добавляем данные из таблицы Cost (для внешних расходов, которых нет в Озоне)
    # Например, налоги, зарплаты или реклама, если она еще не подтянулась в Accruals
    cost_rows = db.query(Cost).filter(
        Cost.user_id == current_user.id,
        Cost.date >= since_utc,
        Cost.date <= to_utc
    ).all()

    for row in cost_rows:
        # Простая эвристика, чтобы не дублировать эквайринг/комиссию, если они уже есть в Accruals
        t = (row.type or "").lower()
        if t in ["acquiring", "commission", "logistics"] and len(accruals) > 0:
            continue # Пропускаем, так как Accruals точнее
            
        cat = "Реклама" if t in ("advertising", "adv") else "Хранение" if t == "storage" else "Прочие расходы"
        
        amount = abs(float(row.amount or 0))
        if cat not in by_category: by_category[cat] = 0.0
        by_category[cat] += amount

        if cat not in ops_by_category:
            ops_by_category[cat] = {"total": 0.0, "items": []}
        ops_by_category[cat]["total"] += amount
        ops_by_category[cat]["items"].append({
            "amount": amount,
            "date": row.date.isoformat() if row.date else None,
            "notes": row.notes or t,
        })

    return {
        "by_category": by_category,
        "details": ops_by_category,
        "total": sum(by_category.values())
    }

@router.get("/expenses_summary")
async def expenses_summary(
    since: str,
    to: str,
    tz_offset_hours: int = Query(3),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Возвращает сумму расходов за указанный период с разбивкой по категориям.
    """
    # Используем существующую логику детализации
    res = await expenses_breakdown(since=since, to=to, tz_offset_hours=tz_offset_hours, db=db, current_user=current_user)

    total = res["total"]
    categories = []

    for name, amount in res["by_category"].items():
        if amount > 0:
            percent = (amount / total * 100) if total > 0 else 0
            categories.append({
                "name": name,
                "amount": amount,
                "percent": round(percent, 1)
            })

    # Сортируем по сумме
    categories.sort(key=lambda x: x["amount"], reverse=True)

    return {
        "since": since,
        "to": to,
        "total": total,
        "categories": categories
    }
