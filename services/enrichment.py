import os
import logging
from services.ozon import ozon_fbo_get_async
from sqlalchemy.orm import Session
from db.database import OrderHeader, OrderPosting, OrderProduct, User, OzonCredential
from utils.encryption import decrypt_credential
from datetime import datetime, timezone
from utils.logging_config import log_user_event

logger = logging.getLogger("OzonAPIHub")

def _to_int(val):
    """Экстремально надежное преобразование в число."""
    if val is None: return 0
    try:
        if isinstance(val, (int, float)): return int(round(float(val)))
        # Убираем пробелы, меняем запятую на точку
        cleaned = str(val).replace(',', '.').replace(' ', '').strip()
        if not cleaned: return 0
        return int(round(float(cleaned)))
    except Exception as e:
        logger.error(f"Ошибка парсинга цены/количества ({val}): {e}")
        return 0

def recalc_order_header(db: Session, order_number: str, user_id: int):
    products = db.query(OrderProduct).join(
        OrderPosting,
        (OrderPosting.posting_number == OrderProduct.posting_number) & (OrderPosting.user_id == OrderProduct.user_id)
    ).filter(OrderPosting.order_number == order_number, OrderPosting.user_id == user_id).all()

    total_payout = sum((p.payout or 0) for p in products)
    total_commission = sum((p.commission_amount or 0) for p in products)

    postings = db.query(OrderPosting).filter(OrderPosting.order_number == order_number, OrderPosting.user_id == user_id).all()
    first_created = None
    last_delivery = None
    for p in postings:
        if p.created_at:
            first_created = min(first_created, p.created_at) if first_created else p.created_at
        if p.fact_delivery_date:
            last_delivery = max(last_delivery, p.fact_delivery_date) if last_delivery else p.fact_delivery_date

    hdr = db.query(OrderHeader).filter(OrderHeader.order_number == order_number, OrderHeader.user_id == user_id).first()
    if not hdr:
        hdr = OrderHeader(order_number=order_number, user_id=user_id)
        db.add(hdr)
    hdr.first_created_at = first_created
    hdr.last_delivery_at = last_delivery
    hdr.total_payout = total_payout
    hdr.total_commission = total_commission
    db.commit()

async def enrich_posting_from_ozon(posting_number: str, user: User, db: Session):
    active_cred = db.query(OzonCredential).filter(OzonCredential.user_id == user.id, OzonCredential.is_active == True).first()
    if not active_cred: return {"status": "no_credentials"}
    
    client_id = decrypt_credential(active_cred.client_id_encrypted)
    api_key = decrypt_credential(active_cred.api_key_encrypted)

    try:
        response = await ozon_fbo_get_async(client_id, api_key, posting_number)
        data = response.get("result")
    except Exception as e:
        return {"status": "api_error", "detail": str(e)}

    if not data: return {"status": "no_result"}
    
    order_number = data.get("order_number")
    op = db.query(OrderPosting).filter(OrderPosting.posting_number == posting_number, OrderPosting.user_id == user.id).first()
    if not op:
        op = OrderPosting(posting_number=posting_number, user_id=user.id)
        db.add(op)
    
    op.order_number = order_number
    op.status = data.get("status")
    op.created_at = data.get("created_at")
    op.financial_data = data.get("financial_data")
    db.commit()
    
    db.query(OrderProduct).filter(OrderProduct.posting_number == posting_number, OrderProduct.user_id == user.id).delete()
    
    products_data = data.get("products", [])
    fin_products = (data.get("financial_data") or {}).get("products") or []
    fin_map = {str(f.get("sku") or f.get("product_id")): f for f in fin_products}

    for pr in products_data:
        sku = pr.get("sku")
        # Берем цену напрямую из товара
        price = _to_int(pr.get("price"))
        f = fin_map.get(str(sku))

        # ЛОГ ДЛЯ ОТЛАДКИ: Если цена 0, выведем что пришло от Ozon
        if price == 0:
            logger.warning(f"Ozon вернул нулевую цену для SKU {sku}: {pr.get('price')}")

        obj = OrderProduct(
            user_id=user.id,
            posting_number=posting_number,
            sku=_to_int(sku),
            offer_id=pr.get("offer_id"),
            name=pr.get("name"),
            quantity=_to_int(pr.get("quantity")),
            price=price,
            currency_code=pr.get("currency_code"),
            commission_amount=_to_int((f or {}).get("commission_amount")),
            payout=_to_int((f or {}).get("payout")),
        )
        db.add(obj)
    
    db.commit()
    if order_number: recalc_order_header(db, order_number, user.id)
    return {"status": "ok"}
