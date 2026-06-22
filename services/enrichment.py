import os
import logging
from services.ozon import ozon_fbo_get_async
from sqlalchemy.orm import Session
from db.database import OrderHeader, OrderPosting, OrderProduct, User, OzonCredential
from utils.encryption import decrypt_credential
from datetime import datetime, timezone
from utils.logging_config import log_user_event
from utils.common import parse_ozon_datetime, to_msk

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
            dt_created = parse_ozon_datetime(p.created_at)
            if dt_created:
                # Храним как ISO строку
                dt_str = dt_created.isoformat().replace('+00:00', 'Z')
                first_created = min(first_created, dt_str) if first_created else dt_str

        if p.fact_delivery_date:
            dt_delivery = parse_ozon_datetime(p.fact_delivery_date)
            if dt_delivery:
                dt_str = dt_delivery.isoformat().replace('+00:00', 'Z')
                last_delivery = max(last_delivery, dt_str) if last_delivery else dt_str

    hdr = db.query(OrderHeader).filter(OrderHeader.order_number == order_number, OrderHeader.user_id == user_id).first()
    if not hdr:
        hdr = OrderHeader(order_number=order_number, user_id=user_id)
        db.add(hdr)
    hdr.first_created_at = first_created
    hdr.last_delivery_at = last_delivery
    hdr.total_payout = total_payout
    hdr.total_commission = total_commission

async def enrich_posting_from_ozon(
    posting_number: str,
    user_id: int,
    db: Session,
    client_id: str = None,
    api_key: str = None
):
    # Если ключи не переданы, ищем их в базе (для одиночных вызовов)
    if not client_id or not api_key:
        active_cred = db.query(OzonCredential).filter(OzonCredential.user_id == user_id, OzonCredential.is_active == True).first()
        if not active_cred: return {"status": "no_credentials"}

        client_id = decrypt_credential(active_cred.client_id_encrypted)
        api_key = decrypt_credential(active_cred.api_key_encrypted)

    try:
        response = await ozon_fbo_get_async(client_id, api_key, posting_number)

        # Robust parsing
        if not isinstance(response, dict):
            logger.warning(f"Ozon API returned {type(response)} instead of dict for {posting_number}")
            return {"status": "api_error", "detail": "Unexpected response format"}

        data = response.get("result")
        if not isinstance(data, dict):
            logger.warning(f"Ozon API result is {type(data)} instead of dict for {posting_number}")
            return {"status": "no_result"}

    except Exception as e:
        logger.error(f"Error fetching posting {posting_number} for user {user_id}: {e}")
        return {"status": "api_error", "detail": str(e)}

    order_number = data.get("order_number")
    op = db.query(OrderPosting).filter(OrderPosting.posting_number == posting_number, OrderPosting.user_id == user_id).first()
    if not op:
        op = OrderPosting(posting_number=posting_number, user_id=user_id)
        db.add(op)
    
    op.order_number = order_number
    op.status = data.get("status")
    op.substatus = data.get("substatus")

    # Нормализация дат при сохранении (всегда UTC с Z, без микросекунд)
    def norm(raw):
        dt = parse_ozon_datetime(raw)
        if dt:
            return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        return raw

    op.created_at = norm(data.get("created_at"))
    op.in_process_at = norm(data.get("in_process_at"))
    op.fact_delivery_date = norm(data.get("fact_delivery_date"))

    op.financial_data = data.get("financial_data")
    op.analytics_data = data.get("analytics_data")

    # Удаляем старые товары перед добавлением новых
    db.query(OrderProduct).filter(OrderProduct.posting_number == posting_number, OrderProduct.user_id == user_id).delete()
    
    products_data = data.get("products", [])
    if not isinstance(products_data, list):
        logger.warning(f"Products data is not a list for {posting_number}: {type(products_data)}")
        products_data = []

    fin_data = data.get("financial_data") or {}
    fin_products = fin_data.get("products") if isinstance(fin_data, dict) else []
    if not isinstance(fin_products, list):
        fin_products = []

    fin_map = {}
    for f in fin_products:
        if isinstance(f, dict):
            sku_key = str(f.get("sku") or f.get("product_id") or "")
            if sku_key:
                fin_map[sku_key] = f

    for pr in products_data:
        if not isinstance(pr, dict): continue
        sku = pr.get("sku")
        f = fin_map.get(str(sku))

        # ПРИОРИТЕТ: берем цену из финансового блока (она в рублях, даже если заказ в KZT/BYN)
        # Если в фин. блоке пусто, берем из общего списка товаров
        price = 0
        if f and f.get("price") is not None:
            price = _to_int(f.get("price"))
        else:
            price = _to_int(pr.get("price"))

        if price == 0:
            logger.warning(f"Ozon returned zero price for SKU {sku} in posting {posting_number} (user {user_id})")

        obj = OrderProduct(
            user_id=user_id,
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
    
    if order_number:
        recalc_order_header(db, order_number, user_id)

    # Больше НЕ делаем здесь db.commit(), это ответственность вызывающего кода
    return {"status": "ok"}
