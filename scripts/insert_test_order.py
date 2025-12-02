import os
import sys
import json

# Ensure project root is on sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db.database import SessionLocal, Order

def insert():
    db = SessionLocal()
    try:
        o = Order(
            order_id=999999,
            posting_number='TEST-POSTING-999999',
            status='TEST',
            created_at='2025-12-02T00:00:00',
            updated_at='2025-12-02T00:00:00',
            data={'test': True}
        )
        db.add(o)
        db.commit()
        print('INSERTED')
    except Exception as e:
        print('ERROR', e)
    finally:
        # count rows
        try:
            rows = db.query(Order).count()
            print('TOTAL_ROWS', rows)
        except Exception as e:
            print('COUNT_ERROR', e)
        db.close()

if __name__ == '__main__':
    insert()
