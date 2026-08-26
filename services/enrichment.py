import os
import logging
from services.ozon import ozon_fbo_get_async, ozon_fbs_get_async, ozon_product_info_list_async, ozon_accruals_by_day_async
from sqlalchemy.orm import Session
from db.database import OrderHeader, OrderPosting, Order, OrderProduct, User, OzonCredential, OzonAccrual
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
            dt_created = p.created_at # Это уже объект datetime после изменения типа колонки
            if dt_created:
                first_created = min(first_created, dt_created) if first_created else dt_created

        if p.fact_delivery_date:
            dt_delivery = p.fact_delivery_date
            if dt_delivery:
                last_delivery = max(last_delivery, dt_delivery) if last_delivery else dt_delivery

    hdr = db.query(OrderHeader).filter(OrderHeader.order_number == order_number, OrderHeader.user_id == user_id).first()
    if not hdr:
        # Проверяем также объекты, которые уже в сессии, но еще не в базе
        for obj in db.new:
            if isinstance(obj, OrderHeader) and obj.order_number == order_number and obj.user_id == user_id:
                hdr = obj
                break

        if not hdr:
            hdr = OrderHeader(order_number=order_number, user_id=user_id)
            db.add(hdr)
            db.flush() # Сразу отправляем в БД, чтобы избежать UniqueViolation при следующих вызовах

    hdr.first_created_at = first_created
    hdr.last_delivery_at = last_delivery
    hdr.total_payout = total_payout
    hdr.total_commission = total_commission

async def enrich_posting_from_ozon(
    posting_number: str,
    user_id: int,
    db: Session,
    client_id: str = None,
    api_key: str = None,
    scheme: str = None
):
    """
    Обогащает данные постинга (FBO или FBS) детальной информацией о товарах и финансах.
    """
    # 1. Определяем схему, если она не передана
    if not scheme:
        # Fallback: ищем схему в таблице Order (она там точно есть, так как создается первой)
        o_existing = db.query(Order.scheme).filter(
            Order.posting_number == posting_number,
            Order.user_id == user_id
        ).first()
        scheme = o_existing[0] if o_existing else 'fbo'

    # 2. Получаем ключи
    if not client_id or not api_key:
        active_cred = db.query(OzonCredential).filter(OzonCredential.user_id == user_id, OzonCredential.is_active == True).first()
        if not active_cred: return {"status": "no_credentials"}
        client_id = decrypt_credential(active_cred.client_id_encrypted)
        api_key = decrypt_credential(active_cred.api_key_encrypted)

    try:
        if scheme == 'fbo':
            response = await ozon_fbo_get_async(client_id, api_key, posting_number)
        else:
            response = await ozon_fbs_get_async(client_id, api_key, posting_number)

        if not isinstance(response, dict):
            return {"status": "api_error", "detail": "Unexpected response format"}

        data = response.get("result")
        if not isinstance(data, dict):
            return {"status": "no_result"}

    except Exception as e:
        logger.error(f"Error fetching {scheme} posting {posting_number}: {e}")
        return {"status": "api_error", "detail": str(e)}

    order_number = data.get("order_number")
    
    # 3. Обновляем OrderPosting
    op = db.query(OrderPosting).filter(
        OrderPosting.posting_number == posting_number, 
        OrderPosting.user_id == user_id
    ).with_for_update().first()
    
    if not op:
        try:
            with db.begin_nested():
                op = OrderPosting(posting_number=posting_number, user_id=user_id, scheme=scheme)
                db.add(op)
                db.flush()
        except Exception:
            db.rollback()
            op = db.query(OrderPosting).filter(OrderPosting.posting_number == posting_number, OrderPosting.user_id == user_id).first()
    
    if not op: return {"status": "error", "detail": "Could not create/find OrderPosting"}

    op.order_number = order_number
    op.status = data.get("status")
    op.substatus = data.get("substatus")
    op.scheme = scheme # Гарантируем актуальность схемы

    def to_dt(raw):
        dt = parse_ozon_datetime(raw)
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt else None

    op.created_at = to_dt(data.get("created_at"))
    op.in_process_at = to_dt(data.get("in_process_at"))
    # v3/posting/fbs/get (и v3-лист) не возвращают created_at —
    # используем in_process_at как фоллбэк, чтобы заказ не выпадал из сортировок/фильтров по дате
    if op.created_at is None:
        op.created_at = op.in_process_at
    op.fact_delivery_date = to_dt(data.get("fact_delivery_date"))

    # Специфичные поля FBS
    if scheme != 'fbo':
        op.shipment_date = to_dt(data.get("shipment_date"))
        op.is_express = data.get("is_express", False)
        dm = data.get("delivery_method") or {}
        op.delivery_method_id = dm.get("id")
        op.delivery_method_name = dm.get("name")
        op.tpl_provider = dm.get("tpl_provider")
        op.tracking_number = data.get("tracking_number")

    op.financial_data = data.get("financial_data")
    op.analytics_data = data.get("analytics_data")

    # 4. Обновляем товары
    db.query(OrderProduct).filter(OrderProduct.posting_number == posting_number, OrderProduct.user_id == user_id).delete()
    
    products_data = data.get("products", [])
    fin_data = data.get("financial_data") or {}
    
    # У FBS структура financial_data может отличаться, но в v2/get она обычно совпадает с FBO
    fin_products = fin_data.get("products", []) if isinstance(fin_data, dict) else []
    fin_map = {str(f.get("sku") or f.get("product_id") or ""): f for f in fin_products if isinstance(f, dict)}

    skus = [_to_int(pr.get("sku")) for pr in products_data if isinstance(pr, dict) and pr.get("sku")]
    image_map = {}
    if skus:
        try:
            prod_info = await ozon_product_info_list_async(client_id, api_key, skus)
            items = prod_info.get("items") or prod_info.get("result", {}).get("items") or []
            for item in items:
                raw_img = item.get("primary_image") or (item.get("images", [])[0] if item.get("images") else None)
                img_url = raw_img[0] if isinstance(raw_img, list) and raw_img else raw_img
                if img_url:
                    if isinstance(img_url, str) and img_url.startswith("//"): img_url = "https:" + img_url
                    image_map[str(item.get("sku"))] = img_url
        except Exception as e:
            logger.error(f"Error fetching images: {e}")

    new_products = []
    for pr in products_data:
        if not isinstance(pr, dict): continue
        sku = pr.get("sku")
        f = fin_map.get(str(sku))

        price = _to_int(f.get("price")) if f and f.get("price") is not None else _to_int(pr.get("price"))
        
        new_products.append(OrderProduct(
            user_id=user_id, posting_number=posting_number, sku=_to_int(sku),
            offer_id=pr.get("offer_id"), name=pr.get("name"),
            quantity=_to_int(pr.get("quantity")), price=price,
            currency_code=pr.get("currency_code"),
            commission_amount=_to_int((f or {}).get("commission_amount")),
            payout=_to_int((f or {}).get("payout")),
            image_url=image_map.get(str(sku))
        ))
    
    # ВАЖНО: добавляем товары в сессию — без этого они собираются в список,
    # но не сохраняются (баг: заказ появлялся без товаров, отчёт по выручке пустал)
    if new_products: db.add_all(new_products)

    if order_number: recalc_order_header(db, order_number, user_id)

    return {"status": "ok"}


async def enrich_accruals_from_ozon(
    user_id: int,
    date_str: str,
    db: Session
):
    """
    Получает все транзакции за день через /v1/finance/accrual/by-day
    и сохраняет их в базу, связывая с заказами.
    """
    active_cred = db.query(OzonCredential).filter(OzonCredential.user_id == user_id, OzonCredential.is_active == True).first()
    if not active_cred:
        return {"status": "no_credentials"}

    client_id = decrypt_credential(active_cred.client_id_encrypted)
    api_key = decrypt_credential(active_cred.api_key_encrypted)

    acc_date = datetime.strptime(date_str, "%Y-%m-%d")

    # Удаляем ВСЕ старые записи за эту дату (в рамках одной транзакции с новыми данными)
    db.query(OzonAccrual).filter(
        OzonAccrual.user_id == user_id,
        OzonAccrual.date == acc_date
    ).delete(synchronize_session=False)

    last_id = ""
    total_accruals = 0  # Кол-во top-level транзакций от Ozon
    total_rows = 0      # Кол-во распакованных строк в БД
    posting_cache = {}

    while True:
        try:
            response = await ozon_accruals_by_day_async(client_id, api_key, date_str, last_id)
            accruals = response.get("accruals") or []

            # Если на первой странице пусто и нет last_id - значит данных за день нет
            if not accruals and not last_id:
                db.rollback() # Откатываем предварительный DELETE, чтобы сохранить старые данные
                logger.warning(f"Ozon API вернул пустой ответ для {acc_date}. Данные не удалены.")
                break

            if not accruals and last_id:
                # Редкий случай: пустая страница с указателем на следующую
                last_id = response.get("last_id")
                continue

            # Оптимизация N+1: Предварительная загрузка OrderPosting.id и scheme для всей пачки
            unit_numbers = {acc.get("unit_number") for acc in accruals if acc.get("unit_number")}
            if unit_numbers:
                # Ищем только те, которых еще нет в кеше
                missing_units = [u for u in unit_numbers if u not in posting_cache]
                if missing_units:
                    for u in missing_units:
                        posting_cache[u] = (None, 'fbo')

                    found_ops = db.query(OrderPosting.posting_number, OrderPosting.id, OrderPosting.scheme).filter(
                        OrderPosting.user_id == user_id,
                        OrderPosting.posting_number.in_(missing_units)
                    ).all()
                    for pn, op_id, op_scheme in found_ops:
                        posting_cache[pn] = (op_id, op_scheme)

            all_rows_to_add = []
            for acc in accruals:
                acc_id = acc.get("accrual_id")
                unit_number = acc.get("unit_number")
                category = acc.get("accrued_category")

                p_id, p_scheme = posting_cache.get(unit_number, (None, 'fbo')) if unit_number else (None, 'fbo')

                amount_data = acc.get("total_amount") or {}
                currency = amount_data.get("currency")

                rows_to_add = []
                
                # ... (inner logic same) ...

                if category == "POSTING" and acc.get("posting"):
                    p_data = acc["posting"]
                    for prod in p_data.get("products", []):
                        sku = prod.get("sku")
                        qty = int(prod.get("quantity") or 1)
                        comm = prod.get("commission") or {}
                        
                        # 1. ВЫРУЧКА (Может быть отрицательной при возврате)
                        rev_amount = float((comm.get("sale_amount") or {}).get("amount") or 0)
                        if rev_amount != 0:
                            rows_to_add.append(OzonAccrual(
                                ozon_accrual_id=acc_id, user_id=user_id, date=acc_date,
                                unit_number=unit_number, accrued_category=category,
                                operation_type='revenue' if rev_amount > 0 else 'expense', 
                                amount=round(rev_amount * qty, 2), currency=currency,
                                quantity=qty, sku=sku, posting_id=p_id, scheme=p_scheme
                            ))

                        # 2. КОМИССИЯ (Специальный ID 1000. Отрицательная - расход, Положительная - возврат денег)
                        comm_amount = float((comm.get("commission") or {}).get("amount") or 0)
                        if comm_amount != 0:
                            rows_to_add.append(OzonAccrual(
                                ozon_accrual_id=acc_id, user_id=user_id, date=acc_date,
                                unit_number=unit_number, accrued_category=category,
                                operation_type='expense', # Комиссия всегда относится к расходам (даже если она с плюсом)
                                amount=round(comm_amount * qty, 2), currency=currency,
                                quantity=qty, type_id=1000, sku=sku, posting_id=p_id, scheme=p_scheme
                            ))

                        # 3. ДОСТАВКА И СЕРВИСЫ
                        deliv = prod.get("delivery") or {}
                        for srv in deliv.get("services", []):
                            srv_amount = float((srv.get("accrued") or {}).get("amount") or 0)
                            if srv_amount != 0:
                                rows_to_add.append(OzonAccrual(
                                    ozon_accrual_id=acc_id, user_id=user_id, date=acc_date,
                                    unit_number=unit_number, accrued_category=category,
                                    operation_type='expense', 
                                    amount=round(srv_amount * qty, 2), currency=currency,
                                    quantity=qty, type_id=srv.get("type_id"), sku=sku, posting_id=p_id, scheme=p_scheme
                                ))
                else:
                    # ДЛЯ ITEM и NON_ITEM: Собираем ВСЕ услуги (исправлено)
                    if category == "ITEM":
                        item_fees = acc.get("item_fees") or {}
                        for fee_item in (item_fees.get("fees") or []):
                            sku = fee_item.get("sku")
                            for srv in (fee_item.get("fees") or []):
                                amt = round(float((srv.get("accrued") or {}).get("amount") or 0), 2)
                                if amt != 0:
                                    rows_to_add.append(OzonAccrual(
                                        ozon_accrual_id=acc_id, user_id=user_id, date=acc_date,
                                        unit_number=unit_number, accrued_category=category,
                                        operation_type='revenue' if amt > 0 else 'expense',
                                        amount=amt, currency=currency,
                                        type_id=srv.get("type_id"), sku=sku, posting_id=p_id, scheme=p_scheme
                                    ))
                    elif category == "NON_ITEM":
                        ni_fee = acc.get("non_item_fee") or {}
                        amt = round(float(amount_data.get("amount") or 0), 2)
                        if amt != 0:
                            rows_to_add.append(OzonAccrual(
                                ozon_accrual_id=acc_id, user_id=user_id, date=acc_date,
                                unit_number=unit_number, accrued_category=category,
                                operation_type='revenue' if amt > 0 else 'expense',
                                amount=amt, currency=currency,
                                type_id=ni_fee.get("type_id"), posting_id=p_id, scheme=p_scheme
                            ))
                    else:
                        # Фоллбек для неизвестных категорий
                        amt = round(float(amount_data.get("amount") or 0), 2)
                        if amt != 0:
                            rows_to_add.append(OzonAccrual(
                                ozon_accrual_id=acc_id, user_id=user_id, date=acc_date,
                                unit_number=unit_number, accrued_category=category,
                                operation_type='revenue' if amt > 0 else 'expense',
                                amount=amt, currency=currency, posting_id=p_id, scheme=p_scheme
                            ))

                all_rows_to_add.extend(rows_to_add)
                total_accruals += 1
                total_rows += len(rows_to_add)

            if all_rows_to_add:
                db.add_all(all_rows_to_add)

            db.commit()
            last_id = response.get("last_id")
            if not last_id:
                break

        except Exception as e:
            logger.error(f"Error enriching accruals for user {user_id} date {date_str}: {e}")
            db.rollback()
            return {"status": "error", "detail": "Ошибка при синхронизации транзакций Ozon"}

    logger.info(f"User {user_id}: синхронизировано {total_accruals} accruals ({total_rows} строк) за {date_str}")
    return {"status": "ok", "synced": total_accruals, "rows": total_rows}
