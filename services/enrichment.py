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


def recalc_order_header(db: Session, order_number: str, user_id: int):
    """Пересчет заголовка заказа для конкретного пользователя."""
    # Используем join для точности
    products = db.query(OrderProduct).join(
        OrderPosting,
        (OrderPosting.posting_number == OrderProduct.posting_number) & (OrderPosting.user_id == OrderProduct.user_id)
    ).filter(
        OrderPosting.order_number == order_number,
        OrderPosting.user_id == user_id
    ).all()

    total_payout = sum((_to_int(p.payout) or 0) for p in products)
    total_commission = sum((_to_int(p.commission_amount) or 0) for p in products)

    postings = db.query(OrderPosting).filter(
        OrderPosting.order_number == order_number,
        OrderPosting.user_id == user_id
    ).all()

    first_created = None
    last_delivery = None
    for p in postings:
        if p.created_at:
            first_created = min(first_created, p.created_at) if first_created else p.created_at
        if p.fact_delivery_date:
            last_delivery = max(last_delivery, p.fact_delivery_date) if last_delivery else p.fact_delivery_date

    hdr = db.query(OrderHeader).filter(
        OrderHeader.order_number == order_number,
        OrderHeader.user_id == user_id
    ).first()

    if not hdr:
        hdr = OrderHeader(order_number=order_number, user_id=user_id)
        db.add(hdr)

    hdr.first_created_at = first_created
    hdr.last_delivery_at = last_delivery
    hdr.total_payout = total_payout
    hdr.total_commission = total_commission
    db.commit()


async def enrich_posting_from_ozon(posting_number: str, user: User, db: Session):
    """
    Асинхронно обогатить данные постинга из Ozon API.
    Использует активные Ozon credentials конкретного пользователя.
    """
    # Получаем активные credentials пользователя
    active_cred = db.query(OzonCredential).filter(
        OzonCredential.user_id == user.id,
        OzonCredential.is_active == True
    ).first()
    
    if not active_cred:
        log_user_event(user.id, f"Обогащение {posting_number} отменено: нет активных ключей", "warning")
        return {"status": "no_credentials"}
    
    # Расшифровка credentials
    client_id = decrypt_credential(active_cred.client_id_encrypted)
    api_key = decrypt_credential(active_cred.api_key_encrypted)
    
    if not client_id or not api_key:
        error_msg = f"Ошибка расшифровки Ozon credentials для обогащения {posting_number}"
        log_user_event(user.id, error_msg, "error")
        return {"status": "error", "message": error_msg}
    
    # Запрос к Ozon API
    try:
        log_user_event(user.id, f"Запрос деталей постинга {posting_number} из Ozon API")
        response = await ozon_fbo_get_async(client_id, api_key, posting_number)
        data = response.get("result")
    except Exception as e:
        error_msg = f"Ошибка Ozon API при обогащении {posting_number}: {e}"
        log_user_event(user.id, error_msg, "error")
        return {"status": "api_error", "detail": str(e)}

    if not data:
        log_user_event(user.id, f"Ozon API не вернул данные для {posting_number}", "warning")
        return {"status": "no_result"}
    
    order_number = data.get("order_number")

    # Обновляем или создаем OrderPosting
    op = db.query(OrderPosting).filter(
        OrderPosting.posting_number == posting_number,
        OrderPosting.user_id == user.id
    ).first()
    
    if not op:
        op = OrderPosting(posting_number=posting_number, user_id=user.id)
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
    
    # Удаляем старые товары только этого пользователя и этого постинга
    db.query(OrderProduct).filter(
        OrderProduct.posting_number == posting_number,
        OrderProduct.user_id == user.id
    ).delete()
    
    products_data = data.get("products", [])
    fin_products = (data.get("financial_data") or {}).get("products") or []
    
    # Маппинг финансовых данных для быстрого поиска
    fin_map = {}
    for f in fin_products:
        if f.get("product_id"):
            fin_map[str(f.get("product_id"))] = f
        if f.get("sku"):
            fin_map[str(f.get("sku"))] = f
        if f.get("offer_id"):
            fin_map[str(f.get("offer_id"))] = f

    for pr in products_data:
        sku = pr.get("sku")
        offer_id = pr.get("offer_id")

        # Ищем фин. данные
        f = fin_map.get(str(sku)) or fin_map.get(str(offer_id))

        obj = OrderProduct(
            user_id=user.id,
            posting_number=posting_number,
            sku=_to_int(sku),
            offer_id=str(offer_id) if offer_id is not None else None,
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
        recalc_order_header(db, order_number, user.id)

    log_user_event(user.id, f"Постинг {posting_number} успешно обогащен ({len(products_data)} товаров)")
    return {
        "status": "ok",
        "order_number": order_number,
        "posting_number": posting_number,
        "products_count": len(products_data)
    }
