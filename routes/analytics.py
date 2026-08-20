from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from datetime import datetime, timedelta, timezone
import logging
from collections import defaultdict

from db.database import get_db, User, Order, OrderPosting, OrderProduct, OzonAccrual, Cost
from utils.auth import get_current_user
from utils.common import to_msk, parse_ozon_datetime
from services.costs import get_batch_product_costs

router = APIRouter(prefix="/analytics", tags=["analytics"])
logger = logging.getLogger(__name__)

# Полный официальный справочник услуг Ozon (type_id → название).
# ВНИМАНИЕ: ключи — int, т.к. OzonAccrual.type_id объявлен как Column(Integer).
# Этот словарь используется ТОЛЬКО для отображения названий в отчётах/выпадающих списках.
# Логика категоризации (комиссия/логистика/реклама и т.д.) находится ниже в
# функции sales_report_universal и оперирует числовыми ID — изменение названий её не затрагивает.
OZON_SERVICE_TYPES = {
    1000: "Комиссия за продажу",
    1: "Эквайринг",
    2: "Обратная магистраль",
    3: "Продвижение бренда",
    4: "Подключение продвижения бренда",
    5: "Брендовая полка",
    6: "Обработка отменённых и невостребованных товаров",
    7: "Благотворительное пожертвование",
    8: "Начисления по претензиям",
    9: "Обработка возвратов",
    10: "Компенсация",
    11: "Инвентаризация взаиморасчетов",
    12: "Кросс-докинг",
    13: "Организация выезда курьера",
    14: "Обработка операционных ошибок продавца",
    15: "Утилизация",
    16: "Обработка отправления Drop-off",
    17: "Обработка отправления Drop-off партнёрами",
    18: "Досрочная выплата",
    19: "Внешнее продвижение",
    20: "Гибкий график выплат",
    21: "Сборка заказа",
    22: "Рассрочка",
    23: "Реклама в сети Интернет на Сайте",
    24: "Перенос карточек товаров",
    25: "Товарная компенсация",
    26: "Рассрочка для покупателей из Казахстана",
    27: "Бейдж Оригинал",
    28: "Последняя миля",
    29: "Доставка до места выдачи",
    30: "Выдача товара",
    31: "Лидогенерация для автодилеров",
    32: "Логистика",
    33: "Рекламные услуги",
    34: "Обязательная маркировка товаров",
    35: "Модерация товаров",
    36: "Привлечение предварительных заказов",
    37: "Ozon Data",
    38: "Обеспечение материалами для упаковки товара",
    39: "Упаковка товара партнёрами",
    40: "Обработка частичного невыкупа",
    41: "Оплата за клик",
    42: "Обработка отправления Pick-up",
    43: "Организация выезда курьера",
    44: "Доставка курьером Pick-up",
    45: "Обработка возвратов, отмен и невыкупов партнёрами",
    46: "Размещение товаров на складах Ozon",
    47: "Баллы за отзывы",
    48: "Бонусы продавца",
    49: "Услуга продвижения Premium",
    50: "Бонусы продавца - рассылка",
    51: "Подписка Premium Pro (процент)",
    52: "Подписка Premium",
    53: "Подготовка товаров к возврату",
    54: "Продвижение товара",
    55: "Рассылка пуш-уведомлений",
    56: "Обработка и логистика кванта",
    57: "Корректировка стоимости услуг",
    58: "Перемещение товаров между складами Ozon",
    59: "Обратная логистика",
    60: "Долгосрочное размещение возврата FBS",
    61: "Закрепление отзыва",
    62: "Перечисление за доставку от покупателя",
    63: "Агентское вознаграждение Ozon Агрегатор realFBS",
    64: "Доставка Партнёром Ozon",
    65: "Лёгкий возврат",
    66: "Агентское вознаграждение Ozon",
    67: "Услуги международной доставки",
    68: "Сервисный сбор за интеграцию с логистической платформой",
    69: "Вознаграждение за продажу",
    70: "Приобретение отзывов на платформе",
    71: "Вывоз товара со склада силами Ozon",
    72: "Взаимозачет требований между Договорами",
    73: "Магистраль",
    74: "Звёздные товары",
    75: "Трафареты",
    76: "Страхование товара от массовых повреждений",
    77: "Обработка товара",
    78: "Краткосрочное размещение возврата FBS",
    79: "Временное размещение товара партнерами",
    80: "Генерация видеообложки",
    81: "Бонус за достижение цели продаж",
    82: "Дополнительная обработка ОВХ",
    83: "Обеспечительные платежи",
    84: "Дополнительная упаковка на складе Ozon",
    85: "Пломбирование товара",
    86: "Дополнительная упаковка товара на ПВЗ в СНГ",
    87: "Реклама в социальных сетях",
    88: "Самовывоз",
    89: "Запрещённый контент",
    90: "Запрещённый товар",
    91: "Товар с нарушением интеллектуальных прав",
    92: "Жалобы покупателей",
    93: "Превышение индекса ошибок",
    94: "Отгрузка в нерекомендованный слот",
    95: "Подписка Управление отзывами",
    96: "Ускоренный сбор отзывов",
    97: "Обработка грузоместа",
    98: "Доставка до места выдачи силами Ozon",
    99: "Международная логистика",
    100: "Транспортно-экспедиционная услуга по организации международной перевозки",
    101: "Обработка нестандартного товара",
    102: "Временное размещение отправления в СЦ/ПВЗ/партнёрами",
    103: "Утилизация отправления",
    104: "Страховое возмещение",
    105: "Страхование отправления",
    106: "B2C Обработка отправления Drop-off",
    107: "B2C Обработка отправления Drop-off партнёрами",
    108: "Обеспечение материалами для упаковки отправления",
    109: "Упаковка отправления партнёрами",
    110: "B2C Доставка до места выдачи партнёрами",
    111: "B2C Доставка до места выдачи силами Ozon",
    112: "B2C Выдача товара партнёрами",
    113: "B2C Обработка возвратов, отмен и невыкупов партнёрами",
    114: "B2C Логистика",
    115: "B2C Обратная логистика",
    116: "Сбор первых отзывов",
    117: "Увеличение лимита на создание карточек товаров",
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
    Оптимизировано: используем UNION для эффективного выполнения в БД.
    """
    search_since = since_utc.replace(tzinfo=None)
    search_to = to_utc.replace(tzinfo=None)

    postings_map = {}

    # 1. Собираем данные из нормализованной таблицы (Приоритетный источник)
    # Используем UNION для эффективного использования индексов на стороне БД
    q1 = db.query(OrderPosting.posting_number, OrderPosting.created_at, OrderPosting.status, OrderPosting.in_process_at).filter(
        OrderPosting.user_id == user_id,
        OrderPosting.created_at.between(search_since, search_to)
    )
    q2 = db.query(OrderPosting.posting_number, OrderPosting.created_at, OrderPosting.status, OrderPosting.in_process_at).filter(
        OrderPosting.user_id == user_id,
        OrderPosting.in_process_at.between(search_since, search_to)
    )
    
    # Объединяем на стороне БД
    unified_query = q1.union(q2)

    for pn, cr, st, in_proc in unified_query.all():
        if not pn: continue
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
    """Возвращает индивидуальное название услуги Ozon для детального отчета."""
    if tid is None:
        return "Возврат товара"
    return OZON_SERVICE_TYPES.get(tid, f"Прочая услуга (ID {tid})")


# Type_id услуг Озона, которые ДОСТОВЕРНО указывают на факт
# продажи/отгрузки товара и могут служить сигналом «смещения»
# (когда строки выручки за этот день ещё нет в API, но товар уже
# продан/отгружен по банковской отчётности).
#
# Это комиссия (1000) и логистика/доставка (12/29/32/39/59/305).
# Эквайринг (1), хранение (74), утилизация (98) и прочие мелкие
# удержания НЕ являются признаком продажи.
#
# ПРИМЕЧАНИЕ: проверено эмпирически — на некоторых днях (напр. 26.06)
# может быть единичное расхождение (1-2 единицы), связанное с
# задержкой синхронизации данных в самом API Озона. Это ожидаемое
# поведение, так как данные /v1/finance/accrual/by-day формируются
# с задержкой и могут быть ещё не «закрыты» для некоторых постингов.
_SALE_INDICATING_TYPE_IDS = frozenset({
    1000,                          # Комиссия за продажу
    12, 29, 32, 39, 59, 305        # Логистика / доставка / магистраль
})


def _calculate_cost_price_from_orders(
    db: Session,
    user_id: int,
    since_utc: datetime,
    to_utc: datetime,
    tz_offset_hours: int = 3,
    include_cancelled: bool = False,
    postings_map: dict | None = None
) -> tuple[float, list[dict]]:
    """
    Оперативный расчет себестоимости на основе ЗАКАЗОВ (OrderProduct).
    """
    # 1. Получаем список всех постингов за этот период (если не переданы готовые)
    if postings_map is None:
        postings_map = _get_unified_postings(db, user_id, since_utc, to_utc, include_cancelled)
    
    if not postings_map:
        return 0.0, []

    local_tz = timezone(timedelta(hours=tz_offset_hours))
    date_since_l = since_utc.astimezone(local_tz).date()
    date_to_l = to_utc.astimezone(local_tz).date()

    # Фильтруем постинги, которые попадают в выбранные даты по местному времени (МСК)
    final_pns = []
    for pn, data in postings_map.items():
        # Приоритет: дата обработки (отгрузки). Если нет - дата создания.
        best_date = data.get("in_process_at") or data["created_at"]
        dt_local = to_msk(best_date, tz_offset_hours)
        if dt_local and date_since_l <= dt_local.date() <= date_to_l:
            final_pns.append(pn)

    if not final_pns:
        return 0.0, []

    # 2. Агрегируем количество товаров из этих заказов
    product_stats = db.query(
        OrderProduct.sku,
        OrderProduct.name,
        func.sum(OrderProduct.quantity).label("qty")
    ).filter(
        OrderProduct.user_id == user_id,
        OrderProduct.posting_number.in_(final_pns)
    ).group_by(OrderProduct.sku, OrderProduct.name).all()

    all_skus = [int(r[0]) for r in product_stats]
    cost_cache = get_batch_product_costs(db, user_id, all_skus, to_utc)

    total_cost_price = 0.0
    items = []

    for r_sku, r_name, r_qty in product_stats:
        s_int = int(r_sku)
        qty = int(r_qty or 0)
        cp = cost_cache.get(s_int, 0.0)
        
        if cp > 0 and qty > 0:
            amount = cp * qty
            total_cost_price += amount
            items.append({
                "sku": s_int,
                "name": r_name,
                "quantity": qty,
                "cost_price": round(cp, 2),
                "amount": round(amount, 2),
            })

    return round(total_cost_price, 2), items

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

    # 2. Агрегируем продажи и список товаров из OrderProduct (Наиболее точный источник по данным верификации)
    # Это гарантирует 100% совпадение количества товаров в графике и в итоговой таблице.
    product_stats = db.query(
        OrderProduct.sku,
        OrderProduct.name,
        OrderProduct.offer_id,
        OrderProduct.image_url,
        func.sum(OrderProduct.quantity).label("qty"),
        func.sum(OrderProduct.price * OrderProduct.quantity).label("rev")
    ).filter(
        OrderProduct.user_id == current_user.id,
        OrderProduct.posting_number.in_(final_postings)
    ).group_by(OrderProduct.sku, OrderProduct.name, OrderProduct.offer_id, OrderProduct.image_url).all()

    items_map = {}
    total_sales_revenue = 0.0
    all_skus = []

    for r_sku, r_name, r_oid, r_img, r_qty, r_rev in product_stats:
        s = int(r_sku)
        items_map[s] = {
            "sku": s,
            "name": r_name,
            "offer_id": r_oid,
            "image_url": r_img,
            "quantity": int(r_qty or 0),
            "amount_raw": float(r_rev or 0)
        }
        total_sales_revenue += float(r_rev or 0)
        all_skus.append(s)

    # 3. Агрегируем расходы и возвраты из OzonAccrual (Финансовый первоисточник для услуг)
    accrual_data_raw = db.query(
        OzonAccrual.sku,
        OzonAccrual.amount,
        OzonAccrual.type_id,
        OzonAccrual.operation_type,
        OzonAccrual.quantity
    ).filter(
        OzonAccrual.user_id == current_user.id,
        OzonAccrual.date >= since_utc.replace(tzinfo=None),
        OzonAccrual.date <= to_utc.replace(tzinfo=None)
    ).all()

    total_returns_amount = 0.0
    total_commission = 0.0
    total_logistics = 0.0
    total_acquiring = 0.0
    total_advertising = 0.0
    total_storage = 0.0
    total_other_expenses = 0.0
    total_returns_cancels_fee = 0.0 
    total_manual_expenses = 0.0 

    accruals_by_type = {}

    for r_sku, r_amt, r_tid, r_op_type, r_qty in accrual_data_raw:
        val = float(r_amt or 0)
        
        if r_tid is None:
            # Только возвраты товара (отрицательные суммы без type_id)
            if val < 0:
                total_returns_amount += abs(val)
        else:
            # Накапливаем услуги
            accruals_by_type[r_tid] = accruals_by_type.get(r_tid, 0.0) + val

    # Распределяем накопленные услуги по категориям для итоговой сводки
    for tid, amt_sum in accruals_by_type.items():
        val = -float(amt_sum or 0) 
        
        if tid == 1000: 
            total_commission += val
        elif tid == 1: 
            total_acquiring += val
        elif tid in [2, 12, 21, 28, 29, 30, 32, 39, 58, 59, 73, 84, 98, 99, 101, 114, 115, 305]: 
            total_logistics += val
        elif tid in [3, 5, 33, 41, 49, 54, 74, 75, 120]: 
            total_advertising += val
        elif tid in [46, 60]: 
            total_storage += val
        elif tid in [6, 9, 45]: 
            total_returns_cancels_fee += val
        else: 
            total_other_expenses += val

    # 4. Оперативный расчет себестоимости на основе ЗАКАЗОВ
    total_cost_price, _cost_items = _calculate_cost_price_from_orders(
        db,
        current_user.id,
        since_utc,
        to_utc,
        tz_offset_hours=tz_offset_hours,
        include_cancelled=False, # Не считаем себестоимость отмененных
        postings_map=postings_map  # ОПТИМИЗАЦИЯ: повторно используем уже загруженные постинги
    )

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

    # ВАЖНО: total_expenses включает ВСЕ расходы, включая возвраты товара,
    # чтобы итог совпадал с expenses_breakdown (где «Возвраты и отмены»
    # — это отдельная категория расходов, как в отчёте Озон Банка).
    total_expenses = (
        total_commission + total_logistics + total_advertising + 
        total_storage + total_acquiring + total_other_expenses + 
        total_returns_cancels_fee + total_cost_price + total_manual_expenses +
        total_returns_amount  # возвраты товара (type_id=None, amount<0)
    )
    # Прибыль: выручка минус все расходы (возвраты уже внутри total_expenses)
    profit = total_sales_revenue - total_expenses

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

    # Получаем все расходные транзакции: услуги (type_id IS NOT NULL)
    # и возвраты товара (type_id IS NULL, amount < 0).
    accruals = db.query(OzonAccrual).filter(
        OzonAccrual.user_id == current_user.id,
        OzonAccrual.date >= since_utc,
        OzonAccrual.date <= to_utc,
        or_(
            OzonAccrual.type_id.is_not(None),             # услуги
            (OzonAccrual.type_id.is_(None)) & (OzonAccrual.amount < 0)  # возвраты товара
        )
    ).all()

    # Накапливаем суммы по категориям С УЧЁТОМ ЗНАКА (нетто).
    # Это нужно, чтобы корректировки/сторно (положительные суммы среди
    # расходов) правильно взаимозачитывались — как на главном экране
    # и как в отчёте Озон Банка. Иначе +31.2 и −31.2 (отмена продажи)
    # сложатся в 62.4 вместо правильных 0.
    by_category_signed: dict[str, float] = {}
    ops_by_category: dict[str, dict] = {}

    for acc in accruals:
        tid = acc.type_id
        signed_amount = float(acc.amount or 0)

        # Возвраты товара (type_id=None, amount<0) и обработка отмен (type_id=45)
        # объединяем в категорию «Возвраты и отмены» — как в отчёте Озон Банка.
        if tid is None or tid == 45:
            cat_name = "Возвраты и отмены"
        else:
            cat_name = get_expense_category(tid)

        by_category_signed[cat_name] = by_category_signed.get(cat_name, 0.0) + signed_amount

        if cat_name not in ops_by_category:
            ops_by_category[cat_name] = {"total": 0.0, "items": []}

        # Для отображения берём модуль отдельной транзакции
        display_amount = abs(signed_amount)
        ops_by_category[cat_name]["total"] += display_amount

        note = f"Заказ {acc.unit_number}" if acc.unit_number else acc.accrued_category
        if tid and tid in OZON_SERVICE_TYPES:
            note += f" ({OZON_SERVICE_TYPES[tid]})"

        ops_by_category[cat_name]["items"].append({
            "amount": round(display_amount, 2),
            "date": acc.date.isoformat() if acc.date else None,
            "notes": note,
            "unit_number": acc.unit_number
        })

    # Итоговые суммы по категориям — модуль нетто-суммы
    by_category = {k: abs(v) for k, v in by_category_signed.items()}

    # Синхронизируем итоги деталей с нетто-суммами категорий
    for cat_name, net_total in by_category.items():
        if cat_name in ops_by_category:
            ops_by_category[cat_name]["total"] = net_total

    cost_rows = db.query(Cost).filter(
        Cost.user_id == current_user.id,
        Cost.date >= since_utc,
        Cost.date <= to_utc
    ).all()

    for row in cost_rows:
        t = (row.type or "").lower()
        # Если есть данные из API по основным категориям, ручные записи этих типов игнорируем
        if t in ["acquiring", "commission", "logistics", "advertising", "storage"] and len(accruals) > 0:
            continue
            
        if t in ("advertising", "adv"): cat = "Реклама (ручная)"
        elif t == "storage": cat = "Хранение (ручное)"
        elif t == "logistics": cat = "Логистика (ручная)"
        elif t == "acquiring": cat = "Эквайринг (ручной)"
        elif t == "commission": cat = "Комиссия (ручная)"
        else: cat = "Прочие расходы (ручные)"
        amount = abs(float(row.amount or 0))
        
        by_category[cat] = by_category.get(cat, 0.0) + amount
        if cat not in ops_by_category:
            ops_by_category[cat] = {"total": 0.0, "items": []}
        
        ops_by_category[cat]["total"] += amount
        ops_by_category[cat]["items"].append({
            "amount": round(amount, 2),
            "date": row.date.isoformat() if row.date else None,
            "notes": row.notes or t,
        })

    # --- ОПЕРАТИВНЫЙ РАСЧЕТ СЕБЕСТОИМОСТИ ТОВАРОВ ---
    # Получаем постинги для расчета себестоимости (чтобы не дублировать логику)
    # Используем расширенное окно поиска для корректного маппинга дат
    search_since = since_utc - timedelta(hours=24)
    search_to = to_utc + timedelta(hours=24)
    p_map = _get_unified_postings(db, current_user.id, search_since, search_to, include_cancelled=False)

    total_cp, cp_items = _calculate_cost_price_from_orders(
        db,
        current_user.id,
        since_utc,
        to_utc,
        tz_offset_hours=tz_offset_hours,
        include_cancelled=False,
        postings_map=p_map
    )

    if total_cp > 0:
        cat_cp = "Себестоимость товаров"
        by_category[cat_cp] = by_category.get(cat_cp, 0.0) + total_cp
        if cat_cp not in ops_by_category:
            ops_by_category[cat_cp] = {"total": 0.0, "items": []}
        ops_by_category[cat_cp]["total"] += total_cp
        ops_by_category[cat_cp]["items"].extend([
            {
                "amount": it["amount"],
                "date": None,
                "notes": f"SKU {it['sku']} (x{it['quantity']} шт.) — закупка {it['cost_price']} ₽",
                "unit_number": str(it["sku"]),
                "sku": it["sku"],
            }
            for it in cp_items
        ])

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
