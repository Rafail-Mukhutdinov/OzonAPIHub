"""
Эндпоинты синхронизации данных с Ozon API.
"""
import os
import asyncio
import logging
from fastapi import APIRouter, HTTPException
from db.database import SessionLocal, Order, OrderPosting
from datetime import datetime, timedelta
from services.sync import fetch_and_save_orders, background_sync_loop, run_enrichment_batch

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/sync", tags=["sync"])

# Конфигурация из окружения
ENABLE_INITIAL_SYNC = os.getenv('ENABLE_INITIAL_SYNC', 'true').lower() in ('1', 'true', 'yes')
INITIAL_WINDOW_DAYS = int(os.getenv('INITIAL_WINDOW_DAYS', '365'))
HISTORY_WINDOW_DAYS = int(os.getenv('HISTORY_WINDOW_DAYS', '30'))
RECENT_WINDOW_HOURS = int(os.getenv('RECENT_WINDOW_HOURS', '48'))


def _iso_to_dt(s: str) -> datetime:
    """Парсит ISO строку в datetime."""
    if s is None:
        return None
    try:
        s2 = s.rstrip('Z')
        return datetime.fromisoformat(s2)
    except Exception:
        raise ValueError(f"Invalid ISO datetime: {s}")


def _valid_posting_number(pn: str | None) -> bool:
    """Проверяет валидность номера постинга."""
    if not pn:
        return False
    if pn.upper().startswith('TEST-POSTING'):
        return False
    if '-' not in pn:
        return False
    suffix = pn.split('-')[-1]
    return suffix.isdigit()


def get_earliest_order_date():
    """Получает самую раннюю дату заказа из Ozon API."""
    from services.ozon import ozon_fbo_list
    
    try:
        response = ozon_fbo_list({}, 1, 0, {"analytics_data": True, "financial_data": True})
        result = response.get('result', [])
        if result:
            return result[0].get('created_at')
        return None
    except Exception as e:
        logger.error(f"Ошибка получения самой ранней даты: {e}")
        return None


async def history_forward_sync(start_dt: datetime, end_dt: datetime) -> list:
    """Импорт истории от start_dt до end_dt окнами по HISTORY_WINDOW_DAYS."""
    summary = []
    window_start = start_dt
    while window_start < end_dt:
        window_end = min(window_start + timedelta(days=HISTORY_WINDOW_DAYS), end_dt)
        since_iso = window_start.isoformat() + 'Z'
        to_iso = window_end.isoformat() + 'Z'
        logger.info(f'[history sync] window: {since_iso} -> {to_iso}')
        try:
            result = await asyncio.to_thread(fetch_and_save_orders, since_iso, to_iso)
            summary.append({
                "since": since_iso, 
                "to": to_iso, 
                "saved": result.get('saved'), 
                "fetched": result.get('fetched')
            })
        except Exception as e:
            logger.error(f"Ошибка при синхронизации окна {since_iso} -> {to_iso}: {e}")
            summary.append({
                "since": since_iso, 
                "to": to_iso, 
                "error": str(e)
            })
        window_start = window_end + timedelta(seconds=1)
    return summary


@router.post("/initial")
async def run_initial_sync_endpoint():
    """
    Запустить первичную полную синхронизацию заказов.
    Вернёт сводку по выполненным окнам.
    """
    if not ENABLE_INITIAL_SYNC:
        raise HTTPException(status_code=400, detail="Initial sync disabled by config")

    root = os.path.dirname(os.path.dirname(__file__))
    marker_path = os.path.join(root, '.initial_sync_done')
    
    if os.path.exists(marker_path):
        return {"status": "already_done"}

    # Определяем самую раннюю дату
    earliest = get_earliest_order_date()
    if earliest:
        try:
            start_dt = _iso_to_dt(earliest)
        except Exception:
            start_dt = datetime.utcnow() - timedelta(days=INITIAL_WINDOW_DAYS)
    else:
        start_dt = datetime.utcnow() - timedelta(days=INITIAL_WINDOW_DAYS)

    now = datetime.utcnow()
    window_start = start_dt
    summary = []
    
    while window_start < now:
        window_end = min(window_start + timedelta(days=INITIAL_WINDOW_DAYS), now)
        since_iso = window_start.isoformat() + 'Z'
        to_iso = window_end.isoformat() + 'Z'
        try:
            result = await asyncio.to_thread(fetch_and_save_orders, since_iso, to_iso)
            summary.append({
                "since": since_iso, 
                "to": to_iso, 
                "saved": result.get('saved'), 
                "fetched": result.get('fetched')
            })
        except Exception as e:
            logger.error(f"Ошибка при initial sync: {e}")
            summary.append({
                "since": since_iso, 
                "to": to_iso, 
                "error": str(e)
            })
        window_start = window_end + timedelta(seconds=1)

    # Создаём маркер, чтобы больше не повторять
    try:
        with open(marker_path, 'w') as f:
            f.write(datetime.utcnow().isoformat() + 'Z')
    except Exception as e:
        logger.error(f'Could not write initial sync marker: {e}')

    return {"status": "done", "windows": summary}


@router.post("/initial/force")
async def run_initial_sync_force_endpoint():
    """
    Запустить первичную синхронизацию, игнорируя маркер.
    Полезно для повторного полного импорта.
    """
    if not ENABLE_INITIAL_SYNC:
        raise HTTPException(status_code=400, detail="Initial sync disabled by config")

    earliest = get_earliest_order_date()
    if earliest:
        try:
            start_dt = _iso_to_dt(earliest)
        except Exception:
            start_dt = datetime.utcnow() - timedelta(days=INITIAL_WINDOW_DAYS)
    else:
        start_dt = datetime.utcnow() - timedelta(days=INITIAL_WINDOW_DAYS)

    now = datetime.utcnow()
    window_start = start_dt
    summary = []
    
    while window_start < now:
        window_end = min(window_start + timedelta(days=INITIAL_WINDOW_DAYS), now)
        since_iso = window_start.isoformat() + 'Z'
        to_iso = window_end.isoformat() + 'Z'
        try:
            result = await asyncio.to_thread(fetch_and_save_orders, since_iso, to_iso)
            summary.append({
                "since": since_iso, 
                "to": to_iso, 
                "saved": result.get('saved'), 
                "fetched": result.get('fetched')
            })
        except Exception as e:
            logger.error(f"Ошибка при force initial sync: {e}")
            summary.append({
                "since": since_iso, 
                "to": to_iso, 
                "error": str(e)
            })
        window_start = window_end + timedelta(seconds=1)

    return {"status": "done", "windows": summary}


@router.post("/history")
async def run_history_sync(start: str, end: str = None):
    """
    Ручной импорт истории по окнам HISTORY_WINDOW_DAYS.
    
    Параметры:
    - start: ISO дата начала (обязательно)
    - end: ISO дата конца (по умолчанию текущий момент)
    """
    try:
        start_dt = _iso_to_dt(start)
        end_dt = _iso_to_dt(end) if end else datetime.utcnow()
    except Exception:
        raise HTTPException(status_code=400, detail='Bad date format')
    
    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail='end < start')
    
    summary = await history_forward_sync(start_dt, end_dt)
    return {"status": "done", "windows": summary}


@router.on_event("startup")
async def startup_sync_tasks(app):
    """
    При старте приложения: выполнить initial sync (если нужно),
    затем запустить циклический фоновый sync.
    """
    root = os.path.dirname(os.path.dirname(__file__))
    marker_path = os.path.join(root, '.initial_sync_done')

    async def run_initial_if_needed():
        if not ENABLE_INITIAL_SYNC:
            logger.info('Первичная загрузка отключена настройками')
            return
        
        if os.path.exists(marker_path):
            logger.info('Первичная загрузка уже выполнена (найден маркер)')
            return

        # Проверяем, что база пуста
        session = SessionLocal()
        try:
            count_rows = session.query(Order).count()
        finally:
            session.close()
        
        if count_rows > 0:
            logger.info('База не пустая; пропускаем первичный большой диапазон')
            return

        # Один запрос: год назад -> сейчас
        since_dt = datetime.utcnow() - timedelta(days=365)
        to_dt = datetime.utcnow()
        since_iso = since_dt.isoformat() + 'Z'
        to_iso = to_dt.isoformat() + 'Z'
        
        logger.info(f'Первичная единоразовая загрузка: {since_iso} -> {to_iso}')
        
        try:
            result = await asyncio.to_thread(fetch_and_save_orders, since_iso, to_iso)
            logger.info(f'Результат первичной загрузки: added={result.get("saved")}, fetched={result.get("fetched")}')
            
            # Обогатим постинги из результата initial sync
            try:
                orders = result.get('orders') or []
                pns = sorted({
                    o.get('posting_number') 
                    for o in orders 
                    if _valid_posting_number(o.get('posting_number'))
                })
                
                if pns:
                    db = SessionLocal()
                    try:
                        existing = set(
                            row[0] 
                            for row in db.query(OrderPosting.posting_number)
                            .filter(OrderPosting.posting_number.in_(pns))
                            .all()
                        )
                    finally:
                        db.close()
                    
                    targets = [pn for pn in pns if pn not in existing]
                    if targets:
                        await run_enrichment_batch(targets)
                        logger.info(f'Обогащение initial sync: обработано постингов={len(targets)}')
            except Exception as e:
                logger.debug(f'Ошибка обогащения во время initial sync: {e}')
        
        except Exception as e:
            logger.error(f'Ошибка во время первичной загрузки: {e}')
            return

        # Маркер, чтобы больше не повторять
        try:
            with open(marker_path, 'w') as f:
                f.write(datetime.utcnow().isoformat() + 'Z')
            logger.info('Первичная загрузка завершена, создан маркер')
        except Exception as e:
            logger.error(f'Не удалось записать маркер первичной загрузки: {e}')

    await run_initial_if_needed()
