"""
Эндпоинты для управления процессами синхронизации.
Позволяет вручную запускать полную загрузку истории (Backfill) и проверять текущий прогресс.
"""
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from db.database import get_db, User, SyncStatus
from datetime import datetime, timezone, timedelta
from utils.auth import get_current_user
from utils.common import parse_ozon_datetime
from services.sync import sync_user_orders

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
        "last_sync_at": status.updated_at,
        "total_records_synced": status.total_records_synced,
        "backfill_cursor": status.backfill_cursor,
        "backfill_started_at": status.backfill_started_at,
        "backfill_completed_at": status.backfill_completed_at,
        "backfill_from": status.backfill_from,
        "backfill_to": status.backfill_to,
        "backfill_is_complete": status.backfill_is_complete
    }

@router.post("/manual")
async def trigger_manual_sync(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Запускает принудительную синхронизацию для пользователя.
    Ограничение: не чаще чем раз в 5 минут (300 секунд).
    """
    status = db.query(SyncStatus).filter(SyncStatus.user_id == current_user.id).first()
    
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cooldown = timedelta(minutes=5)
    
    if status and status.updated_at:
        elapsed = now - status.updated_at
        if elapsed < cooldown:
            remaining = cooldown - elapsed
            seconds = int(remaining.total_seconds())
            minutes = seconds // 60
            secs = seconds % 60
            raise HTTPException(
                status_code=429, 
                detail=f"Слишком часто. Подождите еще {minutes:01d} мин. {secs:02d} сек."
            )

    # Если статуса еще нет, создаем
    if not status:
        status = SyncStatus(user_id=current_user.id, status_message="manual_sync_started")
        db.add(status)
    
    status.is_syncing = True
    status.sync_started_at = now
    db.commit()

    try:
        # Запускаем синхронизацию (это блокирующий вызов для этого HTTP запроса, 
        # но так как это легкая синхронизация за последние дни, это нормально)
        found_new = await sync_user_orders(current_user, db)
        
        status.is_syncing = False
        status.sync_completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        status.updated_at = status.sync_completed_at
        status.status_message = "ok"
        db.commit()
        
        return {
            "status": "ok", 
            "new_orders_found": found_new,
            "last_sync_at": status.updated_at
        }
    except Exception as e:
        status.is_syncing = False
        status.status_message = f"error: {str(e)}"
        db.commit()
        logger.error(f"Manual sync error for user {current_user.id}: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при синхронизации")


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
        # Используем уникальный ID задачи, чтобы избежать блокировок в Redis при перезапусках
        job_id = f"backfill_user_{current_user.id}_{int(datetime.now().timestamp())}" if is_force else f"backfill_user_{current_user.id}"

        await arq_pool.enqueue_job(
            'initial_backfill_task',
            current_user.id,
            _job_id=job_id
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

    # Проверка, не идет ли уже другая синхронизация
    from db.database import SessionLocal
    db = SessionLocal() # Используем временную сессию, так как эндпоинт не инжектит db
    try:
        sync_status = db.query(SyncStatus).filter(SyncStatus.user_id == current_user.id).first()
        if sync_status and sync_status.is_syncing:
            raise HTTPException(
                status_code=409,
                detail="Синхронизация уже выполняется. Подождите завершения текущей задачи."
            )
    finally:
        db.close()

    arq_pool = getattr(request.app.state, "arq_pool", None)
    if arq_pool is None:
        raise HTTPException(status_code=503, detail="Сервис очередей недоступен")

    await arq_pool.enqueue_job(
        'history_sync_task',
        current_user.id,
        start_dt.isoformat(),
        end_dt.isoformat()
    )

    return {"status": "ok", "message": "Задача на импорт истории добавлена в очередь"}
