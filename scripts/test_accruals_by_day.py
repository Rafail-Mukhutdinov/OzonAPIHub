"""
Тестовый скрипт для проверки расчёта расходов через /v1/finance/accrual/by-day.

Запуск:
    python scripts/test_accruals_by_day.py 2026-06-15
    python scripts/test_accruals_by_day.py 2026-06-15 --user 1
    python scripts/test_accruals_by_day.py 2026-06-15 --raw

Без --raw выводит агрегированный отчёт по расходам.
С --raw выводит каждую транзакцию отдельно.
"""

import sys
import os
import asyncio
import argparse
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


# Справочник типов операций Ozon (Синхронизировано с 'Экономикой' Озон)
OZON_TYPE_NAMES = {
    "commission": "Комиссия за продажу",
    "1": "Эквайринг",
    "12": "Магистраль / Логистика",
    "29": "Последняя миля",
    "32": "Логистика (FBO)",
    "38": "Прочие услуги (Ozon)",
    "39": "Логистика (Доп. услуги)",
    "41": "Реклама Ozon (Продвижение)",
    "45": "Обработка отмен",
    "46": "Хранение (Обработка возвратов)",
    "59": "Доставка",
    "74": "Хранение на складе",
    "98": "Утилизация",
    "101": "Реклама (Продвижение)",
    "102": "Бонусы продавца",
    "305": "Доставка сторонними службами",
}

# Маппинг type_id → категория отчёта Ozon "Банк" / "Экономика".
# Используется для сверки с отчётом Ozon (вкладка "Банк" → "Экономика").
# ВАЖНО: себестоимость товара (1161.00 ₽ в примере) НЕ возвращается API
# accrual/by-day — она берётся из отдельного справочника себестоимостей.
OZON_BANK_CATEGORY_MAP = {
    "commission": "Комиссия МП",
    "1": "Эквайринг",
    "12": "Логистика",
    "29": "Прочие расходы Ozon",
    "32": "Логистика",
    "38": "Прочие расходы Ozon",
    "39": "Логистика",
    "41": "Реклама Ozon",
    "45": "Возвраты и отмены",
    "46": "Хранение",
    "59": "Логистика",
    "74": "Прочие расходы Ozon",
    "98": "Прочие расходы Ozon",
    "101": "Реклама Ozon",
    "102": "Прочие доходы",
    "305": "Логистика",
}


def get_type_name(tid) -> str:
    """Возвращает человекочитаемое название типа операции."""
    tid_str = str(tid).replace("type_id:", "")
    return OZON_TYPE_NAMES.get(tid_str, f"Операция {tid_str}")


def analyze_accruals(accruals: list, raw: bool = False):
    """Анализирует accruals и выводит отчёт по расходам."""
    if raw:
        print("\n" + "=" * 80)
        print("RAW ВЫВОД КАЖДОЙ ТРАНЗАКЦИИ")
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
        return

    # Агрегация
    total_revenue = 0.0
    total_expense = 0.0

    # По категориям
    by_category = defaultdict(lambda: {"revenue": 0.0, "expense": 0.0, "count": 0})
    # По type_id (для расходов)
    by_type_id = defaultdict(float)
    # По SKU (для расходов)
    by_sku = defaultdict(float)
    # Детально по POSTING: комиссия / доставка / доход
    posting_breakdown = {
        "revenue": 0.0,
        "commission": 0.0,
        "delivery_services": 0.0,
    }

    for acc in accruals:
        category = acc.get("accrued_category") or "UNKNOWN"
        amount_data = acc.get("total_amount") or {}
        total_amount = parse_amount(amount_data)

        by_category[category]["count"] += 1

        if category == "POSTING" and acc.get("posting"):
            # Распаковка POSTING
            p_data = acc["posting"]
            for prod in p_data.get("products", []):
                sku = prod.get("sku")
                comm = prod.get("commission") or {}

                # Доход
                rev = parse_amount(comm.get("sale_amount"))
                if rev > 0:
                    total_revenue += rev
                    by_category[category]["revenue"] += rev
                    posting_breakdown["revenue"] += rev

                # Комиссия
                comm_amt = parse_amount(comm.get("commission"))
                if comm_amt != 0:
                    # Считаем расход как положительное число для отчета
                    abs_comm = abs(comm_amt)
                    total_expense += abs_comm
                    by_category[category]["expense"] += abs_comm
                    by_type_id["commission"] += abs_comm
                    by_sku[f"sku:{sku}"] += abs_comm
                    posting_breakdown["commission"] += abs_comm

                # Доставка и сервисы
                deliv = prod.get("delivery") or {}
                for srv in deliv.get("services", []):
                    srv_amt = parse_amount(srv.get("accrued"))
                    if srv_amt != 0:
                        abs_srv = abs(srv_amt)
                        total_expense += abs_srv
                        by_category[category]["expense"] += abs_srv
                        type_id = srv.get("type_id", "unknown")
                        by_type_id[f"type_id:{type_id}"] += abs_srv
                        by_sku[f"sku:{sku}"] += abs_srv
                        posting_breakdown["delivery_services"] += abs_srv
        else:
            # ITEM и NON_ITEM
            amount = total_amount
            if amount > 0:
                total_revenue += amount
                by_category[category]["revenue"] += amount
            else:
                abs_amt = abs(amount)
                total_expense += abs_amt
                by_category[category]["expense"] += abs_amt

                type_id = None
                sku = None
                if category == "ITEM":
                    item_fees = acc.get("item_fees") or {}
                    if item_fees.get("fees"):
                        fee_item = item_fees["fees"][0]
                        sku = fee_item.get("sku")
                        if fee_item.get("fees"):
                            type_id = fee_item["fees"][0].get("type_id")
                elif category == "NON_ITEM":
                    ni_fee = acc.get("non_item_fee") or {}
                    type_id = ni_fee.get("type_id")

                if type_id is not None:
                    by_type_id[f"type_id:{type_id}"] += abs_amt
                if sku is not None:
                    by_sku[f"sku:{sku}"] += abs_amt

    # Вывод отчёта
    print("\n" + "=" * 80)
    print("ОТЧЁТ ПО РАСХОДАМ (accrual/by-day)")
    print("=" * 80)

    print(f"\nВсего транзакций: {len(accruals)}")
    print(f"Общий доход:   {total_revenue:>15.2f} руб")
    print(f"Общий расход:  {total_expense:>15.2f} руб")
    print(f"Чистая выплата: {total_revenue - total_expense:>14.2f} руб")

    print("\n--- По категориям ---")
    print(f"{'Категория':<15} {'Доход':>15} {'Расход':>15} {'Кол-во':>8}")
    print("-" * 55)
    for cat in sorted(by_category.keys()):
        d = by_category[cat]
        print(f"{cat:<15} {d['revenue']:>15.2f} {d['expense']:>15.2f} {d['count']:>8}")

    print("\n--- Расшифровка POSTING ---")
    print(f"  Доход (sale_amount):     {posting_breakdown['revenue']:>15.2f}")
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
    print(f"{'Доходы (sale_amount, API)':<30} {total_revenue:>15.2f}")
    print(f"{'Прибыль (API, без себестоимости)':<30} {total_revenue - bank_total_expense:>15.2f}")
    print(
        "\nДля полного соответствия отчёту Ozon Банк добавьте себестоимость\n"
        "товаров из отдельного справочника (в примере за 28.06.2026: 1161.00 ₽)."
    )


async def main():
    parser = argparse.ArgumentParser(description="Тест расчёта расходов через accrual/by-day")
    parser.add_argument("date", nargs="?", default="2026-06-28", help="Дата в формате YYYY-MM-DD (по умолчанию 2026-06-15)")
    parser.add_argument("--user", type=int, default=None, help="ID пользователя (по умолчанию первый)")
    parser.add_argument("--raw", action="store_true", help="Вывести сырые данные каждой транзакции")
    args = parser.parse_args()

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

    print(f"\nДата: {args.date}")
    print("Запрос к Ozon API: /v1/finance/accrual/by-day")

    # Инициализируем httpx-клиент
    init_http_client()

    try:
        accruals = await fetch_all_accruals(client_id, api_key, args.date)
        print(f"\nВсего получено accruals: {len(accruals)}")

        if not accruals:
            print("Нет данных за эту дату")
            return

        analyze_accruals(accruals, raw=args.raw)

    finally:
        await close_http_client()
        session.close()


if __name__ == "__main__":
    asyncio.run(main())