"""
Эндпоинты синхронизации данных с Ozon API.
"""
import os
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from db.database import Order, OrderPosting, get_db, User, SyncStatus
from datetime import datetime, timedelta, timezone
from services.sync import fetch_and_save_orders, run_enrichment_batch, initial_backfill_for_user
from utils.auth import get_current_user
from utils.logging_config import log_user_event

logger = logging.getLogger("OzonAPIHub")

router = APIRouter(prefix="/sync", tags=["sync"])

# Конфигурация из окружения
ENABLE_INITIAL_SYNC = os.getenv('ENABLE_INITIAL_SYNC', 'true').lower() in ('1', 'true', 'yes')
HISTORY_WINDOW_DAYS = int(os.getenv('HISTORY_WINDOW_DAYS', '30'))


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


async def history_forward_sync(user: User, db: Session, start_dt: datetime, end_dt: datetime) -> list:
    """Импорт истории от start_dt до end_dt окнами по HISTORY_WINDOW_DAYS для пользователя."""
    summary = []
    window_start = start_dt

    log_user_event(user.id, f"Запуск ручного импорта истории: {start_dt} -> {end_dt}")

    while window_start < end_dt:
        window_end = min(window_start + timedelta(days=HISTORY_WINDOW_DAYS), end_dt)
        since_iso = window_start.isoformat() + 'Z'
        to_iso = window_end.isoformat() + 'Z'

        log_user_event(user.id, f"Синхронизация окна истории: {since_iso} -> {to_iso}")

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
                log_user_event(user.id, f"Обогащение {len(pns)} заказов из окна истории")
                await run_enrichment_batch(pns, user.id)
        except Exception as e:
            error_msg = f"Ошибка в окне истории {since_iso} -> {to_iso}: {e}"
            log_user_event(user.id, error_msg, "error")
            summary.append({
                "since": since_iso, 
                "to": to_iso, 
                "error": str(e)
            })
        window_start = window_end + timedelta(seconds=1)

    log_user_event(user.id, "Ручной импорт истории завершен.")
    return summary


@router.post("/initial")
async def run_initial_sync_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Запустить первичную полную синхронизацию заказов для текущего пользователя.
    """
    if not ENABLE_INITIAL_SYNC:
        raise HTTPException(status_code=400, detail="Initial sync disabled by config")

    sync_status = db.query(SyncStatus).filter(SyncStatus.user_id == current_user.id).first()
    if sync_status and sync_status.status_message == "completed":
        return {"status": "already_done", "completed_at": sync_status.sync_completed_at}

    if sync_status and sync_status.is_syncing:
        return {"status": "in_progress", "started_at": sync_status.sync_started_at}

    log_user_event(current_user.id, "Пользователь запустил первичную синхронизацию (Initial Backfill) вручную.")

    # Запускаем фоновую задачу первичного импорта
    asyncio.create_task(initial_backfill_for_user(current_user, db))

    return {"status": "started", "message": "Первичная синхронизация запущена в фоне"}


@router.get("/status")
def get_sync_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Получить статус текущей синхронизации пользователя."""
    status = db.query(SyncStatus).filter(SyncStatus.user_id == current_user.id).first()
    if not status:
        return {"is_syncing": False, "status_message": "not_started"}

    return {
        "is_syncing": status.is_syncing,
        "status_message": status.status_message,
        "sync_started_at": status.sync_started_at,
        "sync_completed_at": status.sync_completed_at,
        "total_records_synced": status.total_records_synced
    }


@router.post("/history")
async def run_history_sync(
    start: str,
    end: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Ручной импорт истории по окнам.
    """
    try:
        start_dt = _iso_to_dt(start)
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        end_dt = _iso_to_dt(end) if end else now_utc
    except Exception:
        raise HTTPException(status_code=400, detail='Bad date format')
    
    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail='end < start')
    
    summary = await history_forward_sync(current_user, db, start_dt, end_dt)
    return {"status": "done", "windows": summary}
