import asyncio
from db.database import SessionLocal, User, OzonCredential, OrderPosting
from utils.encryption import decrypt_credential
from services.ozon import ozon_fbo_list_async
from utils.common import parse_ozon_datetime

async def main():
    session = SessionLocal()
    user = session.query(User).first()
    if not user:
        print('no user')
        return
    
    cred = session.query(OzonCredential).filter(OzonCredential.user_id == user.id, OzonCredential.is_active == True).first()
    if not cred:
        print('no credentials')
        return
    
    client_id = decrypt_credential(cred.client_id_encrypted)
    api_key = decrypt_credential(cred.api_key_encrypted)
    
    # Fetch postings from Ozon for 08-17 June
    all_postings = []
    for offset in range(0, 2000, 50):
        resp = await ozon_fbo_list_async(
            client_id, api_key,
            {"since": "2026-06-08T00:00:00Z", "to": "2026-06-17T23:59:59Z"},
            limit=50,
            offset=offset
        )
        if not resp:
            break
        result = resp.get('result')
        if not result:
            break
        # result is a dict with 'postings' list
        if isinstance(result, dict):
            postings = result.get('postings', [])
        elif isinstance(result, list):
            postings = result
        else:
            postings = []
        if not postings:
            break
        all_postings.extend(postings)
        print(f"Fetched {len(all_postings)} postings so far...")
    
    print(f"\nTotal postings from Ozon: {len(all_postings)}")
    
    # Group by date
    from collections import defaultdict
    from utils.common import to_msk
    
    ozon_by_date = defaultdict(list)
    for p in all_postings:
        pn = p.get('posting_number')
        created = p.get('created_at')
        status = p.get('status')
        if created:
            dt = parse_ozon_datetime(created)
            if dt:
                msk_dt = to_msk(dt)
                date = msk_dt.date().isoformat()
                ozon_by_date[date].append((pn, status))
    
    # Compare with DB
    db_by_date = defaultdict(list)
    db_postings = session.query(OrderPosting).all()
    for op in db_postings:
        if op.created_at:
            dt = parse_ozon_datetime(op.created_at)
            if dt:
                msk_dt = to_msk(dt)
                date = msk_dt.date().isoformat()
                db_by_date[date].append((op.posting_number, op.status))
    
    print("\n=== COMPARISON ===")
    for date in sorted(set(list(ozon_by_date.keys()) + list(db_by_date.keys()))):
        if date >= '2026-06-08' and date <= '2026-06-17':
            ozon_list = sorted([pn for pn, _ in ozon_by_date[date]])
            db_list = sorted([pn for pn, _ in db_by_date[date]])
            only_in_ozon = set(ozon_list) - set(db_list)
            only_in_db = set(db_list) - set(ozon_list)
            print(f"{date}: Ozon={len(ozon_list)}, DB={len(db_list)}, only_in_ozon={len(only_in_ozon)}, only_in_db={len(only_in_db)}")
            if only_in_db:
                print(f"  Only in DB: {list(only_in_db)[:5]}")
            if only_in_ozon:
                print(f"  Only in Ozon: {list(only_in_ozon)[:5]}")
    
    session.close()

if __name__ == '__main__':
    asyncio.run(main())
