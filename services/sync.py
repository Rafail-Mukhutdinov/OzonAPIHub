"""
Модуль синхронизации данных с Ozon API.
Оптимизирован для массовой обработки (бэкфилл) и инкрементальной синхронизации без перегрузки БД.
Управляет очередностью загрузки заказов, финансов и транзакций.
"""

import os
import logging
import asyncio
from typing import Union
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from db.database import User, Order, OrderPosting, OrderProduct, OzonCredential, SessionLocal, SyncStatus, Cost, OzonAccrual
from services.enrichment import enrich_posting_from_ozon, enrich_accruals_from_ozon
from services.ozon import ozon_fbo_list_async, ozon_fbs_list_async, ozon_transaction_list_async, ozon_accruals_by_day_async
from utils.encryption import decrypt_credential
from utils.common import valid_posting_number, to_msk, to_msk_date, parse_ozon_datetime, get_now_utc
from utils.logging_config import log_user_event

# Настройка логирования
logger = logging.getLogger("OzonAPIHub")

# Глобальные настройки синхронизации из переменных окружения
RECENT_WINDOW_HOURS = int(os.getenv('RECENT_WINDOW_HOURS', '24')) # Окно для регулярной проверки изменений
ENRICH_ON_FETCH = os.getenv('ENRICH_ON_FETCH', 'true').lower() in ('1', 'true', 'yes') # Автоматическое обогащение при загрузке
ENRICH_CONCURRENCY = int(os.getenv('ENRICH_CONCURRENCY', '2')) # Количество параллельных запросов на детализацию

def get_latest_order_datetime(db: Session, user_id: int, scheme: str = 'fbo') -> Union[datetime, None]:
    """
    Находит дату создания самого последнего заказа пользователя для конкретной схемы отгрузки.
    Используется для определения точки начала следующей инкрементальной синхронизации.

    Args:
        db (Session): Сессия БД.
        user_id (int): ID пользователя.
        scheme (str): Схема работы (fbo/fbs).

    Returns:
        datetime | None: Дата последнего заказа или None, если заказов нет.
    """
    # Ищем в таблице сырых заказов
    raw_max = db.query(func.max(Order.created_at)).filter(
        Order.user_id == user_id,
        Order.scheme == scheme
    ).scalar()

    # Ищем в таблице обработанных отправлений (для подстраховки)
    posting_max = db.query(func.max(OrderPosting.created_at)).filter(
        OrderPosting.user_id == user_id,
        OrderPosting.scheme == scheme
    ).scalar()

    values = [v for v in [raw_max, posting_max] if v is not None]
    return max(values) if values else None

def get_latest_accrual_date(db: Session, user_id: int) -> Union[datetime, None]:
    """
    Находит дату самого последнего загруженного начисления (accrual) пользователя.

    Args:
        db (Session): Сессия БД.
        user_id (int): ID пользователя.

    Returns:
        datetime | None: Максимальная дата начисления.
    """
    return db.query(func.max(OzonAccrual.date)).filter(
        OzonAccrual.user_id == user_id
    ).scalar()

def find_accrual_date_gaps(db: Session, user_id: int, lookback_days: int = 30) -> list[str]:
    """
    Находит даты за последние N дней, для которых в системе НЕТ финансовых записей (начислений).
    Позволяет точечно догружать пропущенные дни.

    Args:
        db (Session): Сессия БД.
        user_id (int): ID пользователя.
        lookback_days (int): Глубина проверки в днях.

    Returns:
        list[str]: Список строк с датами в формате ГГГГ-ММ-ДД.
    """
    now = get_now_utc()
    since = (now - timedelta(days=lookback_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Получаем уникальные даты, которые уже есть в БД
    existing_dates = db.query(OzonAccrual.date).filter(
        OzonAccrual.user_id == user_id,
        OzonAccrual.date >= since
    ).distinct().all()
    existing_date_set = {d[0].date() for d in existing_dates}
    
    gaps = []
    check = since.date()
    today = now.date()
    # Идем по календарю от 'since' до сегодня и проверяем наличие данных
    while check < today:
        if check not in existing_date_set:
            gaps.append(check.strftime("%Y-%m-%d"))
        check += timedelta(days=1)
    
    return gaps

async def sync_user_orders(user: User, db: Session) -> bool:
    """
    Запускает полный цикл регулярной синхронизации для одного пользователя.
    Включает в себя FBO заказы, FBS заказы, начисления и транзакции.

    Args:
        user (User): Объект пользователя.
        db (Session): Сессия БД.

    Returns:
        bool: True, если были найдены и сохранены новые/измененные данные.
    """
    try:
        # Проверяем наличие активных API-ключей
        active_cred = db.query(OzonCredential).filter(
            OzonCredential.user_id == user.id,
            OzonCredential.is_active == True
        ).first()
        
        if not active_cred: return False

        # --- 1. Синхронизация FBO (со склада Ozon) ---
        fbo_changed = await _sync_scheme_orders(user, db, active_cred, scheme='fbo')
        
        # --- 2. Синхронизация FBS (со склада продавца) ---
        fbs_changed = await _sync_scheme_orders(user, db, active_cred, scheme='fbs')

        # --- 3. Синхронизация финансов (начисления по дням и рекламные транзакции) ---
        await _sync_finances(user, db)

        return fbo_changed or fbs_changed
    except Exception as e:
        logger.error(f"User {user.id}: sync_user_orders error: {e}", exc_info=True)
        return False

async def _sync_scheme_orders(user: User, db: Session, cred: OzonCredential, scheme: str) -> bool:
    """
    Вспомогательный метод для инкрементальной синхронизации конкретной схемы (FBO или FBS).
    Запрашивает список изменений с момента последнего известного заказа.

    Args:
        user (User): Пользователь.
        db (Session): Сессия.
        cred (OzonCredential): Учетные данные Ozon.
        scheme (str): Схема ('fbo' или 'fbs').

    Returns:
        bool: Были ли изменения.
    """
    now = get_now_utc()
    last_dt = get_latest_order_datetime(db, user.id, scheme=scheme)
    
    # Определяем временное окно запроса
    if last_dt:
        # Перекрываем 12 часов, чтобы не пропустить статусы, изменившиеся "задним числом"
        since_dt = last_dt - timedelta(hours=12)
    else:
        # Если данных нет, берем за последние 30 дней
        since_dt = now - timedelta(days=30)

    # Валидация границ
    if since_dt >= now: since_dt = now - timedelta(seconds=10)
    
    # Лимиты Ozon API по глубине запроса списка
    max_days = 60 if scheme == 'fbo' else 14
    if since_dt < now - timedelta(days=max_days):
        since_dt = now - timedelta(days=max_days)

    # Подготовка строк ISO для API
    since_iso = since_dt.replace(microsecond=0).isoformat().split('+')[0] + 'Z'
    to_iso = now.replace(microsecond=0).isoformat().split('+')[0] + 'Z'

    # Расшифровка ключей для запроса
    client_id = decrypt_credential(cred.client_id_encrypted)
    api_key = decrypt_credential(cred.api_key_encrypted)

    total_saved, offset, limit = 0, 0, 50
    new_pns = set() # Список номеров отправлений для последующего обогащения

    while True:
        # Запрос списка постингов
        if scheme == 'fbo':
            data = await ozon_fbo_list_async(
                client_id=client_id, api_key=api_key,
                filter_dict={'since': since_iso, 'to': to_iso},
                limit=limit, offset=offset, sort_dir="DESC"
            )
        else:
            data = await ozon_fbs_list_async(
                client_id=client_id, api_key=api_key,
                filter_dict={'since': since_iso, 'to': to_iso},
                limit=limit, offset=offset, sort_dir="DESC"
            )

        if not isinstance(data, dict): break
        res_val = data.get("result")
        if isinstance(res_val, dict):
            items = res_val.get("postings", [])
        elif isinstance(res_val, list):
            items = res_val
        else:
            items = []

        if not items: break

        # Оптимизация: загружаем статусы существующих заказов одной пачкой
        fetched_pns = [o.get('posting_number') for o in items if o.get('posting_number')]
        existing_orders_map = {}
        if fetched_pns:
            existing_rows = db.query(Order.posting_number, Order.status).filter(
                Order.user_id == user.id, Order.posting_number.in_(fetched_pns)
            ).all()
            existing_orders_map = {r[0]: r[1] for r in existing_rows}

        # Проверяем, есть ли уже полные данные (enrichment) для этих номеров
        existing_norm_pns = set()
        if fetched_pns:
            norm_rows = db.query(OrderPosting.posting_number).filter(
                OrderPosting.user_id == user.id, OrderPosting.posting_number.in_(fetched_pns)
            ).all()
            existing_norm_pns = {r[0] for r in norm_rows}

        for o in items:
            pn = o.get('posting_number')
            try:
                # Используем sub-transaction для изоляции ошибок сохранения конкретного заказа
                with db.begin_nested():
                    current_existing_status = existing_orders_map.get(pn, "__NOT_FOUND__")
                    # Сохраняем/обновляем базовую информацию о заказе
                    is_active_change = save_order_for_user(db, user, o, existing_status=current_existing_status, scheme=scheme)

                    # Если статус изменился или данных о заказе еще нет в "чистой" таблице — помечаем на обогащение
                    if is_active_change or (pn not in existing_norm_pns):
                        total_saved += 1
                        if valid_posting_number(pn): 
                            new_pns.add(pn)
            except Exception as e:
                logger.error(f"User {user.id} ({scheme}): Error saving order {pn}: {e}")

        db.commit()
        if len(items) < limit: break # Выход, если дошли до конца списка
        offset += limit

    # Если нашли новые заказы, запускаем фоновое обогащение (детализация товаров и цен)
    if total_saved > 0:
        log_user_event(user.id, f"[{scheme.upper()}] Найдено новых/измененных заказов: {total_saved}. Запуск обогащения...")
        if ENRICH_ON_FETCH:
            await run_enrichment_batch(list(new_pns), user.id, scheme=scheme)
    
    # Обновляем метку времени последней синхронизации в SyncStatus
    status = db.query(SyncStatus).filter(SyncStatus.user_id == user.id).first()
    if status and scheme == 'fbs':
        status.fbs_last_sync_at = now
        db.commit()

    return total_saved > 0

async def _sync_finances(user: User, db: Session):
    """
    Синхронизация начислений (Accruals) и рекламных транзакций.
    Проверяет последние дни на наличие пропусков и догружает их.

    Args:
        user (User): Пользователь.
        db (Session): Сессия.
    """
    now = get_now_utc()
    last_acc_dt = get_latest_accrual_date(db, user.id)
    
    # Определяем глубину синхронизации
    if last_acc_dt:
        start_sync_dt = max(last_acc_dt - timedelta(days=2), now - timedelta(days=30))
    else:
        start_sync_dt = now - timedelta(days=7)

    days_to_sync = (now.date() - start_sync_dt.date()).days
    days_to_sync = max(days_to_sync, 4) # Минимум 4 дня для надежности

    # Ищем дыры в данных за последние 30 дней (например, если сервер лежал)
    all_gaps = find_accrual_date_gaps(db, user.id, lookback_days=30)
    window_dates = {(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_to_sync + 1)}
    gaps_to_fill = [g for g in all_gaps if g not in window_dates]

    # Заполняем сначала старые дыры (лимит 10 в один проход)
    for check_date in gaps_to_fill[:10]:
        await enrich_accruals_from_ozon(user.id, check_date, db)

    # Синхронизируем последние дни
    for i in range(days_to_sync + 1):
        check_date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        await enrich_accruals_from_ozon(user.id, check_date, db)

    # Отдельно тянем список транзакций (реклама, хранение)
    await sync_ozon_transactions(user.id, db, days_back=days_to_sync + 1)

def save_order_for_user(db: Session, user: User, order_data: dict, existing_status: str = "__FALLBACK__", scheme: str = "fbo") -> bool:
    """
    Сохраняет сырые данные заказа в таблицу Order.
    Определяет, нужно ли обновлять существующую запись на основе статуса.

    Args:
        db (Session): Сессия.
        user (User): Пользователь.
        order_data (dict): Данные от API.
        existing_status (str): Текущий статус в БД (для оптимизации).
        scheme (str): fbo/fbs.

    Returns:
        bool: True, если запись была создана или статус изменился.
    """
    if not isinstance(order_data, dict): return False
    posting_number = order_data.get('posting_number')
    if not posting_number: return False
    
    try:
        user_id = user.id if hasattr(user, 'id') else user
        status = order_data.get('status')
        raw_created_at = order_data.get('created_at')
        
        # Парсим дату создания
        dt_created = parse_ozon_datetime(raw_created_at)
        if dt_created: 
            dt_created = dt_created.astimezone(timezone.utc).replace(tzinfo=None)

        # Оптимизированный путь: если мы точно знаем, что заказа нет
        if existing_status == "__NOT_FOUND__":
            new_order = Order(
                user_id=user_id, order_id=order_data.get('order_id'),
                posting_number=posting_number, status=status, scheme=scheme,
                created_at=dt_created, updated_at=get_now_utc(), data=order_data
            )
            db.add(new_order)
            return True

        # Если мы знаем статус и он изменился
        if existing_status != "__FALLBACK__":
            if existing_status != status:
                db.query(Order).filter(Order.user_id == user_id, Order.posting_number == posting_number).update({
                    "status": status, "updated_at": get_now_utc(), "data": order_data
                }, synchronize_session=False)
                return True
            return False

        # Фоллбэк: ручная проверка в БД (медленно)
        existing = db.query(Order).filter(Order.user_id == user_id, Order.posting_number == posting_number).first()
        if existing:
            if existing.status != status:
                existing.status = status
                existing.updated_at = get_now_utc()
                existing.data = order_data
                return True
            return False
        
        # Создание нового заказа
        new_order = Order(
            user_id=user_id, order_id=order_data.get('order_id'),
            posting_number=posting_number, status=status, scheme=scheme,
            created_at=dt_created, updated_at=get_now_utc(), data=order_data
        )
        db.add(new_order)
        return True
    except Exception as e:
        logger.error(f"Error saving order {posting_number}: {e}")
        raise

async def fetch_and_save_orders_async(since: str, to: str, status_f: str, limit: int, offset: int, user_id: int, db: Session, scheme: str = "fbo") -> dict:
    """
    Низкоуровневая обертка для загрузки пачки заказов и их сохранения.
    Используется в основном в процессах бэкфилла.

    Args:
        since (str): Начало периода (ISO).
        to (str): Конец периода (ISO).
        status_f (str): Фильтр по статусу.
        limit (int): Лимит.
        offset (int): Смещение.
        user_id (int): ID пользователя.
        db (Session): Сессия.
        scheme (str): Схема.

    Returns:
        dict: Статистика операции (saved, fetched, orders).
    """
    try:
        user = db.query(User).filter(User.id == user_id).first()
        cred = db.query(OzonCredential).filter(OzonCredential.user_id == user_id, OzonCredential.is_active == True).first()
        if not user or not cred: return {"saved": 0, "fetched": 0, "orders": []}
        
        client_id = decrypt_credential(cred.client_id_encrypted)
        api_key = decrypt_credential(cred.api_key_encrypted)

        filter_dict = {'since': since, 'to': to}
        if status_f: filter_dict['status'] = status_f

        # Вызов API
        if scheme == 'fbo':
            res = await ozon_fbo_list_async(client_id, api_key, filter_dict, limit, offset)
        else:
            res = await ozon_fbs_list_async(client_id, api_key, filter_dict, limit, offset)

        if not isinstance(res, dict): return {"saved": 0, "fetched": 0, "error": "Bad API response", "orders": []}
        res_val = res.get("result")
        
        # Нормализация формата ответа
        if isinstance(res_val, dict):
            items = res_val.get("postings", [])
        elif isinstance(res_val, list):
            items = res_val
        else:
            items = []

        if not isinstance(items, list): return {"saved": 0, "fetched": 0, "error": "Result not a list", "orders": []}

        # Массовая проверка существующих записей
        fetched_pns = [o.get('posting_number') for o in items if isinstance(o, dict) and o.get('posting_number')]
        existing_map = {}
        if fetched_pns:
            rows = db.query(Order.posting_number, Order.status).filter(
                Order.user_id == user_id, Order.posting_number.in_(fetched_pns)
            ).all()
            existing_map = {r[0]: r[1] for r in rows}

        saved = 0
        valid_orders = []
        for o in items:
            if not isinstance(o, dict): continue
            pn = o.get('posting_number', 'unknown')
            try:
                with db.begin_nested():
                    # Сохранение в БД
                    if save_order_for_user(db, user, o, existing_status=existing_map.get(pn, "__NOT_FOUND__"), scheme=scheme):
                        saved += 1
                valid_orders.append(o)
            except Exception as e:
                logger.error(f"Error saving order {pn} in fetch_and_save: {e}")

        db.commit()
        return {"saved": saved, "fetched": len(items), "orders": valid_orders}
    except Exception as e:
        logger.error(f"fetch_and_save_orders_async error: {e}")
        return {"saved": 0, "fetched": 0, "error": str(e), "orders": []}

async def run_enrichment_batch(pns: list[str], user_id: int, scheme: str = None):
    """
    Запускает параллельный процесс детализации (enrichment) для списка номеров отправлений.
    Обогащает данные товарами, изображениями и точными финансовыми показателями.

    Args:
        pns (list[str]): Список номеров отправлений.
        user_id (int): ID пользователя.
        scheme (str): Схема работы.
    """
    if not pns: return
    logger.info(f"User {user_id}: Запрос деталей по {len(pns)} заказам...")
    
    # Предварительно загружаем ключи один раз
    check_db = SessionLocal()
    try:
        cred = check_db.query(OzonCredential).filter(OzonCredential.user_id == user_id, OzonCredential.is_active == True).first()
        if not cred: return
        client_id = decrypt_credential(cred.client_id_encrypted)
        api_key = decrypt_credential(cred.api_key_encrypted)
    finally: 
        check_db.close()

    success_count = 0
    # Ограничиваем количество одновременных запросов к API через семафор
    sem = asyncio.Semaphore(ENRICH_CONCURRENCY)

    async def _enrich_one(pn):
        nonlocal success_count
        async with sem:
            db = SessionLocal()
            try:
                # Обогащаем один постинг
                res = await enrich_posting_from_ozon(
                    posting_number=pn, user_id=user_id, db=db,
                    client_id=client_id, api_key=api_key, scheme=scheme
                )
                if res.get("status") == "ok":
                    success_count += 1
                    db.commit()
                else: 
                    db.rollback()
            except Exception as e:
                db.rollback()
                logger.error(f"User {user_id}: Error enriching {pn}: {e}")
            finally: 
                db.close()

    # Запускаем все задачи параллельно
    await asyncio.gather(*(_enrich_one(p) for p in pns))
    logger.info(f"User {user_id}: Обогащение завершено. Успешно: {success_count}/{len(pns)}.")

async def sync_ozon_transactions(user_id: int, db: Session, days_back: int = 30):
    """
    Синхронизирует транзакционные расходы (реклама, хранение, логистика) из /v3/finance/transaction/list.
    Парсит типы операций и сохраняет их в таблицу Cost.

    Args:
        user_id (int): ID пользователя.
        db (Session): Сессия.
        days_back (int): За сколько дней назад тянуть транзакции.

    Returns:
        int: Количество новых синхронизированных транзакций.
    """
    try:
        active_cred = db.query(OzonCredential).filter(OzonCredential.user_id == user_id, OzonCredential.is_active == True).first()
        if not active_cred: return 0
        
        client_id = decrypt_credential(active_cred.client_id_encrypted)
        api_key = decrypt_credential(active_cred.api_key_encrypted)
        
        now = get_now_utc()
        since_dt = now - timedelta(days=days_back)
        from_iso = since_dt.replace(microsecond=0).isoformat() + 'Z'
        to_iso = now.replace(microsecond=0).isoformat() + 'Z'
        
        page, total_synced = 1, 0
        while page <= 50: # Защита от бесконечного цикла
            data = await ozon_transaction_list_async(client_id, api_key, from_iso, to_iso, page=page)
            operations = data.get("result", {}).get("operations", [])
            if not operations: break
            
            # Собираем ID операций для проверки на дубликаты
            op_ids = [str(op.get("operation_id")) for op in operations if op.get("operation_id")]
            existing_tags = set()
            if op_ids:
                # Ищем пометку [ID:...] в поле notes таблицы Cost
                from sqlalchemy import or_
                check_q = db.query(Cost.notes).filter(Cost.user_id == user_id)
                found_notes = []
                # Разбиваем на батчи по 100 для LIKE-запроса
                for i in range(0, len(op_ids), 100):
                    batch_ids = op_ids[i:i+100]
                    batch_patterns = [f"%[ID:{oid}]%" for oid in batch_ids]
                    found_notes.extend([r[0] for r in check_q.filter(or_(*(Cost.notes.like(p) for p in batch_patterns))).all()])
                
                for note in found_notes:
                    for oid in op_ids:
                        if f"[ID:{oid}]" in note: existing_tags.add(oid)

            costs_to_add = []
            for op in operations:
                amount = float(op.get("amount") or 0)
                # Нас интересуют только списания (отрицательные суммы)
                if amount >= 0: continue
                
                op_id = str(op.get("operation_id"))
                if op_id in existing_tags: continue # Пропускаем, если уже загружено
                
                dt_op = parse_ozon_datetime(op.get("operation_date"))
                if dt_op: dt_op = dt_op.replace(tzinfo=None)
                
                category = "other" # Категория по умолчанию
                type_name = op.get("operation_type_name", "").lower()
                services = op.get("services", [])
                service_names = " ".join([s.get("name", "").lower() for s in services])
                
                # Классификация расхода по ключевым словам
                if "реклам" in type_name or "реклам" in service_names or "promotion" in service_names: 
                    category = "advertising"
                elif "хранен" in type_name or "storage" in service_names or "inventory" in service_names: 
                    category = "storage"
                elif "логистик" in type_name or "доставк" in type_name or "delivery" in type_name: 
                    category = "logistics"
                
                notes = f"{op.get('operation_type_name')} [ID:{op_id}]"
                if services: 
                    notes += " | Услуги: " + ", ".join([f"{s.get('name')}: {s.get('price')}" for s in services])
                
                costs_to_add.append(Cost(
                    user_id=user_id, type=category, amount=int(abs(amount)), 
                    date=dt_op, notes=notes
                ))
                total_synced += 1
            
            if costs_to_add: 
                db.add_all(costs_to_add)
            db.commit()
            
            if len(operations) < 1000: break
            page += 1
            await asyncio.sleep(0.1)
            
        return total_synced
    except Exception as e:
        logger.error(f"Error syncing transactions for user {user_id}: {e}")
        return 0

async def sync_range_for_user(user_id: int, start_dt: datetime, end_dt: datetime, db: Session):
    """
    Синхронизирует заказы и начисления за произвольный период.
    Использует пагинацию и оптимальные окна запроса для избежания таймаутов API.

    Args:
        user_id (int): ID пользователя.
        start_dt (datetime): Начало периода.
        end_dt (datetime): Конец периода.
        db (Session): Сессия.
    """
    start_dt, end_dt = start_dt.replace(tzinfo=None), end_dt.replace(tzinfo=None)
    cred = db.query(OzonCredential).filter(OzonCredential.user_id == user_id, OzonCredential.is_active == True).first()
    if not cred:
        logger.warning(f"User {user_id}: Range sync aborted: API credentials not found or inactive")
        sync_status = db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
        if sync_status:
            sync_status.status_message = "Error: API credentials not found or inactive"
            db.commit()
        return
    
    logger.info(f"User {user_id}: Starting range sync: {start_dt} - {end_dt}")
    
    # Обновляем статус для отображения в UI
    sync_status = db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
    if not sync_status:
        sync_status = SyncStatus(user_id=user_id)
        db.add(sync_status)
    sync_status.is_syncing, sync_status.status_message = True, f"Range sync: {start_dt.date()} — {end_dt.date()}"
    db.commit()
    
    try:
        for scheme in ['fbo', 'fbs']:
            # Идем назад по времени пачками (окнами)
            current_end, window_days = end_dt, (30 if scheme == 'fbo' else 14)
            while current_end > start_dt:
                current_start = max(current_end - timedelta(days=window_days), start_dt)
                start_iso = current_start.replace(microsecond=0).isoformat() + 'Z'
                end_iso = current_end.replace(microsecond=0).isoformat() + 'Z'
                
                offset, limit = 0, 1000
                while True:
                    res = await fetch_and_save_orders_async(start_iso, end_iso, "", limit, offset, user_id, db, scheme=scheme)
                    if res.get("error"):
                        err_msg = f"Orders error ({scheme}) at {start_iso}: {res.get('error')}"
                        logger.error(f"User {user_id}: Range sync: {err_msg}")
                        raise Exception(err_msg)
                    
                    # Собираем номера для обогащения
                    pns = [o.get("posting_number") for o in res.get("orders", []) if isinstance(o, dict) and valid_posting_number(o.get("posting_number"))]
                    if pns: 
                        await run_enrichment_batch(pns, user_id, scheme=scheme)
                    
                    if res.get("fetched", 0) < limit: break
                    offset += limit
                    await asyncio.sleep(0.2)
                
                current_end = current_start
                await asyncio.sleep(0.5)
        
        # Догружаем начисления за каждый день периода
        acc_current = end_dt
        while acc_current >= start_dt:
            date_str = acc_current.strftime("%Y-%m-%d")
            res = await enrich_accruals_from_ozon(user_id, date_str, db)
            if res.get("status") != "ok":
                err_msg = f"Accrual error at {date_str}: {res.get('detail', 'Unknown error')}"
                logger.error(f"User {user_id}: Range sync: {err_msg}")
                raise Exception(err_msg)
            
            acc_current -= timedelta(days=1)
            await asyncio.sleep(0.1)

        # Если дошли сюда — всё успешно
        db.refresh(sync_status)
        sync_status.status_message = "ok"
    except Exception as e:
        logger.error(f"User {user_id}: Range sync failed: {e}")
        db.rollback() # Очищаем состояние сессии перед записью ошибки
        db.refresh(sync_status)
        sync_status.status_message = f"Error: {str(e)[:200]}"
        raise # Пробрасываем в задачу воркера
    finally:
        sync_status.is_syncing = False
        db.commit()

async def initial_backfill_for_user(user: User, db: Session):
    """
    Запускает первичную загрузку истории данных за последний год (Backfill).
    Это длительный процесс, который выполняется в фоне.
    Сохраняет прогресс в SyncStatus, что позволяет возобновить его при прерывании.

    Args:
        user (User): Пользователь.
        db (Session): Сессия.
    """
    user_id = user.id if hasattr(user, 'id') else user
    cred = db.query(OzonCredential).filter(OzonCredential.user_id == user_id, OzonCredential.is_active == True).first()
    
    if not cred:
        st = db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
        if st:
            st.is_syncing, st.status_message = False, "Ошибка: не настроены API ключи"
            db.commit()
        return

    # Создаем собственную сессию для долгого фонового процесса
    bg_db = SessionLocal()
    try:
        st = bg_db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
        if not st:
            st = SyncStatus(user_id=user_id)
            bg_db.add(st)
            bg_db.commit()
            bg_db.refresh(st)
        
        now = get_now_utc()
        start_limit = now - timedelta(days=365) # Глубина истории - 1 год
        
        # Определяем готовность начислений
        accruals_done = st.accruals_backfill_cursor is not None and st.accruals_backfill_cursor <= start_limit

        # Если всё уже загружено - выходим
        if st.backfill_is_complete and st.fbs_backfill_is_complete and accruals_done:
            return

        # --- 1. Backfill FBO (заказы со склада Ozon) ---
        if not st.backfill_is_complete:
            await _run_scheme_backfill(user_id, bg_db, start_limit, now, scheme='fbo')

        # --- 2. Backfill FBS (заказы со склада продавца) ---
        if not st.fbs_backfill_is_complete:
            await _run_scheme_backfill(user_id, bg_db, start_limit, now, scheme='fbs')

        # --- 3. ОДНОКРАТНАЯ загрузка начислений за весь год ---
        if not accruals_done:
            logger.info(f"User {user_id}: Starting full-year accrual backfill...")
            # Продолжаем с того места, где остановились
            current_acc_date = st.accruals_backfill_cursor or now
            
            while current_acc_date > start_limit:
                date_str = current_acc_date.strftime("%Y-%m-%d")
                res = await enrich_accruals_from_ozon(user_id, date_str, bg_db)
                
                # 🔴 Исправление: проверяем статус загрузки. 
                # Теперь ловим не только "error", но и "no_credentials" или любые другие неуспешные статусы.
                if res.get("status") != "ok":
                    error_detail = res.get("detail", "Unknown API error or credentials issue")
                    raise Exception(f"Accrual backfill failed at {date_str}: {error_detail}")

                current_acc_date -= timedelta(days=1)
                st.accruals_backfill_cursor = current_acc_date
                bg_db.commit() # Сохраняем прогресс только после успешного дня
                await asyncio.sleep(0.1)
            
            # Финализируем курсор
            st.accruals_backfill_cursor = start_limit
            bg_db.commit()
            accruals_done = True

        # Финальный статус ставим только если ВСЕ этапы реально завершены
        if st.backfill_is_complete and st.fbs_backfill_is_complete and accruals_done:
            st.is_syncing = False
            st.status_message = "Backfill completed"
            bg_db.commit()
    except Exception as e: 
        logger.error(f"User {user_id}: Backfill failed: {e}")
        # Сбрасываем флаг синхронизации при ошибке, чтобы не блокировать процесс навсегда
        try:
            bg_db.rollback()
            # Перечитываем объект в новой транзакции
            st_err = bg_db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
            if st_err:
                st_err.is_syncing = False
                st_err.status_message = f"Backfill failed: {str(e)[:100]}"
                bg_db.commit()
        except Exception as ef:
            logger.error(f"Failed to reset sync status after error: {ef}")
    finally: 
        bg_db.close()

async def _run_scheme_backfill(user_id: int, db: Session, start_limit: datetime, now: datetime, scheme: str):
    """
    Внутренний метод для выполнения бэкфилла заказов конкретной схемы.
    Загружает историю пачками по дням, сохраняя промежуточный результат (курсор).

    Args:
        user_id (int): ID пользователя.
        db (Session): Сессия.
        start_limit (datetime): Точка остановки в прошлом.
        now (datetime): Точка начала (настоящее время).
        scheme (str): Схема (fbo/fbs).
    """
    st = db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
    
    # Динамически определяем атрибуты прогресса в зависимости от схемы
    cursor_attr = 'backfill_cursor' if scheme == 'fbo' else 'fbs_backfill_cursor'
    is_complete_attr = 'backfill_is_complete' if scheme == 'fbo' else 'fbs_backfill_is_complete'
    
    current_end = getattr(st, cursor_attr) or now
    window_days = 30 if scheme == 'fbo' else 14 # FBS имеет более жесткое окно в API
    
    while current_end > start_limit:
        current_start = max(current_end - timedelta(days=window_days), start_limit)
        st.status_message, st.is_syncing = f"Backfill {scheme.upper()}: {current_start.date()} — {current_end.date()}", True
        db.commit()
        
        start_iso = current_start.replace(microsecond=0).isoformat() + 'Z'
        end_iso = current_end.replace(microsecond=0).isoformat() + 'Z'
        
        offset, limit = 0, 1000
        while True:
            # Загружаем и сохраняем заказы за окно
            res = await fetch_and_save_orders_async(start_iso, end_iso, "", limit, offset, user_id, db, scheme=scheme)
            if res.get("error"):
                error_msg = f"Backfill {scheme} error for user {user_id}: {res['error']}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            if not res.get("orders"): break
            
            # Обогащаем пачками по 50 номеров
            pns = [o.get("posting_number") for o in res["orders"] if isinstance(o, dict) and valid_posting_number(o.get("posting_number"))]
            if pns:
                for i in range(0, len(pns), 50): 
                    await run_enrichment_batch(pns[i:i+50], user_id, scheme=scheme)
            
            if res.get("fetched", 0) < limit: break
            offset += limit
            await asyncio.sleep(0.3)

        # Сдвигаем курсор назад
        setattr(st, cursor_attr, current_start)
        db.commit()
        current_end = current_start
        await asyncio.sleep(1) # Небольшая пауза для снижения нагрузки на БД/API
        
    setattr(st, is_complete_attr, True)
    db.commit()
