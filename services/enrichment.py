import os
import logging
from services.ozon import ozon_fbo_get_async, ozon_product_info_list_async, ozon_accruals_by_day_async
from sqlalchemy.orm import Session
from db.database import OrderHeader, OrderPosting, OrderProduct, User, OzonCredential, OzonAccrual
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
    
    # Пытаемся найти существующий или создаем новый максимально безопасно
    op = db.query(OrderPosting).filter(
        OrderPosting.posting_number == posting_number, 
        OrderPosting.user_id == user_id
    ).with_for_update().first() # Блокируем строку для обновления
    
    if not op:
        # Если заказа все еще нет, создаем его
        # Используем flush и вложенную транзакцию для обработки гонки
        try:
            with db.begin_nested():
                op = OrderPosting(posting_number=posting_number, user_id=user_id)
                db.add(op)
                db.flush()
        except Exception:
            # Если кто-то успел вставить параллельно, просто берем его
            db.rollback()
            op = db.query(OrderPosting).filter(
                OrderPosting.posting_number == posting_number, 
                OrderPosting.user_id == user_id
            ).first()
    
    if not op:
        return {"status": "error", "detail": "Could not create or find OrderPosting"}

    op.order_number = order_number
    op.status = data.get("status")
    op.substatus = data.get("substatus")

    # Конвертация дат в объекты datetime для БД
    def to_dt(raw):
        dt = parse_ozon_datetime(raw)
        if dt:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return None

    op.created_at = to_dt(data.get("created_at"))
    op.in_process_at = to_dt(data.get("in_process_at"))
    op.fact_delivery_date = to_dt(data.get("fact_delivery_date"))

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

    # --- ПОЛУЧЕНИЕ ИЗОБРАЖЕНИЙ ТОВАРОВ ---
    skus = []
    for pr in products_data:
        if isinstance(pr, dict) and pr.get("sku"):
            skus.append(_to_int(pr.get("sku")))

    image_map = {}
    if skus:
        try:
            prod_info = await ozon_product_info_list_async(client_id, api_key, skus)

            # В API v3 список товаров обычно лежит прямо в корне в 'items'
            # Проверяем оба варианта (корень и внутри 'result') для максимальной совместимости
            items = prod_info.get("items")
            if items is None and isinstance(prod_info.get("result"), dict):
                items = prod_info.get("result", {}).get("items")

            if not isinstance(items, list):
                items = []

            for item in items:
                s_id = item.get("sku")
                # ПРИОРИТЕТ: сначала ищем главную картинку (primary_image),
                # если её нет — берем первую из списка images
                raw_img = item.get("primary_image") or (item.get("images", [])[0] if item.get("images") else None)

                # Озон может вернуть ссылку как строку или как список из одной строки.
                # Нам нужна именно строка.
                img_url = None
                if isinstance(raw_img, list) and raw_img:
                    img_url = raw_img[0]
                elif isinstance(raw_img, str):
                    img_url = raw_img

                if img_url:
                    # Санитарная проверка: Ozon иногда возвращает // вместо https://
                    if isinstance(img_url, str) and img_url.startswith("//"):
                        img_url = "https:" + img_url
                    image_map[str(s_id)] = img_url

            if image_map:
                logger.debug(f"User {user_id}: Успешно получено {len(image_map)} изображений для SKU.")
        except Exception as e:
            logger.error(f"User {user_id}: Критическая ошибка при получении изображений Ozon: {e}")

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
            image_url=image_map.get(str(sku))
        )
        db.add(obj)
    
    if order_number:
        recalc_order_header(db, order_number, user_id)

    # Больше НЕ делаем здесь db.commit(), это ответственность вызывающего кода
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

    # Удаляем ВСЕ старые записи за эту дату одним запросом (защита от дублей)
    deleted_count = db.query(OzonAccrual).filter(
        OzonAccrual.user_id == user_id,
        OzonAccrual.date == acc_date
    ).delete(synchronize_session=False)
    if deleted_count > 0:
        logger.info(f"User {user_id}: удалено {deleted_count} старых accruals за {date_str}")
    db.commit()

    last_id = ""
    total_accruals = 0  # Кол-во top-level транзакций от Ozon
    total_rows = 0      # Кол-во распакованных строк в БД
    posting_cache = {}

    while True:
        try:
            response = await ozon_accruals_by_day_async(client_id, api_key, date_str, last_id)
            accruals = response.get("accruals") or []

            if not accruals:
                break

            for acc in accruals:
                acc_id = acc.get("accrual_id")
                unit_number = acc.get("unit_number")
                category = acc.get("accrued_category")

                p_id = None
                if unit_number:
                    if unit_number in posting_cache:
                        p_id = posting_cache[unit_number]
                    else:
                        op = db.query(OrderPosting.id).filter(
                            OrderPosting.posting_number == unit_number,
                            OrderPosting.user_id == user_id
                        ).first()
                        if op:
                            p_id = op.id
                            posting_cache[unit_number] = p_id

                amount_data = acc.get("total_amount") or {}
                currency = amount_data.get("currency")

                rows_to_add = []

                if category == "POSTING" and acc.get("posting"):
                    p_data = acc["posting"]
                    for prod in p_data.get("products", []):
                        sku = prod.get("sku")
                        comm = prod.get("commission") or {}
                        
                        # 1. ДОХОД
                        rev_amount = round(float((comm.get("sale_amount") or {}).get("amount") or 0), 2)
                        if rev_amount > 0:
                            rows_to_add.append(OzonAccrual(
                                ozon_accrual_id=acc_id, user_id=user_id, date=acc_date,
                                unit_number=unit_number, accrued_category=category,
                                operation_type='revenue', amount=rev_amount, currency=currency,
                                sku=sku, posting_id=p_id
                            ))

                        # 2. КОМИССИЯ (Специальный ID 1000 для Комиссии)
                        comm_amount = round(float((comm.get("commission") or {}).get("amount") or 0), 2)
                        if comm_amount != 0:
                            rows_to_add.append(OzonAccrual(
                                ozon_accrual_id=acc_id, user_id=user_id, date=acc_date,
                                unit_number=unit_number, accrued_category=category,
                                operation_type='expense' if comm_amount < 0 else 'revenue', 
                                amount=comm_amount, currency=currency,
                                type_id=1000, sku=sku, posting_id=p_id
                            ))

                        # 3. ДОСТАВКА И СЕРВИСЫ
                        deliv = prod.get("delivery") or {}
                        for srv in deliv.get("services", []):
                            srv_amount = round(float((srv.get("accrued") or {}).get("amount") or 0), 2)
                            if srv_amount != 0:
                                rows_to_add.append(OzonAccrual(
                                    ozon_accrual_id=acc_id, user_id=user_id, date=acc_date,
                                    unit_number=unit_number, accrued_category=category,
                                    operation_type='expense' if srv_amount < 0 else 'revenue', 
                                    amount=srv_amount, currency=currency,
                                    type_id=srv.get("type_id"), sku=sku, posting_id=p_id
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
                                        type_id=srv.get("type_id"), sku=sku, posting_id=p_id
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
                                type_id=ni_fee.get("type_id"), posting_id=p_id
                            ))
                    else:
                        # Фоллбек для неизвестных категорий
                        amt = round(float(amount_data.get("amount") or 0), 2)
                        if amt != 0:
                            rows_to_add.append(OzonAccrual(
                                ozon_accrual_id=acc_id, user_id=user_id, date=acc_date,
                                unit_number=unit_number, accrued_category=category,
                                operation_type='revenue' if amt > 0 else 'expense',
                                amount=amt, currency=currency, posting_id=p_id
                            ))

                for row in rows_to_add:
                    db.add(row)
                total_accruals += 1
                total_rows += len(rows_to_add)

            db.commit()
            last_id = response.get("last_id")
            if not last_id:
                break

        except Exception as e:
            logger.error(f"Error enriching accruals for user {user_id} date {date_str}: {e}")
            db.rollback()
            return {"status": "error", "detail": str(e)}

    logger.info(f"User {user_id}: синхронизировано {total_accruals} accruals ({total_rows} строк) за {date_str}")
    return {"status": "ok", "synced": total_accruals, "rows": total_rows}
