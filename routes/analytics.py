from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from datetime import datetime, timedelta, timezone
import logging

from db.database import get_db, User, Order, OrderPosting, OrderProduct, OzonAccrual, Cost
from utils.auth import get_current_user
from utils.common import to_msk, parse_ozon_datetime

router = APIRouter(prefix="/analytics", tags=["analytics"])
logger = logging.getLogger(__name__)

OZON_SERVICE_TYPES = {
    1000: "Комиссия за продажу",
    1: "Эквайринг",
    12: "Магистраль / Логистика",
    22: "Прочие услуги (Ozon)",
    29: "Последняя миля",
    32: "Логистика (FBO)",
    38: "Прочие услуги (Ozon)",
    39: "Логистика (Доп. услуги)",
    41: "Сборка заказа / Продвижение",
    45: "Обработка отмен",
    46: "Обработка возвратов / Хранение",
    54: "Продвижение (Реклама)",
    59: "Доставка",
    74: "Складское хранение",
    98: "Утилизация",
    101: "Продвижение (Реклама)",
    102: "Бонусы продавца",
    103: "Трафареты (Реклама)",
    104: "Вывод в топ (Реклама)",
    105: "Брендовая полка (Реклама)",
    106: "Рассылка бонусов (Реклама)",
    120: "Продвижение (Акция)",
    305: "Доставка сторонними службами",
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
    Оптимизировано для использования индексов: избегаем OR по разным колонкам.
    """
    search_since = since_utc.replace(tzinfo=None)
    search_to = to_utc.replace(tzinfo=None)

    postings_map = {}

    # 1. Собираем данные из нормализованной таблицы (Приоритетный источник)
    # Используем UNION или раздельные запросы для эффективного использования индексов
    q1 = db.query(OrderPosting.posting_number, OrderPosting.created_at, OrderPosting.status, OrderPosting.in_process_at).filter(
        OrderPosting.user_id == user_id,
        OrderPosting.created_at.between(search_since, search_to)
    )
    q2 = db.query(OrderPosting.posting_number, OrderPosting.created_at, OrderPosting.status, OrderPosting.in_process_at).filter(
        OrderPosting.user_id == user_id,
        OrderPosting.in_process_at.between(search_since, search_to)
    )
    
    # Объединяем результаты в Python (быстрее, чем OR в БД без правильных индексов)
    for pn, cr, st, in_proc in q1.all() + q2.all():
        if not pn or pn in postings_map: continue
        if not include_cancelled and is_cancelled(st): continue

        postings_map[pn] = {
            "posting_number": pn,
            "created_at": cr,
            "in_process_at": in_proc,
            "status": st,
            "source": "normalized"
        }

    # 2. Дозаполняем из сырой таблицы только если нет в нормализованной
    # (Фоллбек для постингов, которые еще не прошли энричмент)
    q3 = db.query(Order.posting_number, Order.created_at, Order.status, Order.data).filter(
        Order.user_id == user_id,
        Order.created_at.between(search_since, search_to)
    )
    # Мы не берем здесь по updated_at, так как это обычно техническое поле, 
    # а основные события (создание/обработка) покрыты выше.
    
    for pn, cr, st, data in q3.all():
        if not pn or pn in postings_map: continue
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

    return postings_map

def get_expense_category(tid: int | None) -> str:
    """Единая логика категоризации услуг Ozon для всех отчетов.
    Синхронизировано с плитками раздела 'Экономика' в ЛК Ozon.
    """
    if tid == 1000:
        return "Комиссия Ozon"
    if tid in [32, 39, 59, 305]:
        return "Логистика (FBO/FBS)"
    if tid == 1:
        return "Эквайринг"
    if tid == 46: 
        return "Хранение"
    if tid in [41, 54, 101, 103, 104, 105, 106, 120]:
        return "Реклама"
    if tid == 45:
        return "Возвраты и отмены"
    # Все остальное (Магистраль 12, Последняя миля 29, Утилизация 98, Складское хранение 74, Прочие 22, 38)
    # Озон объединяет в плитку 'Прочие расходы Ozon'
    return "Прочие расходы Ozon"

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

    # 1. Получаем список отправлений и заказов для статистики по количеству и статусам
    postings_map = _get_unified_postings(db, current_user.id, search_since_dt, search_to_dt, include_cancelled)

    local_tz = timezone(timedelta(hours=tz_offset_hours))
    date_since_local = since_dt.astimezone(local_tz).date()
    date_to_local = to_dt.astimezone(local_tz).date()

    final_postings = []
    for pn, data in postings_map.items():
        best_date = data.get("in_process_at") or data["created_at"]
        dt_local = to_msk(best_date, tz_offset_hours)
        if not dt_local: continue
        if date_since_local <= dt_local.date() <= date_to_local:
            final_postings.append(pn)

    # 2. Агрегируем продажи и себестоимость из OzonAccrual (Финансовый первоисточник)
    # ВАЖНО: выбираем также type_id и operation_type, чтобы отличать продажу/возврат
    # товара (type_id IS NULL) от комиссий и услуг (type_id задан).
    accrual_items_raw = db.query(
        OzonAccrual.sku,
        OzonAccrual.accrued_category,
        OzonAccrual.amount,
        OzonAccrual.quantity,
        OzonAccrual.type_id,
        OzonAccrual.operation_type,
        OzonAccrual.date
    ).filter(
        OzonAccrual.user_id == current_user.id,
        OzonAccrual.date >= since_utc.replace(tzinfo=None),
        OzonAccrual.date <= to_utc.replace(tzinfo=None)
    ).all()

    items_map = {}
    total_cost_price = 0.0
    total_sales_revenue = 0.0
    total_returns_amount = 0.0
    total_commission = 0.0
    total_logistics = 0.0
    total_acquiring = 0.0
    total_advertising = 0.0
    total_storage = 0.0
    total_other_expenses = 0.0
    total_returns_cancels_fee = 0.0 # Услуги по возвратам
    total_manual_expenses = 0.0 # Ручные расходы (не из Ozon)

    # Для оптимизации: собираем суммы по type_id прямо здесь, чтобы не делать второй запрос к БД
    accruals_by_type = {}

    from services.costs import get_batch_product_costs

    # Собираем все уникальные SKU для массового получения себестоимости
    all_skus = list(set(int(r[0]) for r in accrual_items_raw if r[0] and r[4] is None))
    cost_cache = get_batch_product_costs(db, current_user.id, all_skus, to_utc.replace(tzinfo=None))

    for r_sku, r_cat, r_amt, r_qty, r_tid, r_op_type, r_date in accrual_items_raw:
        val = float(r_amt or 0)
        qty = int(r_qty or 1)

        is_product_row = (r_tid is None)

        if is_product_row:
            if val > 0:
                # Продажа товара или компенсация/доплата (sale_amount > 0)
                total_sales_revenue += val
                
                if r_sku:
                    if r_sku not in items_map:
                        items_map[r_sku] = {"sku": r_sku, "name": f"Товар {r_sku}", "quantity": 0, "amount_raw": 0, "image_url": None}
                    items_map[r_sku]["amount_raw"] += val
                    items_map[r_sku]["quantity"] += qty

                    # Используем кэшированную себестоимость
                    cp = cost_cache.get(int(r_sku), 0.0)
                    total_cost_price += (cp * qty)
            elif val < 0:
                total_returns_amount += abs(val)
                if r_sku:
                    cp = cost_cache.get(int(r_sku), 0.0)
                    total_cost_price -= (cp * qty)
        else:
            # Накапливаем услуги для последующей агрегации
            accruals_by_type[r_tid] = accruals_by_type.get(r_tid, 0.0) + val

    # Распределяем накопленные услуги по категориям
    for tid, amt_sum in accruals_by_type.items():
        abs_expense = -float(amt_sum or 0) 
        cat_name = get_expense_category(tid)
        
        if cat_name == "Комиссия Ozon": total_commission += abs_expense
        elif cat_name == "Эквайринг": total_acquiring += abs_expense
        elif cat_name == "Логистика (FBO/FBS)": total_logistics += abs_expense
        elif cat_name == "Реклама": total_advertising += abs_expense
        elif cat_name == "Хранение": total_storage += abs_expense
        elif cat_name == "Возвраты и отмены": total_returns_cancels_fee += abs_expense
        else: total_other_expenses += abs_expense

    # ОБОГАЩЕНИЕ ТОВАРОВ МЕТАДАННЫМИ (Оптимизировано: убран N+1)
    if items_map:
        unique_skus = list(items_map.keys())
        # Берем данные по товарам одним батч-запросом
        products_meta = db.query(OrderProduct).filter(
            OrderProduct.user_id == current_user.id,
            OrderProduct.sku.in_(unique_skus)
        ).all()
        
        # Создаем маппинг SKU -> meta для быстрого доступа
        meta_by_sku = {}
        for p in products_meta:
            if p.sku not in meta_by_sku: # Берем первое вхождение
                meta_by_sku[p.sku] = p
        
        for sku, item in items_map.items():
            meta = meta_by_sku.get(sku)
            if meta:
                item["name"] = meta.name
                item["offer_id"] = meta.offer_id
                item["image_url"] = meta.image_url

    items = list(items_map.values())
    items.sort(key=lambda x: -x["amount_raw"])

    costs_by_type = db.query(
        Cost.type,
        func.sum(Cost.amount)
    ).filter(
        Cost.user_id == current_user.id,
        Cost.date >= since_utc.replace(tzinfo=None),
        Cost.date <= to_utc.replace(tzinfo=None)
    ).group_by(Cost.type).all()

    for c_type, c_amt in costs_by_type:
        t = (c_type or "").lower()
        val = abs(float(c_amt or 0))
        if len(accruals_by_type) > 0 and t in ["acquiring", "commission", "logistics", "advertising", "storage"]:
            continue

        if t in ("advertising", "adv"): total_advertising += val
        elif t == "storage": total_storage += val
        elif t == "logistics": total_logistics += val
        elif t == "acquiring": total_acquiring += val
        elif t == "commission": total_commission += val
        else: total_manual_expenses += val

    total_expenses = (
        total_commission + total_logistics + total_advertising + 
        total_storage + total_acquiring + total_other_expenses + 
        total_returns_cancels_fee + total_cost_price + total_manual_expenses
    )
    profit = total_sales_revenue - total_returns_amount - total_expenses

    cancelled_pns = [pn for pn in final_postings if is_cancelled(postings_map.get(pn, {}).get("status"))]
    total_cancelled_amount = 0.0
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
        total_cancelled_amount = float(c_res[1] or 0.0)

    return {
        "items": items,
        "total_items": sum(i["quantity"] for i in items),
        "total_orders": len(final_postings),
        "total_amount_raw": round(total_sales_revenue, 2), 
        "total_cancelled_amount": total_cancelled_amount,
        "total_cancelled_count": total_cancelled_count,
        "total_expenses": round(total_expenses, 2),
        "total_advertising": round(total_advertising, 2),
        "total_storage": round(total_storage, 2),
        "total_logistics": round(total_logistics, 2),
        "total_acquiring": round(total_acquiring, 2),
        "total_other": round(total_other_expenses + total_returns_cancels_fee + total_manual_expenses, 2),
        "total_returns": round(total_returns_amount, 2), 
        "total_payout": round(total_sales_revenue - total_returns_amount - total_commission - total_acquiring, 2),
        "total_commission": round(total_commission, 2),
        "total_cost_price": round(total_cost_price, 2), 
        "profit": round(profit, 2)
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
    Детализация расходов по категориям (БЕЗ МИНУСОВ).
    """
    since_dt = parse_msk_date(since, tz_offset_hours=tz_offset_hours)
    to_dt = parse_msk_date(to, end_of_day=True, tz_offset_hours=tz_offset_hours)

    if not since_dt or not to_dt:
        raise HTTPException(status_code=400, detail="Некорректный формат даты")

    since_utc = since_dt.astimezone(timezone.utc).replace(tzinfo=None)
    to_utc = to_dt.astimezone(timezone.utc).replace(tzinfo=None)

    accruals = db.query(OzonAccrual).filter(
        OzonAccrual.user_id == current_user.id,
        OzonAccrual.date >= since_utc,
        OzonAccrual.date <= to_utc,
        or_(OzonAccrual.operation_type == 'expense', OzonAccrual.amount < 0)
    ).all()

    by_category = {
        "Комиссия Ozon": 0.0,
        "Логистика (FBO/FBS)": 0.0,
        "Эквайринг": 0.0,
        "Хранение": 0.0,
        "Реклама": 0.0,
        "Возвраты и отмены": 0.0,
        "Прочие расходы Ozon": 0.0
    }
    ops_by_category = {}

    for acc in accruals:
        tid = acc.type_id
        amount = abs(float(acc.amount or 0))
        cat_name = get_expense_category(tid)

        if cat_name not in by_category:
            by_category[cat_name] = 0.0
        by_category[cat_name] += amount

        if cat_name not in ops_by_category:
            ops_by_category[cat_name] = {"total": 0.0, "items": []}
        
        ops_by_category[cat_name]["total"] += amount
        
        note = f"Заказ {acc.unit_number}" if acc.unit_number else acc.accrued_category
        if tid and tid in OZON_SERVICE_TYPES:
            note += f" ({OZON_SERVICE_TYPES[tid]})"

        ops_by_category[cat_name]["items"].append({
            "amount": round(amount, 2),
            "date": acc.date.isoformat() if acc.date else None,
            "notes": note,
            "unit_number": acc.unit_number
        })

    cost_rows = db.query(Cost).filter(
        Cost.user_id == current_user.id,
        Cost.date >= since_utc,
        Cost.date <= to_utc
    ).all()

    for row in cost_rows:
        t = (row.type or "").lower()
        if t in ["acquiring", "commission", "logistics", "advertising", "storage"] and len(accruals) > 0:
            continue
            
        if t in ("advertising", "adv"): cat = "Реклама"
        elif t == "storage": cat = "Хранение"
        elif t == "logistics": cat = "Логистика (FBO/FBS)"
        elif t == "acquiring": cat = "Эквайринг"
        elif t == "commission": cat = "Комиссия Ozon"
        else: cat = "Прочие расходы (ручные)"
        amount = abs(float(row.amount or 0))
        
        by_category[cat] += amount
        if cat not in ops_by_category:
            ops_by_category[cat] = {"total": 0.0, "items": []}
        
        ops_by_category[cat]["total"] += amount
        ops_by_category[cat]["items"].append({
            "amount": round(amount, 2),
            "date": row.date.isoformat() if row.date else None,
            "notes": row.notes or t,
        })

    return {
        "by_category": {k: round(v, 2) for k, v in by_category.items() if v != 0},
        "details": ops_by_category,
        "total": round(sum(by_category.values()), 2)
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

    categories.sort(key=lambda x: x["amount"], reverse=True)

    return {
        "since": since,
        "to": to,
        "total": total,
        "categories": categories
    }
