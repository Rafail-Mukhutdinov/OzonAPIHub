import asyncio
from db.database import SessionLocal, User, OzonCredential, OrderPosting, OrderProduct
from utils.encryption import decrypt_credential
from services.ozon import ozon_fbo_get_async
from utils.common import parse_ozon_datetime, to_msk
from collections import defaultdict

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
    
    # Get postings for problem dates (10, 15, 17 June)
    problem_dates = ['2026-06-10', '2026-06-15', '2026-06-17']
    
    postings_by_date = defaultdict(list)
    db_postings = session.query(OrderPosting).all()
    for op in db_postings:
        if op.created_at:
            dt = parse_ozon_datetime(op.created_at)
            if dt:
                msk_dt = to_msk(dt)
                date = msk_dt.date().isoformat()
                if date in problem_dates:
                    postings_by_date[date].append(op.posting_number)
    
    print("=== OZON FINANCIAL DATA ===\n")
    
    for date in problem_dates:
        print(f"\n{date}:")
        pn_list = postings_by_date[date]
        print(f"  Postings count: {len(pn_list)}")
        
        total_qty = 0
        total_amount = 0
        total_payout = 0
        
        for pn in pn_list[:5]:  # Check first 5
            try:
                resp = await ozon_fbo_get_async(client_id, api_key, pn)
                result = resp.get('result', {})
                fin_data = result.get('financial_data', {})
                products = fin_data.get('products', [])
                
                qty = 0
                amount = 0
                for p in products:
                    q = int(p.get('quantity', 0))
                    price = int(p.get('price', 0))
                    qty += q
                    amount += price * q
                
                total_qty += qty
                total_amount += amount
                total_payout += int(fin_data.get('payout', 0))
                
                print(f"    {pn}: qty={qty}, amount={amount}, payout={fin_data.get('payout', 0)}")
            except Exception as e:
                print(f"    {pn}: ERROR {str(e)[:50]}")
        
        # Compare with DB
        db_qty = 0
        db_amount = 0
        db_payout = 0
        for pn in pn_list:
            products = session.query(OrderProduct).filter(OrderProduct.posting_number == pn).all()
            for p in products:
                db_qty += int(p.quantity or 0)
                db_amount += int((p.price or 0) * (p.quantity or 0))
                db_payout += int(p.payout or 0)
        
        print(f"  Ozon (first 5): qty={total_qty}, amount={total_amount}, payout={total_payout}")
        print(f"  DB (all {len(pn_list)}): qty={db_qty}, amount={db_amount}, payout={db_payout}")
    
    session.close()

if __name__ == '__main__':
    asyncio.run(main())
