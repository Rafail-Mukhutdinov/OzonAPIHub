"""
Модуль обогащения и пересчета данных.
Отвечает за получение детальной информации о товарах из заказов, пересчет агрегатов в OrderHeader 
и разбор сложных финансовых начислений Ozon по отдельным статьям (комиссия, логистика, выручка).
"""

import os
import logging
from services.ozon import ozon_fbo_get_async, ozon_fbs_get_async, ozon_product_info_list_async, ozon_accruals_by_day_async
from sqlalchemy.orm import Session
from db.database import OrderHeader, OrderPosting, Order, OrderProduct, User, OzonCredential, OzonAccrual
from utils.encryption import decrypt_credential
from datetime import datetime, timezone
from utils.logging_config import log_user_event
from utils.common import parse_ozon_datetime, to_msk

# Настройка логирования
logger = logging.getLogger("OzonAPIHub")

def _to_int(val):
    """
    Экстремально надежное преобразование в целое число.
    Обрабатывает None, строки с запятыми, пробелами и дробные числа (округляет).

    Args:
        val: Значение для преобразования.

    Returns:
        int: Целочисленное значение (0 при ошибке).
    """
    if val is None: return 0
    try:
        if isinstance(val, (int, float)): return int(round(float(val)))
        # Убираем пробелы, меняем запятую на точку для корректного float()
        cleaned = str(val).replace(',', '.').replace(' ', '').strip()
        if not cleaned: return 0
        return int(round(float(cleaned)))
    except Exception as e:
        logger.error(f"Ошибка парсинга цены/количества ({val}): {e}")
        return 0

def recalc_order_header(db: Session, order_number: str, user_id: int):
    """
    Пересчитывает суммарные показатели в таблице OrderHeader на основе всех товаров (OrderProduct),
    входящих в состав этого заказа (может состоять из нескольких постингов).
    Вычисляет общую выплату, комиссию, первую дату создания и последнюю дату доставки.

    Args:
        db (Session): Сессия БД.
        order_number (str): Номер заказа Ozon.
        user_id (int): ID пользователя.
    """
    # ВАЖНО: сбрасываем изменения сессии в БД, чтобы OrderProduct были доступны для SQL-запроса
    db.flush()

    # Собираем все товары для этого заказа
    products = db.query(OrderProduct).join(
        OrderPosting,
        (OrderPosting.posting_number == OrderProduct.posting_number) & (OrderPosting.user_id == OrderProduct.user_id)
    ).filter(OrderPosting.order_number == order_number, OrderPosting.user_id == user_id).all()

    # Суммируем финансовые показатели
    total_payout = sum((p.payout or 0) for p in products)
    total_commission = sum((p.commission_amount or 0) for p in products)

    # Собираем даты из всех отправлений заказа
    postings = db.query(OrderPosting).filter(OrderPosting.order_number == order_number, OrderPosting.user_id == user_id).all()
    first_created = None
    last_delivery = None

    for p in postings:
        if p.created_at:
            dt_created = p.created_at
            if dt_created:
                # Находим самую раннюю дату создания
                first_created = min(first_created, dt_created) if first_created else dt_created

        if p.fact_delivery_date:
            dt_delivery = p.fact_delivery_date
            if dt_delivery:
                # Находим самую позднюю дату доставки
                last_delivery = max(last_delivery, dt_delivery) if last_delivery else dt_delivery

    # Пытаемся найти существующий заголовок заказа
    hdr = db.query(OrderHeader).filter(OrderHeader.order_number == order_number, OrderHeader.user_id == user_id).first()
    if not hdr:
        # Проверяем объекты, которые уже созданы в текущей сессии, но еще не в БД
        for obj in db.new:
            if isinstance(obj, OrderHeader) and obj.order_number == order_number and obj.user_id == user_id:
                hdr = obj
                break

        if not hdr:
            # Создаем новый заголовок, если его нет
            hdr = OrderHeader(order_number=order_number, user_id=user_id)
            db.add(hdr)
            db.flush() # Сразу сохраняем для избежания проблем с уникальностью

    # Обновляем поля заголовка
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
    Обогащает данные отправления (постинга) детальной информацией из Ozon API.
    Загружает список товаров, их цены, комиссии, изображения и расширенную логистику.

    Args:
        posting_number (str): Номер отправления.
        user_id (int): ID владельца данных.
        db (Session): Сессия БД.
        client_id (str): API Client-Id (опционально).
        api_key (str): API-Key (опционально).
        scheme (str): Схема работы fbo/fbs (опционально, определяется автоматически).

    Returns:
        dict: Статус операции (ok, error, api_error и т.д.).
    """
    # 1. Автоматически определяем схему, если она не передана
    if not scheme:
        o_existing = db.query(Order.scheme).filter(
            Order.posting_number == posting_number,
            Order.user_id == user_id
        ).first()
        scheme = o_existing[0] if o_existing else 'fbo'

    # 2. Получаем API-ключи, если они не переданы напрямую
    if not client_id or not api_key:
        active_cred = db.query(OzonCredential).filter(OzonCredential.user_id == user_id, OzonCredential.is_active == True).first()
        if not active_cred: return {"status": "no_credentials"}
        client_id = decrypt_credential(active_cred.client_id_encrypted)
        api_key = decrypt_credential(active_cred.api_key_encrypted)

    try:
        # Запрашиваем детали у Ozon API в зависимости от схемы
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
    
    # 3. Находим или создаем запись в OrderPosting (используем блокировку для безопасного обновления)
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

    # Обновляем базовые поля
    op.order_number = order_number
    op.status = data.get("status")
    op.substatus = data.get("substatus")
    op.scheme = scheme

    # Функция для безопасного парсинга дат Ozon
    def to_dt(raw):
        dt = parse_ozon_datetime(raw)
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt else None

    op.created_at = to_dt(data.get("created_at"))
    op.in_process_at = to_dt(data.get("in_process_at"))
    # У FBS v3 может не быть created_at, используем in_process_at как фоллбэк
    if op.created_at is None:
        op.created_at = op.in_process_at
    op.fact_delivery_date = to_dt(data.get("fact_delivery_date"))

    # Обработка специфичных полей для FBS (доставка, курьер)
    if scheme != 'fbo':
        op.shipment_date = to_dt(data.get("shipment_date"))
        op.is_express = data.get("is_express", False)
        dm = data.get("delivery_method") or {}
        op.delivery_method_id = dm.get("id")
        op.delivery_method_name = dm.get("name")
        op.tpl_provider = dm.get("tpl_provider")
        op.tracking_number = data.get("tracking_number")

    op.financial_data = data.get("financial_data") # Храним сырой JSON на всякий случай
    op.analytics_data = data.get("analytics_data")

    # 4. Обновляем товары внутри отправления
    # Сначала удаляем старые записи о товарах (синхронизация "начисто")
    db.query(OrderProduct).filter(OrderProduct.posting_number == posting_number, OrderProduct.user_id == user_id).delete()
    
    products_data = data.get("products", [])
    fin_data = data.get("financial_data") or {}
    
    # Создаем карту SKU -> Финансовые данные для быстрого сопоставления цен и комиссий
    fin_products = fin_data.get("products", []) if isinstance(fin_data, dict) else []
    fin_map = {str(f.get("sku") or f.get("product_id") or ""): f for f in fin_products if isinstance(f, dict)}

    # Собираем изображения товаров через отдельный метод API Ozon
    skus = [_to_int(pr.get("sku")) for pr in products_data if isinstance(pr, dict) and pr.get("sku")]
    image_map = {}
    if skus:
        try:
            prod_info = await ozon_product_info_list_async(client_id, api_key, skus)
            # Извлекаем ссылки на картинки из разных возможных мест в ответе v3
            items = prod_info.get("items") or prod_info.get("result", {}).get("items") or []
            for item in items:
                raw_img = item.get("primary_image") or (item.get("images", [])[0] if item.get("images") else None)
                img_url = raw_img[0] if isinstance(raw_img, list) and raw_img else raw_img
                if img_url:
                    if isinstance(img_url, str) and img_url.startswith("//"): img_url = "https:" + img_url
                    image_map[str(item.get("sku"))] = img_url
        except Exception as e:
            logger.error(f"Error fetching images: {e}")

    # Создаем объекты товаров
    new_products = []
    for pr in products_data:
        if not isinstance(pr, dict): continue
        sku = pr.get("sku")
        f = fin_map.get(str(sku))

        # Берем цену либо из финансовых данных (более точно), либо из основного списка товаров
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
    
    if new_products: 
        db.add_all(new_products)

    # Запускаем пересчет заголовка заказа после изменения товаров
    if order_number: 
        recalc_order_header(db, order_number, user_id)

    return {"status": "ok"}


async def enrich_accruals_from_ozon(
    user_id: int,
    date_str: str,
    db: Session
):
    """
    Загружает и распаковывает финансовые начисления за конкретный день из /v1/finance/accrual/by-day.
    Этот метод разбирает каждую транзакцию Ozon на составные части: выручка от продажи, 
    комиссия площадки, услуги логистики и т.д. для 100% точности финансового учета.

    Args:
        user_id (int): ID пользователя.
        date_str (str): Дата (ГГГГ-ММ-ДД).
        db (Session): Сессия БД.

    Returns:
        dict: Результат синхронизации и статистика по количеству строк.
    """
    # Получаем API-ключи
    active_cred = db.query(OzonCredential).filter(OzonCredential.user_id == user_id, OzonCredential.is_active == True).first()
    if not active_cred:
        return {"status": "no_credentials"}

    client_id = decrypt_credential(active_cred.client_id_encrypted)
    api_key = decrypt_credential(active_cred.api_key_encrypted)

    acc_date = datetime.strptime(date_str, "%Y-%m-%d")

    # ВАЖНО: Удаляем старые записи за эту дату перед загрузкой новых (синхронизация "начисто")
    db.query(OzonAccrual).filter(
        OzonAccrual.user_id == user_id,
        OzonAccrual.date == acc_date
    ).delete(synchronize_session=False)

    last_id = "" # Курсор для пагинации Ozon
    total_accruals = 0  # Счётчик верхнеуровневых транзакций Ozon
    total_rows = 0      # Счётчик созданных строк в нашей БД
    posting_cache = {} # Кеш для оптимизации поиска ID постингов

    while True:
        try:
            # Запрос к API
            response = await ozon_accruals_by_day_async(client_id, api_key, date_str, last_id)
            accruals = response.get("accruals") or []

            # Если данных за день нет вообще (пустой ответ на 1 странице)
            if not accruals and not last_id:
                db.rollback() # Откатываем DELETE, чтобы не терять данные, если API глючит
                logger.warning(f"Ozon API вернул пустой ответ для {acc_date}. Данные не удалены.")
                break

            if not accruals and last_id:
                # Пагинация продолжается
                last_id = response.get("last_id")
                continue

            # Оптимизация N+1: Предварительно находим все постинги из пачки в нашей БД
            unit_numbers = {acc.get("unit_number") for acc in accruals if acc.get("unit_number")}
            if unit_numbers:
                missing_units = [u for u in unit_numbers if u not in posting_cache]
                if missing_units:
                    for u in missing_units:
                        posting_cache[u] = (None, 'fbo') # По умолчанию

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
                category = acc.get("accrued_category") # POSTING, ITEM, NON_ITEM

                # Получаем ID и схему из нашего кеша
                p_id, p_scheme = posting_cache.get(unit_number, (None, 'fbo')) if unit_number else (None, 'fbo')

                amount_data = acc.get("total_amount") or {}
                currency = amount_data.get("currency")

                rows_to_add = []
                
                # РАЗБОР КАТЕГОРИИ POSTING (Операции, привязанные к заказу)
                if category == "POSTING" and acc.get("posting"):
                    p_data = acc["posting"]
                    for prod in p_data.get("products", []):
                        sku = prod.get("sku")
                        qty = int(prod.get("quantity") or 1)
                        comm = prod.get("commission") or {}
                        
                        # 1. ЧИСТАЯ ВЫРУЧКА (Sale Amount)
                        rev_amount = float((comm.get("sale_amount") or {}).get("amount") or 0)
                        if rev_amount != 0:
                            rows_to_add.append(OzonAccrual(
                                ozon_accrual_id=acc_id, user_id=user_id, date=acc_date,
                                unit_number=unit_number, accrued_category=category,
                                operation_type='revenue' if rev_amount > 0 else 'expense', 
                                amount=round(rev_amount * qty, 2), currency=currency,
                                quantity=qty, sku=sku, posting_id=p_id, scheme=p_scheme
                            ))

                        # 2. КОМИССИЯ ПЛОЩАДКИ (Специальный внутренний ID 1000)
                        comm_amount = float((comm.get("commission") or {}).get("amount") or 0)
                        if comm_amount != 0:
                            rows_to_add.append(OzonAccrual(
                                ozon_accrual_id=acc_id, user_id=user_id, date=acc_date,
                                unit_number=unit_number, accrued_category=category,
                                operation_type='expense', 
                                amount=round(comm_amount * qty, 2), currency=currency,
                                quantity=qty, type_id=1000, sku=sku, posting_id=p_id, scheme=p_scheme
                            ))

                        # 3. ЛОГИСТИКА И ДОПОЛНИТЕЛЬНЫЕ СЕРВИСЫ
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
                    # РАЗБОР КАТЕГОРИЙ ITEM и NON_ITEM (Прочие услуги, возвраты, компенсации)
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
                        # Фоллбек для редких или новых категорий API Ozon
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

            # Сохраняем пачку данных текущей страницы
            if all_rows_to_add:
                db.add_all(all_rows_to_add)

            db.commit()
            last_id = response.get("last_id")
            if not last_id:
                break # Все страницы обработаны

        except Exception as e:
            logger.error(f"Error enriching accruals for user {user_id} date {date_str}: {e}")
            db.rollback()
            return {"status": "error", "detail": "Ошибка при синхронизации транзакций Ozon"}

    logger.info(f"User {user_id}: синхронизировано {total_accruals} accruals ({total_rows} строк) за {date_str}")
    return {"status": "ok", "synced": total_accruals, "rows": total_rows}
