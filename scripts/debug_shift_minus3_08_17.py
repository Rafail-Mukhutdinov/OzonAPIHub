from db.database import SessionLocal, User, OrderProduct, OrderPosting
from utils.common import parse_ozon_datetime
from datetime import timedelta
from collections import defaultdict

session = SessionLocal()
user = session.query(User).first()
if not user:
    print('no user')
    raise SystemExit

start='2026-06-08'
end='2026-06-17'
# Build list of dates
from datetime import datetime
s_dt = datetime.fromisoformat(start)
e_dt = datetime.fromisoformat(end)
days = []
cur = s_dt
while cur <= e_dt:
    days.append(cur.strftime('%Y-%m-%d'))
    cur = cur + timedelta(days=1)

agg_qty = defaultdict(int)
agg_amount = defaultdict(int)
agg_orders = defaultdict(set)

rows = session.query(OrderProduct.posting_number, OrderProduct.quantity, OrderProduct.price, OrderPosting.created_at).join(OrderPosting, OrderPosting.posting_number==OrderProduct.posting_number).filter(OrderProduct.user_id==user.id).all()
for pn, qty, price, created_at in rows:
    dt = parse_ozon_datetime(created_at)
    if not dt: continue
    shifted = dt - timedelta(hours=3)
    # determine date in MSK after shift
    # MSK is UTC+3; shifted is UTC; convert to MSK by adding 3 hours
    msk_dt = shifted + timedelta(hours=3)
    date = msk_dt.date().isoformat()
    if date >= start and date <= end:
        agg_qty[date] += int(qty or 0)
        agg_amount[date] += int((price or 0) * (qty or 0))
        agg_orders[date].add(pn)

for d in days:
    print(f"{d}: qty={agg_qty[d]}, amount={agg_amount[d]}, orders={len(agg_orders[d])}")

session.close()
