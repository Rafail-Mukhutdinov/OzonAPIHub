import sys
import os
import time
from datetime import datetime

# Ensure project root is on sys.path when running from scripts/
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db.database import SessionLocal, Order

print('Connecting to DB via SessionLocal...')
session = SessionLocal()
try:
    before_count = session.query(Order).count()
    print('Rows before:', before_count)

    # Insert test order
    ts = int(time.time())
    posting = f'TMP-TEST-{ts}'
    created_at = datetime.utcnow().isoformat() + 'Z'
    test_order = Order(
        order_id=999999999,
        posting_number=posting,
        status='TEST_CREATED',
        created_at=created_at,
        updated_at=created_at,
        data={'test': True, 'created_at': created_at}
    )
    session.add(test_order)
    session.commit()
    print('Inserted test posting_number:', posting)

    # Verify insert
    found = session.query(Order).filter(Order.posting_number == posting).first()
    if not found:
        print('ERROR: inserted row not found')
    else:
        print('Found inserted row id:', found.id, 'status:', found.status, 'created_at:', found.created_at)

    # Update status
    found.status = 'TEST_UPDATED'
    session.commit()
    found2 = session.query(Order).filter(Order.posting_number == posting).first()
    print('After update status:', found2.status)

    # Delete
    session.delete(found2)
    session.commit()
    after_count = session.query(Order).count()
    print('Rows after (should equal before):', after_count)

    if before_count == after_count:
        print('DB insert/update/delete cycle OK')
    else:
        print('Warning: row counts differ before/after')

finally:
    session.close()
