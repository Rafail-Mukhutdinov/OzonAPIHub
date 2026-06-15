"""
Эндпоинты для управления процессами синхронизации.
Позволяет вручную запускать полную загрузку истории (Backfill) и проверять текущий прогресс.
"""
import os
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from db.database import get_db, User, SyncStatus
from datetime import datetime, timedelta, timezone
from services.sync import fetch_and_save_orders_async, run_enrichment_batch
from utils.auth import get_current_user
from utils.logging_config import log_user_event

logger = logging.getLogger("OzonAPIHub")

router = APIRouter(prefix="/sync", tags=["sync"])

# Глобальные настройки из .env
HISTORY_WINDOW_DAYS = int(os.getenv('HISTORY_WINDOW_DAYS', '30'))


def _iso_to_dt(s: str) -> datetime:
    if s is None: return None
    try:
        s2 = s.rstrip('Z')
        return datetime.fromisoformat(s2)
    except Exception:
        raise ValueError(f"Некорректный формат даты: {s}")


@router.get("/status")
def get_sync_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Возвращает текущий прогресс синхронизации для UI."""
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
    request: Request,
    start: str,
    end: str | None = None,
    current_user: User = Depends(get_current_user)
):
    """
    Ручной запуск импорта за конкретный выбранный пользователем период через воркер.
    """
    try:
        start_dt = _iso_to_dt(start)
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        end_dt = _iso_to_dt(end) if end else now_utc
    except Exception:
        raise HTTPException(status_code=400, detail='Неверный формат даты')
    
    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail='Дата конца не может быть раньше даты начала')
    
    # В будущем здесь можно добавить отдельную задачу в воркер для произвольного периода
    # Пока просто сообщаем, что это планируется
    return {"status": "error", "message": "Ручной выбор периода временно недоступен в новой системе воркеров. Используйте полную загрузку."}
