from db.database import SessionLocal, OrderPosting, OrderProduct
from utils.common import to_msk

session = SessionLocal()

postings = [
    '0125697353-0157-1',
    '08494044-0542-1',
    '32116759-0662-1',
    '0171965538-0048-1',
    '08494044-0543-1',
    '50616390-0292-1',
    '74361078-0733-1',
    '0149221573-0005-1',
    '18980487-0232-5',
    '18980487-0232-3',
    '18980487-0232-1',
    '0146320775-0124-7',
    '0146320775-0124-5',
    '0146320775-0124-4',
    '0143611258-0162-1',
    '20935394-0435-1'
]

for pn in postings:
    op = session.query(OrderPosting).filter(OrderPosting.posting_number == pn).first()
    print('POSTING', pn, '=>', 'FOUND' if op else 'MISSING')
    if op:
        print('  created_at=', op.created_at, 'status=', op.status)
        print('  msk=', to_msk(op.created_at))
        print('  fin_data=', op.financial_data)
        products = session.query(OrderProduct).filter(OrderProduct.posting_number == pn).all()
        print('  products count=', len(products))
        for p in products:
            print('    sku=', p.sku, 'price=', p.price, 'qty=', p.quantity, 'currency=', p.currency_code, 'offer=', p.offer_id)

rows = session.query(OrderPosting.posting_number, OrderPosting.created_at).filter(
    OrderPosting.created_at >= '2026-06-09T00:00:00Z',
    OrderPosting.created_at < '2026-06-12T00:00:00Z'
).all()
print('\nTotal postings 2026-06-09..11 UTC', len(rows))
for pn, created_at in rows[:20]:
    print('  ', pn, created_at, '->', to_msk(created_at), to_msk(created_at).date())

session.close()
