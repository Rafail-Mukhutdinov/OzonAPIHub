"""
Эндпоинты синхронизации данных с Ozon API.
"""
import os
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from db.database import SessionLocal, Order, OrderPosting, get_db, User
from datetime import datetime, timedelta
from services.sync import fetch_and_save_orders, run_enrichment_batch, initial_backfill_for_user
from utils.auth import get_current_user

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


def _get_start_date_for_initial() -> datetime:
    """Стартовая дата первичной загрузки."""
    return datetime.utcnow() - timedelta(days=INITIAL_WINDOW_DAYS)


async def history_forward_sync(user: User, db: Session, start_dt: datetime, end_dt: datetime) -> list:
    """Импорт истории от start_dt до end_dt окнами по HISTORY_WINDOW_DAYS для пользователя."""
    summary = []
    window_start = start_dt
    while window_start < end_dt:
        window_end = min(window_start + timedelta(days=HISTORY_WINDOW_DAYS), end_dt)
        since_iso = window_start.isoformat() + 'Z'
        to_iso = window_end.isoformat() + 'Z'
        logger.info(f'[history sync] window: {since_iso} -> {to_iso}')
        try:
            result = await asyncio.to_thread(
                fetch_and_save_orders,
                since_iso,
                to_iso,
                "",
                50,
                0,
                True,
                True,
                False,
                user.id,
                db
            )
            summary.append({
                "since": since_iso, 
                "to": to_iso, 
                "saved": result.get('saved'), 
                "fetched": result.get('fetched')
            })
            orders = result.get('orders') or []
            pns = [o.get('posting_number') for o in orders if _valid_posting_number(o.get('posting_number'))]
            if pns:
                await run_enrichment_batch(pns, user.id)
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
async def run_initial_sync_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
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

    result = await initial_backfill_for_user(current_user, db)

    # Создаём маркер, чтобы больше не повторять
    try:
        with open(marker_path, 'w') as f:
            f.write(datetime.utcnow().isoformat() + 'Z')
    except Exception as e:
        logger.error(f'Could not write initial sync marker: {e}')

    return {"status": "done", "result": result}


@router.post("/initial/force")
async def run_initial_sync_force_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Запустить первичную синхронизацию, игнорируя маркер.
    Полезно для повторного полного импорта.
    """
    if not ENABLE_INITIAL_SYNC:
        raise HTTPException(status_code=400, detail="Initial sync disabled by config")

    result = await initial_backfill_for_user(current_user, db)
    return {"status": "done", "result": result}


@router.post("/history")
async def run_history_sync(
    start: str,
    end: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
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
    
    summary = await history_forward_sync(current_user, db, start_dt, end_dt)
    return {"status": "done", "windows": summary}


@router.on_event("startup")
async def startup_sync_tasks(app):
    """Оставлено пустым для совместимости; глобальный initial sync отключен в SaaS."""
    return None
