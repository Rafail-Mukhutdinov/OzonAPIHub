"""
Эндпоинты для управления процессами синхронизации.
Позволяет вручную запускать полную загрузку истории (Backfill) и проверять текущий прогресс.
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

# Глобальные настройки из .env
ENABLE_INITIAL_SYNC = os.getenv('ENABLE_INITIAL_SYNC', 'true').lower() in ('1', 'true', 'yes')
HISTORY_WINDOW_DAYS = int(os.getenv('HISTORY_WINDOW_DAYS', '30'))


def _iso_to_dt(s: str) -> datetime:
    """Безопасно парсит ISO-строку даты в объект datetime."""
    if s is None:
        return None
    try:
        s2 = s.rstrip('Z')
        return datetime.fromisoformat(s2)
    except Exception:
        raise ValueError(f"Некорректный формат даты: {s}")


def _valid_posting_number(pn: str | None) -> bool:
    """Проверяет валидность номера отправления Ozon."""
    if not pn:
        return False
    if pn.upper().startswith('TEST-POSTING'):
        return False
    if '-' not in pn:
        return False
    suffix = pn.split('-')[-1]
    return suffix.isdigit()


async def history_forward_sync(user: User, db: Session, start_dt: datetime, end_dt: datetime) -> list:
    """
    Утилита для порционной загрузки заказов пользователя за длинный период.
    Разбивает период на окна по 30 дней, чтобы не перегружать API и БД.
    """
    summary = []
    window_start = start_dt

    log_user_event(user.id, f"Ручной запуск импорта: {start_dt} -> {end_dt}")

    while window_start < end_dt:
        window_end = min(window_start + timedelta(days=HISTORY_WINDOW_DAYS), end_dt)
        since_iso = window_start.isoformat() + 'Z'
        to_iso = window_end.isoformat() + 'Z'

        try:
            # Вызов функции синхронизации в отдельном потоке
            result = await asyncio.to_thread(
                fetch_and_save_orders,
                since_iso, to_iso, "", 50, 0, True, True, False, user.id, db
            )
            summary.append({
                "since": since_iso, 
                "to": to_iso, 
                "saved": result.get('saved'), 
                "fetched": result.get('fetched')
            })

            # Сразу подгружаем детали (комиссии) для найденных заказов
            orders = result.get('orders') or []
            pns = [o.get('posting_number') for o in orders if _valid_posting_number(o.get('posting_number'))]
            if pns:
                await run_enrichment_batch(pns, user.id)

        except Exception as e:
            log_user_event(user.id, f"Ошибка в окне {since_iso}: {e}", "error")
            summary.append({"since": since_iso, "to": to_iso, "error": str(e)})

        window_start = window_end + timedelta(seconds=1)

    return summary


@router.post("/initial")
async def run_initial_sync_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Запускает первичную синхронизацию (за 1 год).
    Если синхронизация уже была выполнена (статус 'completed'), повторно не запускается.
    """
    if not ENABLE_INITIAL_SYNC:
        raise HTTPException(status_code=400, detail="Первичная синхронизация отключена в настройках сервера")

    sync_status = db.query(SyncStatus).filter(SyncStatus.user_id == current_user.id).first()

    # Защита от повторных запусков
    if sync_status and sync_status.status_message == "completed":
        return {"status": "already_done", "completed_at": sync_status.sync_completed_at}

    if sync_status and sync_status.is_syncing:
        return {"status": "in_progress", "started_at": sync_status.sync_started_at}

    log_user_event(current_user.id, "Запуск первичной загрузки истории заказов.")

    # Используем asyncio.create_task для запуска задачи в фоне без ожидания результата
    asyncio.create_task(initial_backfill_for_user(current_user, db))

    return {"status": "started", "message": "Синхронизация запущена"}


@router.post("/initial/force")
async def run_initial_sync_force(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Принудительный перезапуск синхронизации.
    Игнорирует статус 'completed'. Полезно при добавлении новых ключей.
    """
    sync_status = db.query(SyncStatus).filter(SyncStatus.user_id == current_user.id).first()
    
    if sync_status and sync_status.is_syncing:
        return {"status": "in_progress", "started_at": sync_status.sync_started_at}

    log_user_event(current_user.id, "Принудительный перезапуск синхронизации.")
    asyncio.create_task(initial_backfill_for_user(current_user, db))

    return {"status": "started"}


@router.get("/status")
def get_sync_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Возвращает текущий прогресс синхронизации для UI (прогресс-бары)."""
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
    Ручной запуск импорта за конкретный выбранный пользователем период.
    """
    try:
        start_dt = _iso_to_dt(start)
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        end_dt = _iso_to_dt(end) if end else now_utc
    except Exception:
        raise HTTPException(status_code=400, detail='Неверный формат даты')
    
    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail='Дата конца не может быть раньше даты начала')
    
    summary = await history_forward_sync(current_user, db, start_dt, end_dt)
    return {"status": "done", "windows": summary}
