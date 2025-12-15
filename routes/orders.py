from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from db.database import Order, OrderHeader, OrderPosting, OrderProduct, get_db
from datetime import datetime

router = APIRouter(tags=["orders"])

def _normalize_iso(s: str | None) -> str | None:
    if not s:
        return None
    s2 = s.rstrip('Z')
    dt = datetime.fromisoformat(s2)
    dt = dt.replace(microsecond=0)
    return dt.isoformat() + 'Z'

@router.get("/orders")
async def list_orders(
    since: str | None = None,
    to: str | None = None,
    status: str | None = None,
    posting_number: str | None = None,
    contains: str | None = None,
    limit: int = 50,
    offset: int = 0,
    sort: str = "-created_at",
    db: Session = Depends(get_db),
):
    try:
        since_iso = _normalize_iso(since)
        to_iso = _normalize_iso(to)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad date format")

    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    q = db.query(Order)
    if since_iso:
        q = q.filter(Order.created_at >= since_iso)
    if to_iso:
        q = q.filter(Order.created_at <= to_iso)
    if status:
        q = q.filter(Order.status == status)
    if posting_number:
        q = q.filter(Order.posting_number == posting_number)
    if contains:
        q = q.filter(Order.posting_number.like(f"%{contains}%"))

    total = q.count()
    if sort == "created_at":
        q = q.order_by(Order.created_at.asc())
    else:
        q = q.order_by(Order.created_at.desc())

    rows = q.offset(offset).limit(limit).all()
    items = [
        {
            "id": r.id,
            "order_id": r.order_id,
            "posting_number": r.posting_number,
            "status": r.status,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "data": r.data,
        }
        for r in rows
    ]
    return {"total": total, "limit": limit, "offset": offset, "items": items}

@router.get("/orders/{posting_number}")
async def get_order_by_posting(posting_number: str, db: Session = Depends(get_db)):
    row = db.query(Order).filter(Order.posting_number == posting_number).first()
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    return row

@router.get("/order/{order_number}")
async def get_order_summary(order_number: str, db: Session = Depends(get_db)):
    header = db.query(OrderHeader).filter(OrderHeader.order_number == order_number).first()
    postings = db.query(OrderPosting).filter(OrderPosting.order_number == order_number).order_by(OrderPosting.created_at.asc()).all()
    products = db.query(OrderProduct).filter(OrderProduct.posting_number.in_([p.posting_number for p in postings])).all() if postings else []
    total_payout = sum((p.payout or 0) for p in products)
    total_commission = sum((p.commission_amount or 0) for p in products)
    profit = total_payout - total_commission
    return {
        "order_number": order_number,
        "header": {
            "first_created_at": header.first_created_at if header else None,
            "last_delivery_at": header.last_delivery_at if header else None,
            "total_payout": header.total_payout if header and header.total_payout is not None else total_payout,
            "total_commission": header.total_commission if header and header.total_commission is not None else total_commission,
            "profit": profit,
        },
        "postings": [
            {
                "posting_number": p.posting_number,
                "status": p.status,
                "created_at": p.created_at,
                "in_process_at": p.in_process_at,
                "fact_delivery_date": p.fact_delivery_date,
                "substatus": p.substatus,
                "analytics_data": p.analytics_data,
                "financial_data": p.financial_data,
                "products": [
                    {
                        "sku": pr.sku,
                        "offer_id": pr.offer_id,
                        "name": pr.name,
                        "quantity": pr.quantity,
                        "price": pr.price,
                        "currency_code": pr.currency_code,
                        "commission_amount": pr.commission_amount,
                        "commission_percent": pr.commission_percent,
                        "payout": pr.payout,
                        "total_discount_value": pr.total_discount_value,
                        "total_discount_percent": pr.total_discount_percent,
                    }
                    for pr in products if pr.posting_number == p.posting_number
                ],
            }
            for p in postings
        ],
    }

@router.get("/order/{order_number}/postings")
async def list_order_postings(order_number: str, db: Session = Depends(get_db)):
    postings = db.query(OrderPosting).filter(OrderPosting.order_number == order_number).order_by(OrderPosting.created_at.asc()).all()
    if not postings:
        prefix = order_number + "-"
        legacy_postings = db.query(Order.posting_number).filter(Order.posting_number.like(f"{prefix}%")).all()
        postings = [
            OrderPosting(order_number=order_number, posting_number=p[0], status=None, created_at=None)
            for p in legacy_postings
        ]
    result = []
    for p in postings:
        prods = db.query(OrderProduct).filter(OrderProduct.posting_number == p.posting_number).all()
        total_payout = sum((pr.payout or 0) for pr in prods)
        total_commission = sum((pr.commission_amount or 0) for pr in prods)
        result.append({
            "posting_number": p.posting_number,
            "status": p.status,
            "created_at": p.created_at,
            "products_count": len(prods),
            "total_payout": total_payout,
            "total_commission": total_commission,
        })
    return {"order_number": order_number, "count": len(result), "items": result}
