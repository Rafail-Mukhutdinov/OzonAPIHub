import os
import logging
from services.ozon import ozon_fbo_get_async
from sqlalchemy.orm import Session
from db.database import OrderHeader, OrderPosting, OrderProduct
from datetime import datetime

logger = logging.getLogger("uvicorn.error")


def _to_int(val):
    try:
        if val is None:
            return None
        if isinstance(val, (int,)):
            return val
        if isinstance(val, float):
            return int(round(val))
        return int(round(float(str(val).replace(',', '.'))))
    except Exception:
        return None


def recalc_order_header(db: Session, order_number: str):
    products = db.query(OrderProduct).join(OrderPosting, OrderPosting.posting_number == OrderProduct.posting_number) \
        .filter(OrderPosting.order_number == order_number).all()
    total_payout = sum((_to_int(p.payout) or 0) for p in products)
    total_commission = sum((_to_int(p.commission_amount) or 0) for p in products)
    postings = db.query(OrderPosting).filter(OrderPosting.order_number == order_number).all()
    first_created = None
    last_delivery = None
    for p in postings:
        if p.created_at:
            first_created = min(first_created, p.created_at) if first_created else p.created_at
        if p.fact_delivery_date:
            last_delivery = max(last_delivery, p.fact_delivery_date) if last_delivery else p.fact_delivery_date
    hdr = db.query(OrderHeader).filter(OrderHeader.order_number == order_number).first()
    if not hdr:
        hdr = OrderHeader(order_number=order_number)
        db.add(hdr)
    hdr.first_created_at = first_created
    hdr.last_delivery_at = last_delivery
    hdr.total_payout = total_payout
    hdr.total_commission = total_commission
    db.commit()


async def enrich_posting_from_ozon(posting_number: str, db: Session):
    """Асинхронно обогатить данные постинга из Ozon API."""
    data = (await ozon_fbo_get_async(posting_number)).get("result")
    if not data:
        return {"status": "no_result"}
    order_number = data.get("order_number")
    op = db.query(OrderPosting).filter(OrderPosting.posting_number == posting_number).first()
    if not op:
        op = OrderPosting(posting_number=posting_number)
        db.add(op)
    op.order_number = order_number
    op.status = data.get("status")
    op.created_at = data.get("created_at")
    op.in_process_at = data.get("in_process_at")
    op.fact_delivery_date = data.get("fact_delivery_date")
    op.substatus = data.get("substatus")
    op.analytics_data = data.get("analytics_data")
    op.financial_data = data.get("financial_data")
    db.commit()
    db.query(OrderProduct).filter(OrderProduct.posting_number == posting_number).delete()
    products = data.get("products", [])
    fin = (data.get("financial_data") or {}).get("products") or []
    fin_by_sku = {}
    fin_by_offer = {}
    for f in fin:
        pid = f.get("product_id")
        if pid is not None:
            fin_by_sku[str(pid)] = f
        sku_key = f.get("sku")
        if sku_key is not None:
            fin_by_sku[str(sku_key)] = f
        ofr = f.get("offer_id")
        if ofr:
            fin_by_offer[str(ofr)] = f
    for pr in products:
        sku = pr.get("sku")
        offer_id_val = pr.get("offer_id")
        f = fin_by_sku.get(str(sku)) or (fin_by_offer.get(str(offer_id_val)) if offer_id_val is not None else None)
        obj = OrderProduct(
            posting_number=posting_number,
            sku=_to_int(sku),
            offer_id=str(offer_id_val) if offer_id_val is not None else None,
            name=pr.get("name"),
            quantity=_to_int(pr.get("quantity")),
            price=_to_int(pr.get("price")),
            currency_code=pr.get("currency_code"),
            commission_amount=_to_int((f or {}).get("commission_amount")),
            commission_percent=_to_int((f or {}).get("commission_percent")),
            payout=_to_int((f or {}).get("payout")),
            total_discount_value=_to_int((f or {}).get("total_discount_value")),
            total_discount_percent=_to_int((f or {}).get("total_discount_percent")),
        )
        db.add(obj)
    db.commit()
    if order_number:
        recalc_order_header(db, order_number)
    return {"status": "ok", "order_number": order_number, "posting_number": posting_number, "products": len(products)}
