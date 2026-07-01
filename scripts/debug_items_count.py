"""
Диагностический скрипт: сверка количества проданных товаров и выручки.

Сравнивает два источника данных:
  - OrderProduct (daily_stats) — нормализованные товары из заказов
  - OzonAccrual (sales_report) — финансовые операции с sale_amount > 0

Запуск:
    # Сверка за один день (детально)
    python scripts/debug_items_count.py 2026-06-15

    # Сверка за диапазон (кратко, только цифры)
    python scripts/debug_items_count.py 2026-06-01 2026-06-30

    # Детализация по SKU
    python scripts/debug_items_count.py 2026-06-15 --sku

    # Сравнение с эталоном Ozon (день/шт/руб)
    python scripts/debug_items_count.py 2026-06-01 2026-06-17 --ozon

    # Указать пользователя
    python scripts/debug_items_count.py 2026-06-15 --user 1
"""

import sys
import os
import argparse
from datetime import datetime, timedelta, timezone
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from db.database import (
    SessionLocal, User, Order, OrderPosting, OrderProduct,
    OzonAccrual, OzonCredential
)
from utils.common import to_msk
from sqlalchemy import func


def get_date_range(start_str: str, end_str: str = None):
    """Возвращает список дат от start до end (включительно)."""
    start = datetime.strptime(start_str, "%Y-%m-%d")
    if end_str:
        end = datetime.strptime(end_str, "%Y-%m-%d")
    else:
        end = start

    dates = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def count_from_order_products(db, user_id: int, date_obj: datetime, tz_offset: int = 3):
    """
    Считает заказы, товары и выручку из OrderPosting + OrderProduct (как daily_stats).
    Включает фоллбэк на сырую таблицу Order для постингов без энричмента.
    Возвращает: dict с ключами orders, items, revenue, by_sku
    """
    local_tz = timezone(timedelta(hours=tz_offset))

    day_start_local = datetime(date_obj.year, date_obj.month, date_obj.day, 0, 0, 0, tzinfo=local_tz)
    day_end_local = datetime(date_obj.year, date_obj.month, date_obj.day, 23, 59, 59, tzinfo=local_tz)

    search_since = (day_start_local - timedelta(hours=24)).astimezone(timezone.utc).replace(tzinfo=None)
    search_to = (day_end_local + timedelta(hours=24)).astimezone(timezone.utc).replace(tzinfo=None)

    # 1. Постинги из нормализованной таблицы
    postings_q = db.query(
        OrderPosting.posting_number,
        OrderPosting.created_at,
        OrderPosting.in_process_at,
        OrderPosting.status
    ).filter(
        OrderPosting.user_id == user_id,
        OrderPosting.created_at.between(search_since, search_to)
    ).all()

    valid_pns = set()
    target_date = date_obj.date()

    for pn, created, in_proc, status in postings_q:
        best_date = in_proc or created
        if not best_date:
            continue
        dt_local = to_msk(best_date, tz_offset)
        if dt_local and dt_local.date() == target_date:
            valid_pns.add(pn)

    # 2. Фоллбэк: постинги из сырой таблицы Order
    raw_q = db.query(
        Order.posting_number,
        Order.created_at,
        Order.status,
        Order.data
    ).filter(
        Order.user_id == user_id,
        Order.created_at.between(search_since, search_to)
    ).all()

    raw_only_pns = set()
    for pn, created, status, data in raw_q:
        if not pn or pn in valid_pns:
            continue
        dt_local = to_msk(created, tz_offset)
        if dt_local and dt_local.date() == target_date:
            raw_only_pns.add(pn)

    all_pns = list(valid_pns | raw_only_pns)
    if not all_pns:
        return {"orders": 0, "items": 0, "revenue": 0.0, "by_sku": {}}

    # 3. Агрегируем товары + выручку из OrderProduct
    results = db.query(
        OrderProduct.sku,
        OrderProduct.posting_number,
        func.sum(OrderProduct.quantity).label("qty"),
        func.sum(OrderProduct.price * OrderProduct.quantity).label("rev")
    ).filter(
        OrderProduct.user_id == user_id,
        OrderProduct.posting_number.in_(all_pns)
    ).group_by(OrderProduct.sku, OrderProduct.posting_number).all()

    by_sku = defaultdict(lambda: {"qty": 0, "revenue": 0.0})
    pns_with_products = set()
    total_revenue = 0.0

    for sku, pn, qty, rev in results:
        q = int(qty or 0)
        r = float(rev or 0)
        by_sku[sku or 0]["qty"] += q
        by_sku[sku or 0]["revenue"] += r
        pns_with_products.add(pn)
        total_revenue += r

    # 4. Фоллбэк: парсим из сырого JSON для постингов без OrderProduct
    pns_without_products = (valid_pns | raw_only_pns) - pns_with_products
    if pns_without_products:
        raw_rows = db.query(Order.posting_number, Order.data).filter(
            Order.user_id == user_id,
            Order.posting_number.in_(list(pns_without_products))
        ).all()
        for pn, data in raw_rows:
            if data and isinstance(data, dict):
                for p in data.get("products", []):
                    sku = p.get("sku") or 0
                    q = int(p.get("quantity") or 0)
                    pr = int(float(p.get("price") or 0))
                    by_sku[int(sku)]["qty"] += q
                    by_sku[int(sku)]["revenue"] += q * pr
                    total_revenue += q * pr

    total_items = sum(v["qty"] for v in by_sku.values())

    return {
        "orders": len(all_pns),
        "items": total_items,
        "revenue": round(total_revenue, 2),
        "by_sku": {k: v["qty"] for k, v in by_sku.items()},
        "revenue_by_sku": {k: round(v["revenue"], 2) for k, v in by_sku.items()},
    }


def count_from_ozon_accruals(db, user_id: int, date_obj: datetime, tz_offset: int = 3):
    """
    Считает заказы, товары и выручку из OzonAccrual WHERE type_id IS NULL (как sales_report).
    Возвращает: dict с ключами orders, items, revenue, by_sku
    """
    day_start = datetime(date_obj.year, date_obj.month, date_obj.day)

    # Только строки товаров (type_id IS NULL) и с положительным amount (продажи)
    results = db.query(
        OzonAccrual.sku,
        OzonAccrual.quantity,
        OzonAccrual.amount,
        OzonAccrual.unit_number
    ).filter(
        OzonAccrual.user_id == user_id,
        OzonAccrual.date == day_start,
        OzonAccrual.type_id.is_(None),
        OzonAccrual.amount > 0
    ).all()

    by_sku = defaultdict(lambda: {"qty": 0, "revenue": 0.0})
    unique_postings = set()
    total_revenue = 0.0

    for sku, qty, amount, unit_number in results:
        q = int(qty or 1)
        amt = float(amount or 0)
        by_sku[sku or 0]["qty"] += q
        by_sku[sku or 0]["revenue"] += amt
        total_revenue += amt
        if unit_number:
            unique_postings.add(unit_number)

    total_items = sum(v["qty"] for v in by_sku.values())

    return {
        "orders": len(unique_postings),
        "items": total_items,
        "revenue": round(total_revenue, 2),
        "by_sku": {k: v["qty"] for k, v in by_sku.items()},
        "revenue_by_sku": {k: round(v["revenue"], 2) for k, v in by_sku.items()},
    }


def print_single_day_detail(db, user_id: int, date_obj: datetime, show_sku: bool = False):
    """Детальный отчёт за один день с разбором расхождений."""
    date_str = date_obj.strftime("%Y-%m-%d")
    print("\n" + "=" * 80)
    print(f"ДЕТАЛЬНАЯ СВЕРКА ЗА {date_str}")
    print("=" * 80)

    op = count_from_order_products(db, user_id, date_obj)
    oa = count_from_ozon_accruals(db, user_id, date_obj)

    print(f"\n{'Источник':<40} {'Заказов':>8} {'Товаров':>8} {'Выручка':>12}")
    print("-" * 70)
    print(f"{'OrderProduct (daily_stats)':<40} {op['orders']:>8} {op['items']:>8} {op['revenue']:>12.2f}")
    print(f"{'OzonAccrual (sales_report)':<40} {oa['orders']:>8} {oa['items']:>8} {oa['revenue']:>12.2f}")
    print("-" * 70)

    diff_items = op["items"] - oa["items"]
    diff_rev = op["revenue"] - oa["revenue"]
    print(f"{'РАСХОЖДЕНИЕ':<40} {'':>8} {diff_items:>+8} {diff_rev:>+12.2f}")

    if diff_items == 0 and abs(diff_rev) < 0.01:
        print("\n✅ Расхождений нет!")
    else:
        print(f"\n⚠️  Расхождение: {diff_items:+d} шт, {diff_rev:+.2f} руб")

    # Детализация по SKU
    if show_sku or abs(diff_items) > 0:
        print("\n--- Разбор по SKU (количество) ---")
        print(f"{'SKU':<20} {'OrderProduct':>13} {'OzonAccrual':>13} {'Δ Кол-во':>10}")
        print("-" * 58)

        all_skus = sorted(set(list(op["by_sku"].keys()) + list(oa["by_sku"].keys())))
        for sku in all_skus:
            op_q = op["by_sku"].get(sku, 0)
            oa_q = oa["by_sku"].get(sku, 0)
            diff = op_q - oa_q
            marker = " ⚠️" if diff != 0 else ""
            print(f"{sku or 'N/A':<20} {op_q:>13} {oa_q:>13} {diff:>+10}{marker}")

        # Сравнение выручки по SKU
        if abs(diff_rev) > 0.01:
            print("\n--- Разбор по SKU (выручка) ---")
            print(f"{'SKU':<20} {'OrderProduct':>13} {'OzonAccrual':>13} {'Δ Выручка':>12}")
            print("-" * 60)
            for sku in all_skus:
                op_r = op["revenue_by_sku"].get(sku, 0.0)
                oa_r = oa["revenue_by_sku"].get(sku, 0.0)
                diff = op_r - oa_r
                if abs(diff) > 0.01:
                    print(f"{sku or 'N/A':<20} {op_r:>13.2f} {oa_r:>13.2f} {diff:>+12.2f} ⚠️")

    # Дополнительно: показываем записи с sale_amount = 0
    zero_sales = db.query(
        OzonAccrual.unit_number,
        OzonAccrual.sku,
        OzonAccrual.type_id,
        OzonAccrual.amount,
        OzonAccrual.operation_type
    ).filter(
        OzonAccrual.user_id == user_id,
        OzonAccrual.date == day_start,
        OzonAccrual.type_id.is_(None),
        OzonAccrual.amount == 0
    ).all()

    if zero_sales:
        print(f"\n--- Постинги с sale_amount = 0 ({len(zero_sales)} шт) ---")
        print("Это отмены/возвраты: товар списан, но выручка = 0.")
        for unit, sku, tid, amt, op_type in zero_sales[:15]:
            print(f"  {unit or 'N/A':<25} SKU={sku or 'N/A':<15} amount={amt} type={op_type}")
        if len(zero_sales) > 15:
            print(f"  ... и ещё {len(zero_sales) - 15}")


def print_range_summary(db, user_id: int, dates: list, show_sku: bool = False):
    """Краткий отчёт по диапазону дат с количеством и выручкой."""
    print("\n" + "=" * 100)
    print(f"СВОДНАЯ СВЕРКА: {dates[0].strftime('%Y-%m-%d')} — {dates[-1].strftime('%Y-%m-%d')}")
    print("=" * 100)

    header = f"{'Дата':<12} {'OP_Товары':>10} {'OA_Товары':>10} {'Δ_Товары':>9} | {'OP_Выручка':>12} {'OA_Выручка':>12} {'Δ_Выручка':>12}"
    print(f"\n{header}")
    print("-" * len(header))

    total_op_items = 0
    total_oa_items = 0
    total_op_rev = 0.0
    total_oa_rev = 0.0

    for date_obj in dates:
        op = count_from_order_products(db, user_id, date_obj)
        oa = count_from_ozon_accruals(db, user_id, date_obj)

        diff_items = op["items"] - oa["items"]
        diff_rev = op["revenue"] - oa["revenue"]

        total_op_items += op["items"]
        total_oa_items += oa["items"]
        total_op_rev += op["revenue"]
        total_oa_rev += oa["revenue"]

        marker = " ⚠️" if diff_items != 0 or abs(diff_rev) > 0.01 else ""
        date_str = date_obj.strftime("%Y-%m-%d")
        print(f"{date_str:<12} {op['items']:>10} {oa['items']:>10} {diff_items:>+9} | {op['revenue']:>12.2f} {oa['revenue']:>12.2f} {diff_rev:>+12.2f}{marker}")

    print("-" * len(header))
    total_diff_items = total_op_items - total_oa_items
    total_diff_rev = total_op_rev - total_oa_rev
    print(f"{'ИТОГО':<12} {total_op_items:>10} {total_oa_items:>10} {total_diff_items:>+9} | {total_op_rev:>12.2f} {total_oa_rev:>12.2f} {total_diff_rev:>+12.2f}")

    print("\n📌 OP = OrderProduct (как в daily_stats/графике)")
    print("📌 OA = OzonAccrual (как в sales_report/финансах)")


def print_ozon_comparison(db, user_id: int, dates: list, ozon_data: dict):
    """Сравнение с эталонными данными Ozon."""
    print("\n" + "=" * 110)
    print("СРАВНЕНИЕ С ЭТАЛОНОМ OZON")
    print("=" * 110)

    header = f"{'Дата':<12} {'Ozon_Шт':>8} {'OP_Шт':>8} {'OA_Шт':>8} | {'Ozon_Руб':>10} {'OP_Руб':>10} {'OA_Руб':>10} | {'Ближе':>8}"
    print(f"\n{header}")
    print("-" * len(header))

    op_correct_items = 0
    oa_correct_items = 0
    op_correct_rev = 0
    oa_correct_rev = 0
    total_days = 0

    for date_obj in dates:
        date_str = date_obj.strftime("%Y-%m-%d")
        if date_str not in ozon_data:
            continue

        total_days += 1
        oz_items, oz_rev = ozon_data[date_str]

        op = count_from_order_products(db, user_id, date_obj)
        oa = count_from_ozon_accruals(db, user_id, date_obj)

        op_diff_items = abs(op["items"] - oz_items)
        oa_diff_items = abs(oa["items"] - oz_items)
        op_diff_rev = abs(op["revenue"] - oz_rev)
        oa_diff_rev = abs(oa["revenue"] - oz_rev)

        # Какой источник ближе к Ozon?
        closer = "OP" if op_diff_items + op_diff_rev < oa_diff_items + oa_diff_rev else "OA"

        if op_diff_items == 0:
            op_correct_items += 1
        if oa_diff_items == 0:
            oa_correct_items += 1
        if op_diff_rev < 1:
            op_correct_rev += 1
        if oa_diff_rev < 1:
            oa_correct_rev += 1

        m1 = "✅" if op_diff_items == 0 else ("⚠️" if op_diff_items <= 2 else "❌")
        m2 = "✅" if oa_diff_items == 0 else ("⚠️" if oa_diff_items <= 2 else "❌")

        print(f"{date_str:<12} {oz_items:>8} {op['items']:>8}{m1} {oa['items']:>8}{m2} | {oz_rev:>10.0f} {op['revenue']:>10.0f} {oa['revenue']:>10.0f} | {closer:>8}")

    print("-" * len(header))
    print(f"\n📊 ИТОГО за {total_days} дней:")
    print(f"   OrderProduct точное совпадение:  {op_correct_items}/{total_days} (шт), {op_correct_rev}/{total_days} (руб)")
    print(f"   OzonAccrual точное совпадение:   {oa_correct_items}/{total_days} (шт), {oa_correct_rev}/{total_days} (руб)")

    print("\n💡 Вывод: источник с большим числом совпадений — наиболее точный.")


def main():
    parser = argparse.ArgumentParser(
        description="Сверка количества и выручки: OrderProduct vs OzonAccrual",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python scripts/debug_items_count.py 2026-06-15
  python scripts/debug_items_count.py 2026-06-01 2026-06-30
  python scripts/debug_items_count.py 2026-06-15 --sku
  python scripts/debug_items_count.py 2026-06-08 2026-06-17 --ozon
  python scripts/debug_items_count.py 2026-06-15 --user 1
        """
    )
    parser.add_argument("start_date", help="Начальная дата (YYYY-MM-DD)")
    parser.add_argument("end_date", nargs="?", default=None, help="Конечная дата (YYYY-MM-DD)")
    parser.add_argument("--user", type=int, default=None, help="ID пользователя")
    parser.add_argument("--sku", action="store_true", help="Показать детализацию по SKU")
    parser.add_argument("--ozon", action="store_true", help="Сравнить с эталоном Ozon (шт/руб)")
    args = parser.parse_args()

    # Эталонные данные Ozon, предоставленные пользователем
    OZON_REFERENCE = {
        "2026-06-08": (16, 2886),
        "2026-06-09": (18, 3481),
        "2026-06-10": (16, 3422),
        "2026-06-11": (25, 5141),
        "2026-06-12": (27, 5310),
        "2026-06-13": (14, 3332),
        "2026-06-14": (34, 7595),
        "2026-06-15": (57, 13428),
        "2026-06-16": (46, 9993),
        "2026-06-17": (25, 5627),
    }

    db = SessionLocal()

    try:
        if args.user:
            user = db.query(User).filter(User.id == args.user).first()
        else:
            user = db.query(User).first()

        if not user:
            print("Пользователь не найден")
            return

        print(f"Пользователь: id={user.id}, email={getattr(user, 'email', 'N/A')}")

        dates = get_date_range(args.start_date, args.end_date)

        if args.ozon:
            print_ozon_comparison(db, user.id, dates, OZON_REFERENCE)
        elif len(dates) == 1:
            print_single_day_detail(db, user.id, dates[0], show_sku=args.sku)
        else:
            print_range_summary(db, user.id, dates, show_sku=args.sku)

    finally:
        db.close()


if __name__ == "__main__":
    main()