from db.database import SessionLocal, User, OrderProduct
from routes.analytics import parse_msk_date, _get_unified_postings, to_msk
from datetime import timezone
from sqlalchemy import func

session = SessionLocal()
user = session.query(User).first()
if not user:
    print('no user in db')
    raise SystemExit
print('user_id=', user.id)
expected = {
    '2026-06-17': (25, 5627),
    '2026-06-16': (46, 9993),
    '2026-06-15': (57, 13428),
    '2026-06-14': (34, 7595),
    '2026-06-13': (14, 3332),
}
for d in ['2026-06-17','2026-06-16','2026-06-15','2026-06-14','2026-06-13']:
    since = parse_msk_date(d, tz_offset_hours=3)
    to = parse_msk_date(d, end_of_day=True, tz_offset_hours=3)
    since_utc = since.astimezone(timezone.utc)
    to_utc = to.astimezone(timezone.utc)
    search_since = since_utc.isoformat().replace('+00:00','Z')
    search_to = to_utc.isoformat().replace('+00:00','Z')

    postings_map = _get_unified_postings(session, user.id, search_since, search_to, include_cancelled=True)
    final_postings = []
    for pn, data in postings_map.items():
        dt = to_msk(data['created_at'])
        if not dt:
            continue
        if dt.date().isoformat() == d:
            final_postings.append(pn)

    rows = session.query(func.coalesce(func.sum(OrderProduct.quantity),0), func.coalesce(func.sum(OrderProduct.price * OrderProduct.quantity),0)).filter(
        OrderProduct.user_id==user.id,
        OrderProduct.posting_number.in_(final_postings)
    ).first()
    qty = int(rows[0] or 0)
    amount = int(rows[1] or 0)
    print(f"{d}: DB -> qty={qty}, amount={amount}, orders={len(final_postings)} | expected qty={expected[d][0]}, amount={expected[d][1]}")

session.close()
