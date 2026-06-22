"""
Эндпоинты для управления процессами синхронизации.
Позволяет вручную запускать полную загрузку истории (Backfill) и проверять текущий прогресс.
"""
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from db.database import get_db, User, SyncStatus
from datetime import datetime, timezone
from utils.auth import get_current_user
from utils.common import parse_ozon_datetime

logger = logging.getLogger("OzonAPIHub")

router = APIRouter(prefix="/sync", tags=["sync"])


def _iso_to_dt(s: str) -> datetime:
    if s is None: return None
    dt = parse_ozon_datetime(s)
    if dt is None:
        raise ValueError(f"Некорректный формат даты: {s}")
    # Возвращаем наивный UTC для совместимости с логикой эндпоинта
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


@router.get("/status")
def get_sync_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Возвращает текущий прогресс синхронизации для UI."""
    status = db.query(SyncStatus).filter(SyncStatus.user_id == current_user.id).first()
    if not status:
        return {
            "is_syncing": False,
            "status_message": "not_started",
            "total_records_synced": 0,
            "sync_started_at": None,
            "sync_completed_at": None,
            "backfill_cursor": None,
            "backfill_started_at": None,
            "backfill_completed_at": None,
            "backfill_from": None,
            "backfill_to": None,
            "backfill_is_complete": False
        }

    return {
        "is_syncing": status.is_syncing,
        "status_message": status.status_message,
        "sync_started_at": status.sync_started_at,
        "sync_completed_at": status.sync_completed_at,
        "total_records_synced": status.total_records_synced,
        "backfill_cursor": status.backfill_cursor,
        "backfill_started_at": status.backfill_started_at,
        "backfill_completed_at": status.backfill_completed_at,
        "backfill_from": status.backfill_from,
        "backfill_to": status.backfill_to,
        "backfill_is_complete": status.backfill_is_complete
    }


@router.post("/initial")
@router.post("/initial/force")
async def run_initial_sync(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Запуск полной загрузки истории заказов через ARQ воркер."""
    # Проверка доступности пула ARQ
    arq_pool = getattr(request.app.state, "arq_pool", None)
    if arq_pool is None:
        logger.error("ARQ Task Pool is not initialized. Check Redis connection.")
        raise HTTPException(
            status_code=503,
            detail="Сервис очередей временно недоступен. Попробуйте позже."
        )

    sync_status = db.query(SyncStatus).filter(SyncStatus.user_id == current_user.id).first()

    # Различаем /initial и /initial/force
    is_force = request.url.path.endswith("/force")

    if sync_status and sync_status.is_syncing and not is_force:
        raise HTTPException(
            status_code=409,
            detail="Синхронизация уже выполняется. Используйте /force для принудительного перезапуска."
        )

    if not sync_status:
        sync_status = SyncStatus(user_id=current_user.id)
        db.add(sync_status)

    # Сбрасываем флаг завершенности для повторного запуска
    sync_status.backfill_is_complete = False
    sync_status.is_syncing = True
    sync_status.status_message = "Задача добавлена в очередь воркеров..."
    sync_status.sync_started_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # При force сбрасываем курсор, чтобы начать сначала
    if is_force:
        sync_status.backfill_cursor = None
        sync_status.backfill_from = None
        sync_status.status_message = "Принудительный перезапуск: задача добавлена в очередь..."

    db.commit()

    logger.info(f"Добавление задачи Backfill в очередь для пользователя {current_user.id} (force={is_force})")

    try:
        # Отправляем задачу в Redis для воркера с уникальным ID задачи
        await arq_pool.enqueue_job(
            'initial_backfill_task',
            current_user.id,
            _job_id=f"backfill_user_{current_user.id}"
        )
    except Exception as e:
        logger.error(f"Failed to enqueue job for user {current_user.id}: {e}")
        sync_status.is_syncing = False
        sync_status.status_message = "Ошибка при постановке задачи в очередь"
        db.commit()
        raise HTTPException(status_code=500, detail="Не удалось запустить синхронизацию")

    return {"status": "ok", "message": "Загрузка добавлена в очередь"}


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

    raise HTTPException(
        status_code=501,
        detail="Ручной выбор периода временно недоступен в новой системе воркеров. Используйте полную загрузку."
    )
