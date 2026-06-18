from collections import defaultdict

from db.database import SessionLocal, OrderPosting, OrderProduct, Order, User
from utils.common import to_msk

CHECK_POSTINGS = [
    "0238898860-0008-1","39412284-0152-1","24638859-0245-2","52058165-0390-1","07914366-0884-1","16242477-0155-1",
    "81271410-0096-17","81271410-0096-3","43992129-0156-1","0128239049-0108-1","61797364-0132-1","28456401-0112-5",
    "51052982-0528-1","76754285-0489-1","47127026-0255-1","32572988-0305-2","57313880-0059-7","45548820-0475-1",
    "0126683590-0179-1","53066316-0138-5","53066316-0138-3","53066316-0138-1","0121061786-1091-9","0121061786-1091-7",
    "0121061786-1091-5","0121061786-1091-3","0121061786-1091-1","0254180143-0007-27","0254180143-0007-25",
    "0254180143-0007-23","0254180143-0007-21","0254180143-0007-1","0207844500-0109-1","0186509397-0029-1","0211304427-0163-1",
    "0106913703-0590-3","35593836-0193-1","10330643-0277-1","13173502-0573-1","32411507-1684-1","0147109116-0125-1",
    "69624462-0168-3","0187865559-0016-1","60061938-0043-1","44377425-0233-1","49969613-0277-1","0123887484-0024-3",
    "0123887484-0024-1","32446645-0339-1","78400391-0353-1","68895324-0203-1","0128231224-0177-1","0184595274-0079-1",
    "30694858-1627-3","68907406-0258-1","40366456-0172-1","78693861-1889-1"
]


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
        postings = session.query(OrderPosting.posting_number, OrderPosting.created_at, OrderPosting.status).filter(OrderPosting.user_id == uid).all()
        raw_orders = session.query(Order.posting_number, Order.created_at).filter(Order.user_id == uid).all()

        normalized = []
        raw = []

        for pn, created_at, status in postings:
            date = msk_date(created_at)
            if date == date_str:
                normalized.append((pn, created_at, status))

        for pn, created_at in raw_orders:
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
