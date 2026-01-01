import os
import logging
logger = logging.getLogger("uvicorn.error")
import asyncio
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from db.database import Order, OrderPosting, SessionLocal
from services.enrichment import enrich_posting_from_ozon
from services.ozon import ozon_fbo_list
from db.database import OrderPosting
from utils.common import valid_posting_number

_valid_posting_number = valid_posting_number

LOG_OZON_REQUESTS = os.getenv('LOG_OZON_REQUESTS', 'false').lower() in ('1', 'true', 'yes')
ENRICH_RECENT_POSTINGS = os.getenv('ENRICH_RECENT_POSTINGS', 'true').lower() in ('1', 'true', 'yes')
ENRICH_RECENT_LIMIT = int(os.getenv('ENRICH_RECENT_LIMIT', '100'))
ENRICH_CONCURRENCY = int(os.getenv('ENRICH_CONCURRENCY', '4'))
ENRICH_ON_FETCH = os.getenv('ENRICH_ON_FETCH', 'true').lower() in ('1', 'true', 'yes')
ENRICH_ON_FETCH_LIMIT = int(os.getenv('ENRICH_ON_FETCH_LIMIT', '200'))
ENRICH_ON_STATUS_CHANGE = os.getenv('ENRICH_ON_STATUS_CHANGE', 'true').lower() in ('1', 'true', 'yes')
ENRICH_STATUS_CHANGE_LIMIT = int(os.getenv('ENRICH_STATUS_CHANGE_LIMIT', '100'))
RECENT_WINDOW_HOURS = int(os.getenv('RECENT_WINDOW_HOURS', '48'))
MONTH_RECONCILE_INTERVAL_SECONDS = int(os.getenv('MONTH_RECONCILE_INTERVAL_SECONDS', '3600'))
MONTH_RECONCILE_MONTHS = int(os.getenv('MONTH_RECONCILE_MONTHS', '3'))


def _iso_to_dt(s: str):
    s2 = s.rstrip('Z')
    return datetime.fromisoformat(s2)


def save_order(order: dict, db: Session):
    db_order = db.query(Order).filter(Order.posting_number == order.get('posting_number')).first()
    if db_order:
        db_order.order_id = order.get('order_id')
        db_order.status = order.get('status')
        db_order.updated_at = order.get('created_at')
        db_order.data = order
        db.commit()
        return 'updated'
    else:
        new_order = Order(
            order_id=order.get('order_id'),
            posting_number=order.get('posting_number'),
            status=order.get('status'),
            created_at=order.get('created_at'),
            updated_at=order.get('created_at'),
            data=order
        )
        db.add(new_order)
        db.commit()
        return 'inserted'


def fetch_and_save_orders(since: str = None, to: str = None, status: str = "", limit: int = 50, offset: int = 0,
                          analytics_data: bool = True, financial_data: bool = True, legal_info: bool = False,
                          db: Session = None):
    own_session = False
    if db is None:
        db = SessionLocal()
        own_session = True
    try:
        if not since and not to:
            last = db.query(Order).order_by(Order.created_at.desc()).first()
            since_dt = _iso_to_dt(last.created_at) if (last and last.created_at) else datetime.utcnow() - timedelta(days=7)
            to_dt = datetime.utcnow()
        else:
            since_dt = _iso_to_dt(since) if since else None
            to_dt = _iso_to_dt(to) if to else None
            if since_dt and not to_dt:
                to_dt = datetime.utcnow()
            if to_dt and not since_dt:
                since_dt = to_dt - timedelta(days=7)
        since_iso = since_dt.replace(microsecond=0).isoformat() + 'Z' if since_dt else None
        to_iso = to_dt.replace(microsecond=0).isoformat() + 'Z' if to_dt else None
        client_id = os.getenv("OZON_CLIENT_ID")
        api_key = os.getenv("OZON_API_KEY")
        url = "https://api-seller.ozon.ru/v2/posting/fbo/list"
        headers = {"Client-Id": client_id, "Api-Key": api_key, "Content-Type": "application/json"}
        total_saved = 0
        all_orders = []
        current_offset = offset
        while True:
            filter_dict = {}
            if since_iso:
                filter_dict['since'] = since_iso
            if to_iso:
                filter_dict['to'] = to_iso
            if status:
                filter_dict['status'] = status
            body = {"dir": "ASC", "filter": filter_dict, "limit": limit, "offset": current_offset, "translit": True,
                    "with": {"analytics_data": analytics_data, "financial_data": financial_data, "legal_info": legal_info}}
            if LOG_OZON_REQUESTS:
                logger.debug(f"Ozon request body: {body}")
            data = ozon_fbo_list(filter_dict, limit, current_offset, {"analytics_data": analytics_data, "financial_data": financial_data, "legal_info": legal_info})
            items = data.get('result', []) or []
            if not items:
                break
            for order in items:
                res = save_order(order, db)
                if res == 'inserted':
                    total_saved += 1
                all_orders.append(order)
            if len(items) < limit:
                break
            current_offset += limit
        enrich_targets = []
        if ENRICH_ON_FETCH and all_orders:
            try:
                enrich_targets = sorted({o.get('posting_number') for o in all_orders if valid_posting_number(o.get('posting_number'))})[:ENRICH_ON_FETCH_LIMIT]
            except Exception as e:
                logger.debug(f"Ошибка подготовки списка обогащения после выгрузки: {e}")
        return {"saved": total_saved, "fetched": len(all_orders), "orders": all_orders, "enrich_targets": enrich_targets}
    finally:
        if own_session:
            db.close()


async def run_enrichment_batch(posting_numbers: list[str]):
    """Асинхронно обогащает постинги с ограничением конкурентности."""
    if not posting_numbers:
        return 0

    targets = [pn for pn in posting_numbers if valid_posting_number(pn)]
    if not targets:
        return 0

    logger.info(f"Запуск обогащения для {len(targets)} постингов...")
    sem = asyncio.Semaphore(ENRICH_CONCURRENCY)

    async def _run_one(pn: str):
        async with sem:
            def _work():
                session = SessionLocal()
                try:
                    enrich_posting_from_ozon(pn, session)
                finally:
                    session.close()
            return await asyncio.to_thread(_work)

    await asyncio.gather(*(_run_one(pn) for pn in targets))
    logger.info(f"Обогащение завершено для {len(targets)} постингов")
    return len(targets)


async def background_sync_loop(app, interval_seconds: int = 300):
    logger.info("Фоновая синхронизация запущена")
    try:
        while True:
            try:
                res_new = await asyncio.to_thread(fetch_and_save_orders)
                app.state.last_sync_new = datetime.utcnow().isoformat() + 'Z'
                app.state.last_sync_new_saved = res_new.get('saved')
                app.state.last_sync_new_fetched = res_new.get('fetched')
                logger.info(f"Инкрементальная синхронизация: добавлено={res_new.get('saved')} получено={res_new.get('fetched')}")

                targets_new = res_new.get('enrich_targets') or []
                if targets_new:
                    try:
                        await run_enrichment_batch(targets_new)
                    except Exception as e:
                        logger.debug(f"Ошибка обогащения после инкрементальной синхронизации: {e}")

                recent_since_dt = datetime.utcnow() - timedelta(hours=RECENT_WINDOW_HOURS)
                recent_since = recent_since_dt.isoformat() + 'Z'
                res_recent = await asyncio.to_thread(fetch_and_save_orders, recent_since, None)
                app.state.last_sync_recent = datetime.utcnow().isoformat() + 'Z'
                app.state.last_sync_recent_saved = res_recent.get('saved')
                app.state.last_sync_recent_fetched = res_recent.get('fetched')
                app.state.last_sync_interval_seconds = interval_seconds
                logger.info(f"Сверка недавнего окна ({RECENT_WINDOW_HOURS}ч): добавлено={res_recent.get('saved')} получено={res_recent.get('fetched')}")

                # Дополнительно: полное обогащение недавнего окна (без лимитов)
                try:
                    recent_orders = res_recent.get('orders') or []
                    posting_numbers = sorted({o.get('posting_number') for o in recent_orders if valid_posting_number(o.get('posting_number'))})
                    if posting_numbers:
                        session = SessionLocal()
                        try:
                            existing = set(row[0] for row in session.query(OrderPosting.posting_number).filter(OrderPosting.posting_number.in_(posting_numbers)).all())
                        finally:
                            session.close()
                        targets = [pn for pn in posting_numbers if pn not in existing]
                        if targets:
                            await run_enrichment_batch(targets)
                            logger.info(f"Полное обогащение недавнего окна: обработано постингов={len(targets)}")
                except Exception as e:
                    logger.debug(f"Ошибка полного обогащения недавнего окна: {e}")

                if ENRICH_ON_STATUS_CHANGE:
                    try:
                        recent_items = res_recent.get('orders') or []
                        session = SessionLocal()
                        try:
                            candidates = []
                            for it in recent_items:
                                pn = it.get('posting_number')
                                if not valid_posting_number(pn):
                                    continue
                                new_status = it.get('status')
                                row = session.query(OrderPosting).filter(OrderPosting.posting_number == pn).first()
                                old_status = row.status if row else None
                                if new_status != old_status:
                                    candidates.append(pn)
                            targets = sorted(set(candidates))[:ENRICH_STATUS_CHANGE_LIMIT]
                        finally:
                            session.close()
                        if targets:
                            await run_enrichment_batch(targets)
                            logger.info(f"Переобогащение по изменению статуса: обработано={len(targets)}")
                    except Exception as e:
                        logger.debug(f"Ошибка переобогащения по статусам: {e}")

                if ENRICH_RECENT_POSTINGS:
                    try:
                        session = SessionLocal()
                        try:
                            since_iso = (datetime.utcnow() - timedelta(hours=RECENT_WINDOW_HOURS)).isoformat() + 'Z'
                            fresh_orders = session.query(Order.posting_number).filter(Order.created_at >= since_iso).order_by(Order.created_at.desc()).limit(ENRICH_RECENT_LIMIT).all()
                            fresh_norm = session.query(OrderPosting.posting_number).filter(OrderPosting.created_at >= since_iso).order_by(OrderPosting.created_at.desc()).limit(ENRICH_RECENT_LIMIT).all()
                            raw_targets = [o[0] for o in fresh_orders] + [n[0] for n in fresh_norm]
                            targets = sorted({pn for pn in raw_targets if valid_posting_number(pn)})
                        finally:
                            session.close()
                        await run_enrichment_batch(targets)
                        logger.info(f"Обогащение свежих постингов: обработано={len(targets)}")
                    except Exception as e:
                        logger.debug(f"Ошибка фонового обогащения: {e}")

                now = datetime.utcnow()
                if not hasattr(app.state, 'last_month_reconcile'):
                    app.state.last_month_reconcile = None
                do_reconcile = (
                    app.state.last_month_reconcile is None or
                    (now - _iso_to_dt(app.state.last_month_reconcile)).total_seconds() >= MONTH_RECONCILE_INTERVAL_SECONDS
                )
                if do_reconcile:
                    logger.info(f"Начинаю месячную сверку последних {MONTH_RECONCILE_MONTHS} месяцев")
                    base = datetime(now.year, now.month, 1)
                    summaries = []
                    for i in range(MONTH_RECONCILE_MONTHS):
                        start_dt = (base - timedelta(days=30*i)).replace(day=1)
                        end_dt = datetime(start_dt.year + (1 if start_dt.month == 12 else 0), 1 if start_dt.month == 12 else start_dt.month + 1, 1)
                        since_iso = start_dt.isoformat() + 'Z'
                        to_iso = end_dt.isoformat() + 'Z'
                        ym = start_dt.strftime('%Y-%m')
                        try:
                            r = await asyncio.to_thread(fetch_and_save_orders, since_iso, to_iso)
                            summaries.append((ym, r.get('saved'), r.get('fetched')))
                            logger.info(f"Месячная сверка {ym}: добавлено={r.get('saved')} получено={r.get('fetched')}")
                            # Дополнительно: обогатить все новые постинги этого окна, которых ещё нет в нормализованной таблице
                            orders_window = r.get('orders') or []
                            posting_numbers = sorted({o.get('posting_number') for o in orders_window if valid_posting_number(o.get('posting_number'))})
                            if posting_numbers:
                                session = SessionLocal()
                                try:
                                    existing = set(row[0] for row in session.query(OrderPosting.posting_number).filter(OrderPosting.posting_number.in_(posting_numbers)).all())
                                finally:
                                    session.close()
                                targets = [pn for pn in posting_numbers if pn not in existing]
                                if targets:
                                    await run_enrichment_batch(targets)
                                    logger.info(f"Обогащение месяца {ym}: обработано постингов={len(targets)}")
                        except Exception as e:
                            logger.error(f"Ошибка месячной сверки для {ym}: {e}")
                    app.state.last_month_reconcile = now.isoformat() + 'Z'
                    logger.info("Месячная сверка завершена")
            except Exception as e:
                logger.error(f"Ошибка фоновой синхронизации: {e}")
                app.state.last_sync_error = str(e)
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("Фоновая синхронизация остановлена")
        raise
