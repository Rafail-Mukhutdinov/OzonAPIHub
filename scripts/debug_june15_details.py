from db.database import SessionLocal, User, OrderProduct
from routes.analytics import parse_msk_date, _get_unified_postings, to_msk
from datetime import timezone
from sqlalchemy import func

session = SessionLocal()
user = session.query(User).first()
if not user:
    print('no user in db')
    raise SystemExit

d = '2026-06-15'
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
        final_postings.append((pn, data['created_at'], data.get('status')))

print('Total postings found:', len(final_postings))
print('Posting details:')
for pn, created_at, status in sorted(final_postings):
    rows = session.query(func.coalesce(func.sum(OrderProduct.quantity),0), func.coalesce(func.sum(OrderProduct.price * OrderProduct.quantity),0), func.coalesce(func.sum(OrderProduct.payout),0), func.coalesce(func.sum(OrderProduct.commission_amount),0)).filter(
        OrderProduct.user_id==user.id,
        OrderProduct.posting_number==pn
    ).first()
    qty = int(rows[0] or 0)
    amount = int(rows[1] or 0)
    payout = int(rows[2] or 0)
    commission = int(rows[3] or 0)
    print(pn, created_at, 'status=', status, f'qty={qty}', f'amount={amount}', f'payout={payout}', f'commission={commission}')

session.close()
