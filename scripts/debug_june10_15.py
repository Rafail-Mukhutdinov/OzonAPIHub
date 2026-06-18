from collections import defaultdict

from db.database import SessionLocal, OrderPosting, OrderProduct, Order, User
from utils.common import to_msk


def is_cancelled(status: str | None) -> bool:
    if not status:
        return False
    status_lower = str(status).lower()
    return any(token in status_lower for token in ["cancelled", "cancel", "отменен", "отменён"])


def msk_date(value):
    dt = to_msk(value)
    return dt.date().isoformat() if dt else None


def analyze_date(date_str):
    session = SessionLocal()
    try:
        user = session.query(User).first()
        if not user:
            print("No user found")
            return

        uid = user.id
        normalized = []
        raw = []

        for pn, created_at, status in session.query(OrderPosting.posting_number, OrderPosting.created_at, OrderPosting.status).filter(OrderPosting.user_id == uid).all():
            date = msk_date(created_at)
            if date == date_str:
                normalized.append((pn, created_at, status))

        for pn, created_at in session.query(Order.posting_number, Order.created_at).filter(Order.user_id == uid).all():
            date = msk_date(created_at)
            if date == date_str:
                raw.append((pn, created_at))

        normalized_set = {pn for pn, _, _ in normalized}
        raw_set = {pn for pn, _ in raw}

        totals = {"all_amount": 0, "all_qty": 0, "all_orders": 0, "nocancel_amount": 0, "nocancel_qty": 0, "nocancel_orders": 0}
        counts = defaultdict(int)

        for pn, created_at, status in normalized:
            counts[str(status).lower()] += 1
            products = session.query(OrderProduct.price, OrderProduct.quantity).filter(
                OrderProduct.user_id == uid,
                OrderProduct.posting_number == pn,
            ).all()
            amount = sum((p.price or 0) * (p.quantity or 0) for p in products)
            qty = sum((p.quantity or 0) for p in products)
            totals["all_amount"] += amount
            totals["all_qty"] += qty
            totals["all_orders"] += 1
            if not is_cancelled(status):
                totals["nocancel_amount"] += amount
                totals["nocancel_qty"] += qty
                totals["nocancel_orders"] += 1

        print(f"=== {date_str} ===")
        print("normalized count:", len(normalized))
        print("raw count:", len(raw))
        print("status_counts:", dict(counts))
        print("totals:", totals)
        print("raw-only postings:", sorted(raw_set - normalized_set))
        print("normalized-only postings:", sorted(normalized_set - raw_set))
        print()
    finally:
        session.close()


def main():
    analyze_date("2026-06-10")
    analyze_date("2026-06-15")

    session = SessionLocal()
    try:
        user = session.query(User).first()
        if not user:
            return
        uid = user.id
        orders = session.query(OrderPosting.posting_number, OrderPosting.created_at, OrderPosting.status).filter(OrderPosting.user_id == uid).all()
        count_date = defaultdict(int)
        for pn, created_at, status in orders:
            date = msk_date(created_at)
            if date:
                count_date[date] += 1
        print("count by MSK date sample:")
        for d in sorted(count_date):
            if d in ["2026-06-10", "2026-06-15"]:
                print(d, count_date[d])
    finally:
        session.close()


if __name__ == '__main__':
    main()
