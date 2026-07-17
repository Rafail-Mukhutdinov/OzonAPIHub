"""
Тестовый скрипт для проверки расчёта расходов через /v1/finance/accrual/by-day.

Поддерживает запрос как за один день, так и за произвольный период
(указываются дата начала и дата конца — период перебирается по дням,
т.к. API Ozon отдаёт данные только за один день за запрос).

Запуск:
    # Один день (обратная совместимость со старой версией)
    python scripts/test_accruals_by_day.py 2026-06-15
    python scripts/test_accruals_by_day.py 2026-06-15 --user 1
    python scripts/test_accruals_by_day.py 2026-06-15 --raw

    # Период (через позиционные аргументы)
    python scripts/test_accruals_by_day.py 2026-06-01 2026-06-30

    # Период (через флаги)
    python scripts/test_accruals_by_day.py --start 2026-06-01 --end 2026-06-30

    # Период + фильтр по пользователю и сырой вывод
    python scripts/test_accruals_by_day.py 2026-06-01 2026-06-30 --user 1 --raw

Без --raw выводит агрегированный отчёт по расходам за весь период.
С --raw выводит каждую транзакцию отдельно (по дням).
"""

import sys
import os
import asyncio
import argparse
from datetime import datetime, timedelta
from collections import defaultdict

# Добавляем корень проекта в sys.path, чтобы импорты работали из scripts/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Загружаем .env из корня проекта
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from db.database import SessionLocal, User, OzonCredential
from utils.encryption import decrypt_credential
from services.ozon import ozon_accruals_by_day_async, init_http_client, close_http_client
from services.costs import get_product_cost


DATE_FORMAT = "%Y-%m-%d"


def parse_date(s: str) -> datetime:
    """Парсит дату в формате YYYY-MM-DD. Бросает argparse.ArgumentTypeError при ошибке."""
    try:
        return datetime.strptime(s, DATE_FORMAT)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Неверный формат даты: '{s}'. Ожидается YYYY-MM-DD")


def daterange(start: datetime, end: datetime):
    """Итератор дней от start до end включительно (шаг = 1 день)."""
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


async def fetch_all_accruals(client_id: str, api_key: str, date_str: str):
    """Получает все accruals за день с пагинацией через last_id."""
    all_accruals = []
    last_id = ""
    page = 0

    while True:
        page += 1
        response = await ozon_accruals_by_day_async(client_id, api_key, date_str, last_id)
        accruals = response.get("accruals") or []

        if not accruals:
            break

        all_accruals.extend(accruals)
        print(f"  Страница {page}: получено {len(accruals)} записей (всего {len(all_accruals)})")

        last_id = response.get("last_id")
        if not last_id:
            break

    return all_accruals


def parse_amount(val) -> float:
    """Безопасно парсит сумму из ответа Ozon."""
    if val is None:
        return 0.0
    if isinstance(val, dict):
        return float(val.get("amount") or 0)
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


# Справочник типов операций Ozon (Синхронизировано с официальным списком)
OZON_TYPE_NAMES = {
    "commission": "Комиссия за продажу",
    "1": "Эквайринг",
    "2": "Обратная магистраль",
    "3": "Продвижение бренда",
    "4": "Подключение продвижения бренда",
    "5": "Брендовая полка",
    "6": "Обработка отменённых и невостребованных товаров",
    "7": "Благотворительное пожертвование",
    "8": "Начисления по претензиям",
    "9": "Обработка возвратов",
    "10": "Компенсация",
    "11": "Инвентаризация взаиморасчетов",
    "12": "Кросс-докинг",
    "13": "Организация выезда курьера",
    "14": "Обработка операционных ошибок продавца",
    "15": "Утилизация",
    "16": "Обработка отправления Drop-off",
    "17": "Обработка отправления Drop-off партнёрами",
    "18": "Досрочная выплата",
    "19": "Внешнее продвижение",
    "20": "Гибкий график выплат",
    "21": "Сборка заказа",
    "22": "Рассрочка",
    "23": "Реклама в сети Интернет на Сайте",
    "24": "Перенос карточек товаров",
    "25": "Товарная компенсация",
    "26": "Рассрочка для покупателей из Казахстана",
    "27": "Бейдж Оригинал",
    "28": "Последняя миля",
    "29": "Доставка до места выдачи",
    "30": "Выдача товара",
    "31": "Лидогенерация для автодилеров",
    "32": "Логистика",
    "33": "Рекламные услуги",
    "34": "Обязательная маркировка товаров",
    "35": "Модерация товаров",
    "36": "Привлечение предварительных заказов",
    "37": "Ozon Data",
    "38": "Обеспечение материалами для упаковки товара",
    "39": "Упаковка товара партнёрами",
    "40": "Обработка частичного невыкупа",
    "41": "Оплата за клик",
    "42": "Обработка отправления Pick-up",
    "43": "Организация выезда курьера",
    "44": "Доставка курьером Pick-up",
    "45": "Обработка возвратов, отмен и невыкупов партнёрами",
    "46": "Размещение товаров на складах Ozon",
    "47": "Баллы за отзывы",
    "48": "Бонусы продавца",
    "49": "Услуга продвижения Premium",
    "50": "Бонусы продавца - рассылка",
    "51": "Подписка Premium Pro (процент)",
    "52": "Подписка Premium",
    "53": "Подготовка товаров к возврату",
    "54": "Продвижение товара",
    "55": "Рассылка пуш-уведомлений",
    "56": "Обработка и логистика кванта",
    "57": "Корректировка стоимости услуг",
    "58": "Перемещение товаров между складами Ozon",
    "59": "Обратная логистика",
    "60": "Долгосрочное размещение возврата FBS",
    "61": "Закрепление отзыва",
    "62": "Перечисление за доставку от покупателя",
    "63": "Агентское вознаграждение Ozon Агрегатор realFBS",
    "64": "Доставка Партнёром Ozon",
    "65": "Лёгкий возврат",
    "66": "Агентское вознаграждение Ozon",
    "67": "Услуги международной доставки",
    "68": "Сервисный сбор за интеграцию с логистической платформой",
    "69": "Вознаграждение за продажу",
    "70": "Приобретение отзывов на платформе",
    "71": "Вывоз товара со склада силами Ozon",
    "72": "Взаимозачет требований между Договорами",
    "73": "Магистраль",
    "74": "Звёздные товары",
    "75": "Трафареты",
    "76": "Страхование товара от массовых повреждений",
    "77": "Обработка товара",
    "78": "Краткосрочное размещение возврата FBS",
    "79": "Временное размещение товара партнерами",
    "80": "Генерация видеообложки",
    "81": "Бонус за достижение цели продаж",
    "82": "Дополнительная обработка ОВХ",
    "83": "Обеспечительные платежи",
    "84": "Дополнительная упаковка на складе Ozon",
    "85": "Пломбирование товара",
    "86": "Дополнительная упаковка товара на ПВЗ в СНГ",
    "87": "Реклама в социальных сетях",
    "88": "Самовывоз",
    "89": "Запрещённый контент",
    "90": "Запрещённый товар",
    "91": "Товар с нарушением интеллектуальных прав",
    "92": "Жалобы покупателей",
    "93": "Превышение индекса ошибок",
    "94": "Отгрузка в нерекомендованный слот",
    "95": "Подписка Управление отзывами",
    "96": "Ускоренный сбор отзывов",
    "97": "Обработка грузоместа",
    "98": "Доставка до места выдачи силами Ozon",
    "99": "Международная логистика",
    "100": "Транспортно-экспедиционная услуга по организации международной перевозки",
    "101": "Обработка нестандартного товара",
    "102": "Временное размещение отправления в СЦ/ПВЗ/партнёрами",
    "103": "Утилизация отправления",
    "104": "Страховое возмещение",
    "105": "Страхование отправления",
    "106": "B2C Обработка отправления Drop-off",
    "107": "B2C Обработка отправления Drop-off партнёрами",
    "108": "Обеспечение материалами для упаковки отправления",
    "109": "Упаковка отправления партнёрами",
    "110": "B2C Доставка до места выдачи партнёрами",
    "111": "B2C Доставка до места выдачи силами Ozon",
    "112": "B2C Выдача товара партнёрами",
    "113": "B2C Обработка возвратов, отмен и невыкупов партнёрами",
    "114": "B2C Логистика",
    "115": "B2C Обратная логистика",
    "116": "Сбор первых отзывов",
    "117": "Увеличение лимита на создание карточек товаров",
    "305": "Доставка сторонними службами",
}

# Маппинг type_id → категория отчёта Ozon "Банк" / "Экономика".
OZON_BANK_CATEGORY_MAP = {
    "commission": "Комиссия МП",
    "1": "Эквайринг",
    "2": "Логистика",               # Обратная магистраль
    "3": "Реклама Ozon",            # Продвижение бренда
    "5": "Реклама Ozon",            # Брендовая полка
    "6": "Возвраты и отмены",       # Обработка отменённых
    "9": "Возвраты и отмены",       # Обработка возвратов
    "12": "Логистика",              # Кросс-докинг
    "15": "Прочие расходы Ozon",    # Утилизация
    "21": "Логистика",              # Сборка заказа (Fulfillment)
    "28": "Логистика",              # Последняя миля
    "29": "Логистика",              # Доставка до места выдачи
    "30": "Логистика",              # Выдача товара
    "32": "Логистика",              # Логистика
    "33": "Реклама Ozon",           # Рекламные услуги
    "39": "Логистика",              # Упаковка товара партнёрами
    "41": "Реклама Ozon",           # Оплата за клик
    "45": "Возвраты и отмены",      # Обработка возвратов партнёрами
    "46": "Хранение",               # Размещение товаров на складах
    "48": "Прочие доходы",          # Бонусы продавца
    "49": "Реклама Ozon",           # Услуга продвижения Premium
    "52": "Прочие расходы Ozon",    # Подписка Premium
    "54": "Реклама Ozon",           # Продвижение товара
    "58": "Логистика",              # Перемещение между складами
    "59": "Логистика",              # Обратная логистика
    "60": "Хранение",               # Хранение возвратов FBS
    "73": "Логистика",              # Магистраль
    "74": "Реклама Ozon",           # Звёздные товары
    "75": "Реклама Ozon",           # Трафареты
    "84": "Логистика",              # Доп. упаковка Ozon
    "98": "Логистика",              # Доставка силами Ozon
    "99": "Логистика",              # Международная логистика
    "101": "Логистика",             # Нестандартный товар
    "103": "Прочие расходы Ozon",   # Утилизация отправления
    "105": "Прочие расходы Ozon",   # Страхование
    "114": "Логистика",             # B2C Логистика
    "115": "Логистика",             # B2C Обратная логистика
    "120": "Реклама Ozon",          # Продвижение (Акция)
    "305": "Логистика",             # Доставка сторонними службами
}


def get_type_name(tid) -> str:
    """Возвращает человекочитаемое название типа операции."""
    tid_str = str(tid).replace("type_id:", "")
    return OZON_TYPE_NAMES.get(tid_str, f"Операция {tid_str}")


def new_accumulator():
    """Создаёт пустой аккумулятор для агрегации данных по периоду."""
    return {
        "total_revenue": 0.0,
        "total_expense": 0.0,
        "total_cost_price": 0.0,
        "total_returns_amount": 0.0,
        "by_category": defaultdict(lambda: {"revenue": 0.0, "expense": 0.0, "count": 0}),
        "by_type_id": defaultdict(float),
        "by_sku": defaultdict(float),
        "posting_breakdown": {
            "revenue": 0.0,
            "commission": 0.0,
            "delivery_services": 0.0,
            "returns": 0.0,
        },
        "total_transactions": 0,
        "by_day": defaultdict(lambda: {"revenue": 0.0, "expense": 0.0, "count": 0, "cost_price": 0.0}),
    }


def aggregate_day(accruals: list, db: SessionLocal, user_id: int, target_date: datetime, acc: dict):
    """
    Разбирает accruals одного дня и добавляет суммы в общий аккумулятор `acc`.
    Важно: себестоимость считается на дату транзакции (target_date).
    """
    acc["total_transactions"] += len(accruals)
    day_key = target_date.strftime(DATE_FORMAT)

    by_category = acc["by_category"]
    by_type_id = acc["by_type_id"]
    by_sku = acc["by_sku"]
    posting_breakdown = acc["posting_breakdown"]
    by_day = acc["by_day"]

    for a in accruals:
        category = a.get("accrued_category") or "UNKNOWN"
        amount_data = a.get("total_amount") or {}
        total_amount = parse_amount(amount_data)

        by_category[category]["count"] += 1
        by_day[day_key]["count"] += 1

        if category == "POSTING" and a.get("posting"):
            # Распаковка POSTING
            p_data = a["posting"]
            for prod in p_data.get("products", []):
                sku = prod.get("sku")
                qty = int(prod.get("quantity") or 1)
                comm = prod.get("commission") or {}

                # 1. Выручка и Возвраты товаров
                sale_amt = parse_amount(comm.get("sale_amount"))
                if sale_amt > 0:
                    item_rev = sale_amt * qty
                    acc["total_revenue"] += item_rev
                    by_category[category]["revenue"] += item_rev
                    posting_breakdown["revenue"] += item_rev
                    by_day[day_key]["revenue"] += item_rev
                    # Считаем себестоимость при продаже (используем дату транзакции!)
                    if db and user_id and sku:
                        cp = get_product_cost(db, user_id, int(sku), target_date)
                        acc["total_cost_price"] += cp * qty
                        by_day[day_key]["cost_price"] += cp * qty
                elif sale_amt < 0:
                    abs_ret = abs(sale_amt) * qty
                    acc["total_returns_amount"] += abs_ret
                    posting_breakdown["returns"] += abs_ret
                    # ВАЖНО: Вычитаем себестоимость при возврате (используем дату транзакции!)
                    if db and user_id and sku:
                        cp = get_product_cost(db, user_id, int(sku), target_date)
                        acc["total_cost_price"] -= cp * qty
                        by_day[day_key]["cost_price"] -= cp * qty

                # 2. Комиссия (С учетом знака!)
                comm_amt = parse_amount(comm.get("commission"))
                if comm_amt != 0:
                    expense_val = -comm_amt * qty
                    acc["total_expense"] += expense_val
                    by_category[category]["expense"] += expense_val
                    by_type_id["commission"] += expense_val
                    by_sku[f"sku:{sku}"] += expense_val
                    posting_breakdown["commission"] += expense_val
                    by_day[day_key]["expense"] += expense_val

                # 3. Доставка и сервисы (С учетом знака!)
                deliv = prod.get("delivery") or {}
                for srv in deliv.get("services", []):
                    srv_amt = parse_amount(srv.get("accrued"))
                    if srv_amt != 0:
                        expense_val = -srv_amt * qty
                        acc["total_expense"] += expense_val
                        by_category[category]["expense"] += expense_val
                        type_id = srv.get("type_id", "unknown")
                        by_type_id[f"type_id:{type_id}"] += expense_val
                        by_sku[f"sku:{sku}"] += expense_val
                        posting_breakdown["delivery_services"] += expense_val
                        by_day[day_key]["expense"] += expense_val
        else:
            # ITEM и NON_ITEM
            amount = total_amount
            type_id = None
            sku = None
            if category == "ITEM":
                item_fees = a.get("item_fees") or {}
                if item_fees.get("fees"):
                    fee_item = item_fees["fees"][0]
                    sku = fee_item.get("sku")
                    if fee_item.get("fees"):
                        type_id = fee_item["fees"][0].get("type_id")
            elif category == "NON_ITEM":
                ni_fee = a.get("non_item_fee") or {}
                type_id = ni_fee.get("type_id")

            if type_id is not None:
                expense_val = -amount
                acc["total_expense"] += expense_val
                by_category[category]["expense"] += expense_val
                by_type_id[f"type_id:{type_id}"] += expense_val
                by_day[day_key]["expense"] += expense_val
            else:
                if amount > 0:
                    acc["total_revenue"] += amount
                    by_category[category]["revenue"] += amount
                    by_day[day_key]["revenue"] += amount
                else:
                    acc["total_expense"] += abs(amount)
                    by_category[category]["expense"] += abs(amount)
                    by_day[day_key]["expense"] += abs(amount)


def print_raw_day(date_str: str, accruals: list):
    """Сырой вывод транзакций одного дня."""
    print("\n" + "=" * 80)
    print(f"RAW ВЫВОД — {date_str}")
    print("=" * 80)
    for i, acc in enumerate(accruals):
        print(f"\n--- #{i} ---")
        print(f"  accrual_id:     {acc.get('accrual_id')}")
        print(f"  unit_number:    {acc.get('unit_number')}")
        print(f"  category:       {acc.get('accrued_category')}")
        print(f"  total_amount:   {acc.get('total_amount')}")
        if acc.get("posting"):
            print(f"  posting:        {acc.get('posting')}")
        if acc.get("item_fees"):
            print(f"  item_fees:      {acc.get('item_fees')}")
        if acc.get("non_item_fee"):
            print(f"  non_item_fee:   {acc.get('non_item_fee')}")


def print_report(acc: dict, start_date: datetime, end_date: datetime):
    """Выводит агрегированный отчёт по всему периоду."""
    total_revenue = acc["total_revenue"]
    total_expense = acc["total_expense"]
    total_cost_price = acc["total_cost_price"]
    total_returns_amount = acc["total_returns_amount"]
    by_category = acc["by_category"]
    by_type_id = acc["by_type_id"]
    by_sku = acc["by_sku"]
    posting_breakdown = acc["posting_breakdown"]
    by_day = acc["by_day"]

    days_count = (end_date - start_date).days + 1

    print("\n" + "=" * 80)
    print("ОТЧЁТ ПО РАСХОДАМ (accrual/by-day)")
    print("=" * 80)
    print(f"Период: {start_date.strftime(DATE_FORMAT)} .. {end_date.strftime(DATE_FORMAT)} ({days_count} дн.)")

    print(f"\nВсего транзакций: {acc['total_transactions']}")
    print(f"Общий доход:   {total_revenue:>15.2f} руб")
    print(f"Общий расход:  {total_expense:>15.2f} руб")
    print(f"Себестоимость: {total_cost_price:>15.2f} руб")
    print(f"Возвраты:      {total_returns_amount:>15.2f} руб")
    print(f"Чистая выплата: {total_revenue - total_returns_amount - total_expense:>14.2f} руб")
    print(f"Прибыль (Net):  {total_revenue - total_returns_amount - total_expense - total_cost_price:>14.2f} руб")

    # Разбивка по дням (новое для периода)
    if days_count > 1:
        print("\n--- По дням ---")
        print(f"{'Дата':<12} {'Доход':>15} {'Расход':>15} {'Себест.':>15} {'Транз.':>8}")
        print("-" * 69)
        for day_key in sorted(by_day.keys()):
            d = by_day[day_key]
            print(f"{day_key:<12} {d['revenue']:>15.2f} {d['expense']:>15.2f} {d['cost_price']:>15.2f} {d['count']:>8}")

    print("\n--- По категориям ---")
    print(f"{'Категория':<15} {'Доход':>15} {'Расход':>15} {'Кол-во':>8}")
    print("-" * 55)
    for cat in sorted(by_category.keys()):
        d = by_category[cat]
        print(f"{cat:<15} {d['revenue']:>15.2f} {d['expense']:>15.2f} {d['count']:>8}")

    print("\n--- Расшифровка POSTING ---")
    print(f"  Доход (sale_amount):     {posting_breakdown['revenue']:>15.2f}")
    print(f"  Возвраты товаров:        {posting_breakdown['returns']:>15.2f}")
    print(f"  Комиссия:                {posting_breakdown['commission']:>15.2f}")
    print(f"  Доставка и сервисы:      {posting_breakdown['delivery_services']:>15.2f}")

    print("\n--- По типам операций (расходы) ---")
    print(f"{'Тип операции':<35} {'Сумма':>15}")
    print("-" * 52)
    # Сортируем расходы от большего к меньшему (по абсолютному значению)
    for tid in sorted(by_type_id.keys(), key=lambda x: -by_type_id[x]):
        name = get_type_name(tid)
        print(f"{name:<35} {by_type_id[tid]:>15.2f}")

    print("\n--- По SKU (расходы) ---")
    print(f"{'SKU':<25} {'Сумма':>15}")
    print("-" * 42)
    for sku in sorted(by_sku.keys(), key=lambda x: -by_sku[x])[:20]:
        print(f"{sku:<25} {by_sku[sku]:>15.2f}")
    if len(by_sku) > 20:
        print(f"  ... и ещё {len(by_sku) - 20} SKU")

    # ------------------------------------------------------------------
    # Сверка с отчётом Ozon «Банк» / «Экономика»
    # ------------------------------------------------------------------
    by_bank_category = defaultdict(float)
    for tid_key, amount in by_type_id.items():
        tid_str = str(tid_key).replace("type_id:", "")
        bank_cat = OZON_BANK_CATEGORY_MAP.get(tid_str, "Прочие расходы Ozon")
        by_bank_category[bank_cat] += amount

    print("\n" + "=" * 80)
    print("СВЕРКА С ОТЧЁТОМ OZON «БАНК» / «ЭКОНОМИКА»")
    print("=" * 80)
    print(
        "\nПримечание: API accrual/by-day НЕ возвращает себестоимость товара.\n"
        "Поэтому «Прибыль» из API = «Прибыль» Ozon Банк + «Себестоимость».\n"
        "Также «Доходы» API (sale_amount) могут отличаться от «Продаж» Банка\n"
        "на сумму возвратов/отмен, которые в Банке учитываются отдельно."
    )

    print(f"\n{'Категория Ozon Банк':<30} {'Сумма':>15}")
    print("-" * 47)
    bank_order = [
        "Комиссия МП",
        "Эквайринг",
        "Логистика",
        "Хранение",
        "Возвраты и отмены",
        "Реклама Ozon",
        "Прочие расходы Ozon",
        "Прочие доходы",
    ]
    for cat in bank_order:
        if cat in by_bank_category:
            print(f"{cat:<30} {by_bank_category[cat]:>15.2f}")
    for cat in sorted(by_bank_category.keys()):
        if cat not in bank_order:
            print(f"{cat:<30} {by_bank_category[cat]:>15.2f}")

    bank_total_expense = sum(by_bank_category.values())
    print("-" * 47)
    print(f"{'ИТОГО расходы (API)':<30} {bank_total_expense:>15.2f}")
    print(f"{'Себестоимость (БД)':<30} {total_cost_price:>15.2f}")
    print(f"{'Доходы (sale_amount, API)':<30} {total_revenue:>15.2f}")
    print(f"{'Возвраты (sale_amount < 0)':<30} {total_returns_amount:>15.2f}")
    print(f"{'Прибыль (Net, финальная)':<30} {total_revenue - total_returns_amount - bank_total_expense - total_cost_price:>15.2f}")

    if total_cost_price == 0 and total_revenue > 0:
        print(
            "\nВНИМАНИЕ: Себестоимость равна 0.00. Проверьте, заполнены ли данные\n"
            "в новой таблице product_costs для используемых SKU."
        )


async def main():
    parser = argparse.ArgumentParser(
        description="Тест расчёта расходов через accrual/by-day (один день или период)"
    )
    # Позиционные даты: 0 (дефолт), 1 (один день) или 2 (период start..end)
    parser.add_argument(
        "dates",
        nargs="*",
        help="Дата (YYYY-MM-DD) или период: дата_начала дата_конца"
    )
    parser.add_argument("--start", type=str, default=None, help="Дата начала периода (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="Дата конца периода (YYYY-MM-DD)")
    parser.add_argument("--date", type=str, default=None, help="Одиночная дата (YYYY-MM-DD). Алиас для совместимости.")
    parser.add_argument("--user", type=int, default=None, help="ID пользователя (по умолчанию первый)")
    parser.add_argument("--raw", action="store_true", help="Вывести сырые данные каждой транзакции")
    args = parser.parse_args()

    # --- Разбор дат в (start_date, end_date) ---
    start_str = args.start
    end_str = args.end

    if args.date and not args.dates:
        # Совместимость: --date YYYY-MM-DD
        if start_str or end_str:
            print("Ошибка: нельзя указывать --date вместе с --start/--end")
            return
        start_str = end_str = args.date
    elif len(args.dates) == 1:
        if start_str or end_str:
            print("Ошибка: нельзя указывать позиционную дату вместе с --start/--end")
            return
        start_str = end_str = args.dates[0]
    elif len(args.dates) == 2:
        if start_str or end_str:
            print("Ошибка: нельзя указывать две позиционные даты вместе с --start/--end")
            return
        start_str, end_str = args.dates[0], args.dates[1]
    elif len(args.dates) == 0 and not start_str and not end_str:
        # Дефолт — сегодня (для обратной совместимости оставим конкретную дату)
        today = datetime.now().strftime(DATE_FORMAT)
        start_str = end_str = today

    if not start_str or not end_str:
        # Указан только один из --start/--end
        print("Ошибка: нужно указать обе даты (--start и --end) либо одну дату позиционно/--date")
        return

    try:
        start_date = parse_date(start_str)
        end_date = parse_date(end_str)
    except argparse.ArgumentTypeError as e:
        print(f"Ошибка: {e}")
        return

    if start_date > end_date:
        print(f"Ошибка: дата начала ({start_str}) больше даты конца ({end_str})")
        return

    session = SessionLocal()

    # Получаем пользователя
    if args.user:
        user = session.query(User).filter(User.id == args.user).first()
    else:
        user = session.query(User).first()

    if not user:
        print("Пользователь не найден")
        return

    print(f"Пользователь: id={user.id}, email={getattr(user, 'email', 'N/A')}")

    # Получаем credentials
    cred = session.query(OzonCredential).filter(
        OzonCredential.user_id == user.id,
        OzonCredential.is_active == True
    ).first()

    if not cred:
        print("Активные credentials не найдены")
        return

    client_id = decrypt_credential(cred.client_id_encrypted)
    api_key = decrypt_credential(cred.api_key_encrypted)
    print(f"Client-Id: {client_id[:4]}...")

    days_count = (end_date - start_date).days + 1
    print(f"\nПериод: {start_date.strftime(DATE_FORMAT)} .. {end_date.strftime(DATE_FORMAT)} ({days_count} дн.)")
    print("Запрос к Ozon API: /v1/finance/accrual/by-day")

    # Инициализируем httpx-клиент
    init_http_client()

    accumulator = new_accumulator()

    try:
        for d in daterange(start_date, end_date):
            date_str = d.strftime(DATE_FORMAT)
            print(f"\n>>> Запрос за {date_str} ...")
            accruals = await fetch_all_accruals(client_id, api_key, date_str)
            print(f"    Получено accruals: {len(accruals)}")

            if args.raw:
                if accruals:
                    print_raw_day(date_str, accruals)
                continue

            if not accruals:
                continue

            # ВАЖНО: себестоимость считаем на дату конкретного дня
            aggregate_day(accruals, db=session, user_id=user.id, target_date=d, acc=accumulator)

        if args.raw:
            return

        if accumulator["total_transactions"] == 0:
            print("\nНет данных за указанный период")
            return

        print_report(accumulator, start_date, end_date)

    finally:
        await close_http_client()
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
