"""
Эндпоинты администратора (Super Admin).

Все маршруты защищены декларативно через dependencies=[Depends(get_current_admin)]
на уровне роутера — ручные проверки `if not is_admin` больше не нужны.

Phase 0 (Фундамент):
  - GET /admin/stats — консолидированная базовая статистика платформы.

Phase 1 (User Management & Support Toolkit):
  - GET    /admin/users                   — список пользователей (пагинация, фильтры)
  - GET    /admin/users/{id}              — профиль пользователя (User 360°)
  - GET    /admin/users/{id}/logs         — логи действий пользователя
  - PATCH  /admin/users/{id}              — редактирование (is_active, is_demo, is_admin)
  - POST   /admin/users/{id}/block        — блокировка
  - POST   /admin/users/{id}/unblock      — разблокировка
  - DELETE /admin/users/{id}              — soft delete
  - POST   /admin/users/{id}/restore      — восстановление после soft delete
  - DELETE /admin/users/{id}/data         — полная очистка данных маркетплейса

Все чувствительные действия логируются в AdminActionLog.
"""

import os
import logging
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from pydantic import BaseModel, ConfigDict
from datetime import datetime, timezone

from db.database import (
    get_db, User, Order, OrderPosting, OrderProduct, OrderHeader,
    Cost, ProductCost, OzonAccrual, OzonCredential, SyncStatus,
    AdminActionLog,
)
from utils.auth import get_current_admin
from utils.logging_config import log_user_event, logger
from utils.common import get_now_utc

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
)

# ============================================================================
# Pydantic схемы (Phase 1)
# ============================================================================

class AdminUserUpdate(BaseModel):
    """Схема для PATCH /admin/users/{id}."""
    is_active: Optional[bool] = None
    is_demo: Optional[bool] = None
    is_admin: Optional[bool] = None
    subscription_end_date: Optional[datetime] = None


# ============================================================================
# Вспомогательные функции (Phase 1)
# ============================================================================

def _log_admin_action(
    db: Session,
    admin_user_id: int,
    action_type: str,
    target_user_id: Optional[int] = None,
    details: Optional[dict] = None,
):
    """Записывает действие администратора в таблицу AdminActionLog."""
    try:
        log_entry = AdminActionLog(
            admin_user_id=admin_user_id,
            target_user_id=target_user_id,
            action_type=action_type,
            details=details or {},
        )
        db.add(log_entry)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to log admin action: {e}")
        db.rollback()


def _ensure_not_last_admin(db: Session, user_id: int):
    """
    Защита: нельзя снять admin-роль или удалить последнего администратора.
    """
    admin_count = db.query(func.count(User.id)).filter(
        User.is_admin.is_(True),
        User.is_active.is_(True),
        User.deleted_at.is_(None),
    ).scalar() or 0

    if admin_count <= 1:
        target = db.query(User).filter(User.id == user_id).first()
        if target and target.is_admin:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Невозможно: это последний активный администратор в системе."
            )


def _read_user_log_file(user_id: int, limit: int = 100, offset: int = 0, level: Optional[str] = None) -> list[dict]:
    """
    Читает лог-файл пользователя (logs/users/user_{id}.log) с пагинацией и фильтром.
    Возвращает список записей в виде словарей.
    """
    log_path = os.path.join("logs", "users", f"user_{user_id}.log")
    if not os.path.exists(log_path):
        return []

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
    except Exception as e:
        logger.error(f"Failed to read log for user {user_id}: {e}")
        return []

    # Парсим строки. Формат: [2023-10-27 12:00:00] INFO    [logger] Message
    parsed = []
    for line in all_lines:
        line = line.strip()
        if not line:
            continue
        entry = _parse_log_line(line)
        if entry:
            if level and entry["level"].upper() != level.upper():
                continue
            parsed.append(entry)

    # Пагинация: последние записи важнее → берём с конца
    parsed.reverse()

    total = len(parsed)
    page = parsed[offset: offset + limit]

    return page


def _parse_log_line(line: str) -> Optional[dict]:
    """Парсит одну строку лога в структуру. Возвращает None при неудаче."""
    try:
        # [2023-10-27 12:00:00] INFO    [user_1] Message text
        if not line.startswith("["):
            return None

        # Извлекаем дату
        date_end = line.index("]")
        date_str = line[1:date_end]
        rest = line[date_end + 1:].strip()

        # Извлекаем уровень
        parts = rest.split(None, 1)
        if not parts:
            return None
        level = parts[0]
        message = parts[1].strip() if len(parts) > 1 else ""

        # Убираем [logger_name] из начала сообщения, если есть
        if message.startswith("["):
            bracket_end = message.index("]")
            message = message[bracket_end + 1:].strip()

        return {
            "timestamp": date_str,
            "level": level,
            "message": message,
        }
    except (ValueError, IndexError):
        return None


def _serialize_user_brief(user: User, has_credentials: bool = False) -> dict:
    """Краткая сериализация пользователя для списка."""
    return {
        "id": user.id,
        "email": user.email,
        "is_demo": user.is_demo,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "has_credentials": has_credentials,
        "subscription_end_date": user.subscription_end_date.isoformat() if user.subscription_end_date else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "deleted_at": user.deleted_at.isoformat() if user.deleted_at else None,
    }


# ============================================================================
# Phase 0: Базовая статистика
# ============================================================================

@router.get("/stats")
def get_platform_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Консолидированная статистика платформы (только для администраторов).
    Заменяет бывшие разрозненные эндпоинты:
      - GET /stats (main.py)
      - GET /auth/debug/users-count (auth_endpoints.py)
    """
    total_users = db.query(func.count(User.id)).filter(User.deleted_at.is_(None)).scalar() or 0
    active_users = db.query(func.count(User.id)).filter(
        User.is_active.is_(True),
        User.deleted_at.is_(None),
    ).scalar() or 0
    total_orders = db.query(func.count(Order.id)).scalar() or 0
    total_postings = db.query(func.count(OrderPosting.id)).scalar() or 0
    total_accruals = db.query(func.count(OzonAccrual.id)).scalar() or 0

    return {
        "users": {
            "total": total_users,
            "active": active_users,
        },
        "data": {
            "orders": total_orders,
            "order_postings": total_postings,
            "ozon_accruals": total_accruals,
        },
        "mode": "distributed_workers",
    }


# ============================================================================
# Phase 1: User Management
# ============================================================================

@router.get("/users")
def get_users(
    search: Optional[str] = Query(None, description="Поиск по email или ID"),
    is_active: Optional[bool] = Query(None, description="Фильтр: активные/заблокированные"),
    is_demo: Optional[bool] = Query(None, description="Фильтр: demo/paid"),
    is_admin: Optional[bool] = Query(None, description="Фильтр: администраторы"),
    has_credentials: Optional[bool] = Query(None, description="Фильтр: есть/нет Ozon ключи"),
    deleted: bool = Query(False, description="Показывать удалённые (soft delete)"),
    sort: str = Query("created_at", description="Сортировка: created_at, email, last_activity"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Список пользователей с пагинацией и фильтрами.
    Агрегации выполняются одним запросом через JOIN (без N+1).
    """
    # Базовый запрос
    query = db.query(User)

    # Фильтр удалённых
    if deleted:
        query = query.filter(User.deleted_at.is_not(None))
    else:
        query = query.filter(User.deleted_at.is_(None))

    # Поиск
    if search:
        search_term = f"%{search}%"
        # Если search — число, ищем и по ID
        if search.isdigit():
            query = query.filter(or_(
                User.email.ilike(search_term),
                User.id == int(search),
            ))
        else:
            query = query.filter(User.email.ilike(search_term))

    # Точные фильтры
    if is_active is not None:
        query = query.filter(User.is_active.is_(is_active))
    if is_demo is not None:
        query = query.filter(User.is_demo.is_(is_demo))
    if is_admin is not None:
        query = query.filter(User.is_admin.is_(is_admin))

    # Сортировка
    if sort == "email":
        query = query.order_by(User.email)
    elif sort == "last_activity":
        # Сортировка по последней активности синхронизации (LEFT JOIN)
        query = query.outerjoin(SyncStatus, SyncStatus.user_id == User.id)
        query = query.order_by(SyncStatus.last_sync_attempt_at.desc().nullslast())
    else:  # created_at
        query = query.order_by(User.created_at.desc())

    # Общее количество (до пагинации)
    total = query.count()

    # Пагинация
    offset = (page - 1) * limit
    users = query.offset(offset).limit(limit).all()

    # Получаем ID пользователей с credentials одним запросом
    user_ids_with_creds = set()
    if users:
        user_ids = [u.id for u in users]
        cred_rows = db.query(OzonCredential.user_id).filter(
            OzonCredential.user_id.in_(user_ids)
        ).distinct().all()
        user_ids_with_creds = {row[0] for row in cred_rows}

    # Фильтр по has_credentials (пост-фильтрация, т.к. это производное поле)
    result_users = []
    for u in users:
        u_has_creds = u.id in user_ids_with_creds
        if has_credentials is not None and u_has_creds != has_credentials:
            continue
        result_users.append(_serialize_user_brief(u, has_credentials=u_has_creds))

    return {
        "items": result_users,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit > 0 else 0,
    }


@router.get("/users/{user_id}")
def get_user_detail(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Профиль пользователя (User 360°): счётчики по всем таблицам,
    статус синхронизации, статус credentials.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Счётчики данных (один запрос на таблицу)
    orders_count = db.query(func.count(Order.id)).filter(Order.user_id == user_id).scalar() or 0
    postings_count = db.query(func.count(OrderPosting.id)).filter(OrderPosting.user_id == user_id).scalar() or 0
    products_count = db.query(func.count(OrderProduct.id)).filter(OrderProduct.user_id == user_id).scalar() or 0
    accruals_count = db.query(func.count(OzonAccrual.id)).filter(OzonAccrual.user_id == user_id).scalar() or 0
    costs_count = db.query(func.count(Cost.id)).filter(Cost.user_id == user_id).scalar() or 0
    product_costs_count = db.query(func.count(ProductCost.id)).filter(ProductCost.user_id == user_id).scalar() or 0

    # Credentials (без расшифровки ключей!)
    creds = db.query(OzonCredential).filter(OzonCredential.user_id == user_id).all()
    credentials_info = [{
        "id": c.id,
        "name": c.name,
        "marketplace": c.marketplace,
        "is_active": c.is_active,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    } for c in creds]

    # Статус синхронизации
    sync_status = db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
    sync_info = None
    if sync_status:
        sync_info = {
            "is_syncing": sync_status.is_syncing,
            "status_message": sync_status.status_message,
            "sync_started_at": sync_status.sync_started_at.isoformat() if sync_status.sync_started_at else None,
            "sync_completed_at": sync_status.sync_completed_at.isoformat() if sync_status.sync_completed_at else None,
            "last_sync_attempt_at": sync_status.last_sync_attempt_at.isoformat() if sync_status.last_sync_attempt_at else None,
            "total_records_synced": sync_status.total_records_synced,
            "backfill_is_complete": sync_status.backfill_is_complete,
        }

    return {
        "user": _serialize_user_brief(user, has_credentials=len(credentials_info) > 0),
        "data_counts": {
            "orders": orders_count,
            "order_postings": postings_count,
            "order_products": products_count,
            "ozon_accruals": accruals_count,
            "costs": costs_count,
            "product_costs": product_costs_count,
        },
        "credentials": credentials_info,
        "sync_status": sync_info,
    }


@router.get("/users/{user_id}/logs")
def get_user_logs(
    user_id: int,
    level: Optional[str] = Query(None, description="Фильтр: info, warning, error"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Логи действий пользователя (User Event Logs).
    Читает файл logs/users/user_{id}.log, созданный функцией log_user_event().
    """
    # Проверяем, что пользователь существует
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    entries = _read_user_log_file(user_id, limit=limit, offset=offset, level=level)

    return {
        "user_id": user_id,
        "entries": entries,
        "limit": limit,
        "offset": offset,
        "level_filter": level,
    }


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Редактирование пользователя: is_active, is_demo, is_admin, subscription_end_date.
    """
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    changes = {}

    if payload.is_admin is not None and payload.is_admin != user.is_admin:
        # Снятие admin-роли — проверка последнего админа
        if not payload.is_admin:
            _ensure_not_last_admin(db, user_id)
        user.is_admin = payload.is_admin
        changes["is_admin"] = payload.is_admin

    if payload.is_active is not None and payload.is_active != user.is_active:
        if not payload.is_active and user.is_admin:
            _ensure_not_last_admin(db, user_id)
        user.is_active = payload.is_active
        changes["is_active"] = payload.is_active

    if payload.is_demo is not None and payload.is_demo != user.is_demo:
        user.is_demo = payload.is_demo
        changes["is_demo"] = payload.is_demo

    if payload.subscription_end_date is not None:
        user.subscription_end_date = payload.subscription_end_date.replace(tzinfo=None)
        changes["subscription_end_date"] = user.subscription_end_date.isoformat()

    if not changes:
        return {"status": "ok", "message": "Нет изменений", "changes": {}}

    db.commit()

    # Логируем действие админа
    _log_admin_action(
        db,
        admin_user_id=current_user.id,
        action_type="update_user",
        target_user_id=user_id,
        details=changes,
    )

    log_user_event(user_id, f"Администратор обновил профиль: {changes}")

    return {"status": "ok", "changes": changes}


@router.post("/users/{user_id}/block")
def block_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Блокировка пользователя (is_active = False)."""
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if not user.is_active:
        return {"status": "ok", "message": "Пользователь уже заблокирован"}

    # Защита последнего админа
    if user.is_admin:
        _ensure_not_last_admin(db, user_id)

    user.is_active = False
    db.commit()

    _log_admin_action(
        db,
        admin_user_id=current_user.id,
        action_type="block_user",
        target_user_id=user_id,
    )

    log_user_event(user_id, "Аккаунт заблокирован администратором.", "warning")

    return {"status": "ok", "message": "Пользователь заблокирован"}


@router.post("/users/{user_id}/unblock")
def unblock_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Разблокировка пользователя (is_active = True)."""
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user.is_active:
        return {"status": "ok", "message": "Пользователь уже активен"}

    user.is_active = True
    db.commit()

    _log_admin_action(
        db,
        admin_user_id=current_user.id,
        action_type="unblock_user",
        target_user_id=user_id,
    )

    log_user_event(user_id, "Аккаунт разблокирован администратором.")

    return {"status": "ok", "message": "Пользователь разблокирован"}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Soft delete пользователя (deleted_at = now()).
    Данные остаются в БД, но пользователь не может войти.
    """
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Защита последнего админа
    if user.is_admin:
        _ensure_not_last_admin(db, user_id)

    user.deleted_at = func.now()
    user.is_active = False
    db.commit()

    _log_admin_action(
        db,
        admin_user_id=current_user.id,
        action_type="delete_user",
        target_user_id=user_id,
    )

    log_user_event(user_id, "Аккаунт удалён администратором (soft delete).", "warning")

    return {"status": "ok", "message": "Пользователь удалён (soft delete)"}


@router.post("/users/{user_id}/restore")
def restore_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Восстановление пользователя после soft delete."""
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_not(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Удалённый пользователь не найден")

    user.deleted_at = None
    user.is_active = True
    db.commit()

    _log_admin_action(
        db,
        admin_user_id=current_user.id,
        action_type="restore_user",
        target_user_id=user_id,
    )

    log_user_event(user_id, "Аккаунт восстановлен администратором.")

    return {"status": "ok", "message": "Пользователь восстановлен"}


@router.delete("/users/{user_id}/data")
def purge_user_data(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Полная очистка данных маркетплейса пользователя.
    Удаляет записи из всех таблиц с данными Ozon.
    Логика аналогична /auth/me/data/purge (которая уже корректно чистит 7 таблиц).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Подсчитываем удаляемые записи для отчёта
    counts = {
        "order_products": db.query(func.count(OrderProduct.id)).filter(OrderProduct.user_id == user_id).scalar() or 0,
        "order_postings": db.query(func.count(OrderPosting.id)).filter(OrderPosting.user_id == user_id).scalar() or 0,
        "order_headers": db.query(func.count(OrderHeader.id)).filter(OrderHeader.user_id == user_id).scalar() or 0,
        "orders": db.query(func.count(Order.id)).filter(Order.user_id == user_id).scalar() or 0,
        "costs": db.query(func.count(Cost.id)).filter(Cost.user_id == user_id).scalar() or 0,
        "ozon_accruals": db.query(func.count(OzonAccrual.id)).filter(OzonAccrual.user_id == user_id).scalar() or 0,
        "product_costs": db.query(func.count(ProductCost.id)).filter(ProductCost.user_id == user_id).scalar() or 0,
    }

    # Удаление (порядок важен из-за FK)
    db.query(OrderProduct).filter(OrderProduct.user_id == user_id).delete()
    db.query(OrderPosting).filter(OrderPosting.user_id == user_id).delete()
    db.query(OrderHeader).filter(OrderHeader.user_id == user_id).delete()
    db.query(Order).filter(Order.user_id == user_id).delete()
    db.query(Cost).filter(Cost.user_id == user_id).delete()
    db.query(OzonAccrual).filter(OzonAccrual.user_id == user_id).delete()
    db.query(ProductCost).filter(ProductCost.user_id == user_id).delete()
    db.commit()

    _log_admin_action(
        db,
        admin_user_id=current_user.id,
        action_type="purge_data",
        target_user_id=user_id,
        details=counts,
    )

    log_user_event(
        user_id,
        "ВНИМАНИЕ: Все данные маркетплейса удалены администратором.",
        "warning"
    )

    return {"status": "ok", "deleted_counts": counts}


# ============================================================================
# Phase 2: Sync Failures Dashboard & Sync Control
# ============================================================================

@router.get("/health/sync-failures")
def get_sync_failures(
    stuck_minutes: int = Query(30, ge=5, le=1440, description="Порог «зависшей» синхронизации (в минутах)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Единый список проблем синхронизации по всем пользователям.
    Позволяет проактивно выявлять и чинить ошибки до жалоб пользователей.

    Критерии попадания в список:
      - status_message содержит 'error', 'ошибка' или 'interrupted'
      - ИЛИ is_syncing=True дольше stuck_minutes (зависшая синхронизация)
    """
    threshold = get_now_utc() - _timedelta(minutes=stuck_minutes)

    statuses = db.query(SyncStatus).filter(
        or_(
            SyncStatus.status_message.ilike("%error%"),
            SyncStatus.status_message.ilike("%ошибка%"),
            SyncStatus.status_message.ilike("%interrupted%"),
            (SyncStatus.is_syncing.is_(True)) & (SyncStatus.last_sync_attempt_at < threshold),
        )
    ).order_by(SyncStatus.last_sync_attempt_at.desc().nullslast()).all()

    # Получаем email пользователей одним запросом
    user_ids = [s.user_id for s in statuses]
    users_map = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        users_map = {u.id: u for u in users}

    result = []
    for s in statuses:
        u = users_map.get(s.user_id)
        is_stuck = s.is_syncing and s.last_sync_attempt_at and (s.last_sync_attempt_at < threshold)
        result.append({
            "user_id": s.user_id,
            "user_email": u.email if u else None,
            "user_is_active": u.is_active if u else False,
            "is_syncing": s.is_syncing,
            "is_stuck": bool(is_stuck),
            "status_message": s.status_message,
            "sync_started_at": s.sync_started_at.isoformat() if s.sync_started_at else None,
            "sync_completed_at": s.sync_completed_at.isoformat() if s.sync_completed_at else None,
            "last_sync_attempt_at": s.last_sync_attempt_at.isoformat() if s.last_sync_attempt_at else None,
        })

    return {
        "total": len(result),
        "errors": [r for r in result if not r["is_stuck"]],
        "stuck": [r for r in result if r["is_stuck"]],
        "stuck_threshold_minutes": stuck_minutes,
    }


def _timedelta(minutes: int = 0, days: int = 0):
    """Обёртка для создания timedelta (импортируется локально во избежание коллизий)."""
    from datetime import timedelta
    return timedelta(minutes=minutes, days=days)


@router.post("/users/{user_id}/sync/trigger")
async def trigger_user_sync(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Запускает обычную (лёгкую) синхронизацию для пользователя.
    Аналог пользовательского /sync/manual, но от имени администратора.
    """
    from services.sync import sync_user_orders

    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Проверяем, не идёт ли уже синхронизация (атомарная блокировка)
    status_row = db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
    if not status_row:
        status_row = SyncStatus(user_id=user_id, status_message="admin_trigger_started")
        db.add(status_row)

    if status_row.is_syncing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Синхронизация уже выполняется. Используйте /reset-stuck для сброса зависшего флага."
        )

    now = get_now_utc()
    updated = db.query(SyncStatus).filter(
        SyncStatus.user_id == user_id,
        SyncStatus.is_syncing == False,
    ).update({
        SyncStatus.is_syncing: True,
        SyncStatus.sync_started_at: now,
        SyncStatus.last_sync_attempt_at: now,
        SyncStatus.status_message: "admin_trigger_started",
    }, synchronize_session=False)
    db.commit()

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Не удалось захватить блокировку синхронизации (гонка)."
        )

    try:
        found_new = await sync_user_orders(user, db)
        status_row.is_syncing = False
        status_row.status_message = "ok"
        status_row.sync_completed_at = get_now_utc()
        db.commit()

        _log_admin_action(
            db, admin_user_id=current_user.id, action_type="trigger_sync",
            target_user_id=user_id, details={"found_new": found_new},
        )
        log_user_event(user_id, "Администратор запустил синхронизацию.")

        return {"status": "ok", "new_orders_found": found_new}
    except Exception as e:
        db.rollback()
        status_row = db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
        if status_row:
            status_row.is_syncing = False
            status_row.status_message = "error: admin trigger failed"
            db.commit()
        logger.error(f"Admin trigger sync failed for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при синхронизации. Подробности в журнале.")


@router.post("/users/{user_id}/sync/force-backfill")
async def force_user_backfill(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Запускает принудительный полный backfill (365 дней) через ARQ-воркер.
    Аналог пользовательского /sync/initial/force.
    """
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    arq_pool = getattr(request.app.state, "arq_pool", None)
    if arq_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Сервис очередей временно недоступен. Проверьте подключение Redis."
        )

    sync_status = db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
    if not sync_status:
        sync_status = SyncStatus(user_id=user_id)
        db.add(sync_status)

    # Сбрасываем курсор для принудительного перезапуска
    sync_status.backfill_is_complete = False
    sync_status.is_syncing = True
    sync_status.backfill_cursor = None
    sync_status.backfill_from = None
    sync_status.status_message = "admin_force_backfill_queued"
    sync_status.sync_started_at = get_now_utc()
    db.commit()

    try:
        job_id = f"backfill_user_{user_id}_{int(datetime.now(timezone.utc).timestamp())}"
        await arq_pool.enqueue_job("initial_backfill_task", user_id, _job_id=job_id)
    except Exception as e:
        logger.error(f"Failed to enqueue backfill for user {user_id}: {e}")
        sync_status.is_syncing = False
        sync_status.status_message = "error: enqueue failed"
        db.commit()
        raise HTTPException(status_code=500, detail="Не удалось поставить задачу в очередь.")

    _log_admin_action(
        db, admin_user_id=current_user.id, action_type="force_backfill",
        target_user_id=user_id,
    )
    log_user_event(user_id, "Администратор запустил принудительный backfill.", "warning")

    return {"status": "ok", "message": "Задача backfill добавлена в очередь"}


@router.post("/users/{user_id}/sync/reset-stuck")
def reset_stuck_sync(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Сбрасывает зависший флаг is_syncing=True.
    Применяется, когда синхронизация завершилась аварийно и флаг не снялся.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    sync_status = db.query(SyncStatus).filter(SyncStatus.user_id == user_id).first()
    if not sync_status:
        raise HTTPException(status_code=404, detail="Статус синхронизации не найден")

    if not sync_status.is_syncing:
        return {"status": "ok", "message": "Флаг is_syncing уже сброшен"}

    was_syncing_since = sync_status.sync_started_at
    sync_status.is_syncing = False
    sync_status.status_message = "reset by admin"
    db.commit()

    _log_admin_action(
        db, admin_user_id=current_user.id, action_type="reset_stuck",
        target_user_id=user_id,
        details={"was_syncing_since": was_syncing_since.isoformat() if was_syncing_since else None},
    )
    log_user_event(user_id, "Администратор сбросил зависший флаг синхронизации.", "warning")

    return {"status": "ok", "message": "Флаг is_syncing сброшен"}


@router.post("/users/{user_id}/sync/history")
async def trigger_history_sync(
    user_id: int,
    request: Request,
    start: str,
    end: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Докачка данных за конкретный период через ARQ-воркер.
    Аналог пользовательского /sync/history, но от имени администратора.

    Параметры:
      - start: ISO-дата начала (обязательный)
      - end: ISO-дата конца (необязательный, по умолчанию — сейчас)
    """
    from utils.common import parse_ozon_datetime

    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    try:
        start_dt = parse_ozon_datetime(start)
        if start_dt is None:
            raise ValueError("Некорректная дата начала")
        end_dt = parse_ozon_datetime(end) if end else get_now_utc()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Неверный формат даты. Используйте ISO 8601.")

    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail="Дата конца не может быть раньше даты начала")

    arq_pool = getattr(request.app.state, "arq_pool", None)
    if arq_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Сервис очередей недоступен."
        )

    # Приводим к наивному UTC для передачи в воркер
    start_naive = start_dt.astimezone(timezone.utc).replace(tzinfo=None)
    end_naive = end_dt.astimezone(timezone.utc).replace(tzinfo=None)

    try:
        await arq_pool.enqueue_job(
            "history_sync_task",
            user_id,
            start_naive.isoformat(),
            end_naive.isoformat(),
        )
    except Exception as e:
        logger.error(f"Failed to enqueue history sync for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Не удалось поставить задачу в очередь.")

    _log_admin_action(
        db, admin_user_id=current_user.id, action_type="history_sync",
        target_user_id=user_id,
        details={"start": start_naive.isoformat(), "end": end_naive.isoformat()},
    )
    log_user_event(
        user_id,
        f"Администратор запустил докачку периода: {start_naive.date()} — {end_naive.date()}."
    )

    return {
        "status": "ok",
        "message": "Задача на импорт истории добавлена в очередь",
        "period": {"start": start_naive.isoformat(), "end": end_naive.isoformat()},
    }


@router.get("/audit-logs")
def get_audit_logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Журнал аудита действий администраторов.
    """
    query = db.query(AdminActionLog)
    if action_type:
        query = query.filter(AdminActionLog.action_type == action_type)

    total = query.count()
    rows = query.order_by(AdminActionLog.created_at.desc()).offset(offset).limit(limit).all()

    # Предзагрузка email админов и таргетов
    admin_ids = {r.admin_user_id for r in rows if r.admin_user_id}
    target_ids = {r.target_user_id for r in rows if r.target_user_id}
    all_user_ids = admin_ids | target_ids

    users_map = {}
    if all_user_ids:
        users = db.query(User.id, User.email).filter(User.id.in_(all_user_ids)).all()
        users_map = {u.id: u.email for u in users}

    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "admin_user_id": r.admin_user_id,
                "admin_email": users_map.get(r.admin_user_id),
                "target_user_id": r.target_user_id,
                "target_user_email": users_map.get(r.target_user_id),
                "action_type": r.action_type,
                "details": r.details,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


# ============================================================================
# Phase 3: Global Analytics
# ============================================================================

@router.get("/analytics/gmv")
def get_platform_gmv(
    since: str = Query(..., description="ISO дата начала периода"),
    to: str = Query(..., description="ISO дата конца периода"),
    group_by: str = Query("day", description="Группировка: day, week, month"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Platform GMV (Gross Merchandise Value) — сколько денег проходит через сервис.
    Агрегирует SUM(price * quantity) из OrderProduct по ВСЕМ пользователям.
    """
    from utils.common import parse_ozon_datetime

    try:
        since_dt = parse_ozon_datetime(since)
        to_dt = parse_ozon_datetime(to)
        if not since_dt or not to_dt:
            raise ValueError("Invalid date")
        since_utc = since_dt.astimezone(timezone.utc).replace(tzinfo=None)
        to_utc = to_dt.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Неверный формат даты. Используйте ISO 8601.")

    # GMV через JOIN OrderPosting -> OrderProduct (для фильтра по дате)
    query = db.query(
        func.sum(OrderProduct.price * OrderProduct.quantity).label("gmv"),
        func.count(func.distinct(OrderProduct.user_id)).label("sellers_count"),
    ).join(
        OrderPosting, OrderPosting.id == OrderProduct.posting_id
    ).filter(
        OrderPosting.created_at.between(since_utc, to_utc)
    )

    totals = query.one()
    total_gmv = float(totals.gmv or 0)
    sellers_count = int(totals.sellers_count or 0)

    # Динамика по period_bucket
    if group_by == "month":
        bucket = func.date_trunc("month", OrderPosting.created_at).label("bucket")
    elif group_by == "week":
        bucket = func.date_trunc("week", OrderPosting.created_at).label("bucket")
    else:
        bucket = func.date_trunc("day", OrderPosting.created_at).label("bucket")

    dynamic_q = db.query(
        bucket,
        func.sum(OrderProduct.price * OrderProduct.quantity).label("gmv"),
        func.count(func.distinct(OrderProduct.user_id)).label("sellers"),
    ).join(
        OrderPosting, OrderPosting.id == OrderProduct.posting_id
    ).filter(
        OrderPosting.created_at.between(since_utc, to_utc)
    ).group_by(bucket).order_by(bucket).all()

    return {
        "since": since_utc.isoformat(),
        "to": to_utc.isoformat(),
        "group_by": group_by,
        "total_gmv": round(total_gmv, 2),
        "sellers_count": sellers_count,
        "dynamic": [
            {
                "period": row.bucket.isoformat() if row.bucket else None,
                "gmv": round(float(row.gmv or 0), 2),
                "sellers": int(row.sellers or 0),
            }
            for row in dynamic_q
        ],
    }


@router.get("/analytics/growth")
def get_growth_metrics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Метрики роста платформы: регистрации, активность (DAU/WAU/MAU), churn-детектор.
    """
    now = get_now_utc()

    # 1. Регистрации за последние 30 дней (по дням)
    reg_q = db.query(
        func.date_trunc("day", User.created_at).label("day"),
        func.count(User.id).label("count"),
    ).filter(
        User.created_at >= now - _timedelta(days=30)
    ).group_by("day").order_by("day").all()

    # 2. Активность: DAU/WAU/MAU по last_sync_attempt_at
    dau_threshold = now - _timedelta(days=1)
    wau_threshold = now - _timedelta(days=7)
    mau_threshold = now - _timedelta(days=30)

    active_users = db.query(User).join(
        SyncStatus, SyncStatus.user_id == User.id
    ).filter(
        User.is_active.is_(True),
        User.deleted_at.is_(None),
    )

    dau = active_users.filter(SyncStatus.last_sync_attempt_at >= dau_threshold).count()
    wau = active_users.filter(SyncStatus.last_sync_attempt_at >= wau_threshold).count()
    mau = active_users.filter(SyncStatus.last_sync_attempt_at >= mau_threshold).count()

    # 3. Churn detector: активные пользователи с устаревшей синхронизацией (> 14 дней)
    churn_threshold = now - _timedelta(days=14)
    churned = db.query(User).join(
        SyncStatus, SyncStatus.user_id == User.id
    ).filter(
        User.is_active.is_(True),
        User.deleted_at.is_(None),
        User.is_demo.is_(False),
        or_(
            SyncStatus.last_sync_attempt_at < churn_threshold,
            SyncStatus.last_sync_attempt_at.is_(None),
        )
    ).all()

    return {
        "registrations_30d": [
            {"date": r.day.isoformat() if r.day else None, "count": int(r.count)}
            for r in reg_q
        ],
        "activity": {
            "dau": dau,
            "wau": wau,
            "mau": mau,
        },
        "churn_risk": {
            "count": len(churned),
            "threshold_days": 14,
            "users": _serialize_user_brief_list(churned),
        },
    }


@router.get("/analytics/top-sellers")
def get_top_sellers(
    limit: int = Query(50, ge=1, le=200),
    period_days: int = Query(30, ge=1, le=365, description="Период в днях"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Рейтинг крупнейших продавцов на платформе по GMV.
    """
    now = get_now_utc()
    since = now - _timedelta(days=period_days)

    rows = db.query(
        OrderProduct.user_id,
        func.sum(OrderProduct.price * OrderProduct.quantity).label("gmv"),
        func.sum(OrderProduct.quantity).label("items"),
    ).join(
        OrderPosting, OrderPosting.id == OrderProduct.posting_id
    ).filter(
        OrderPosting.created_at >= since
    ).group_by(OrderProduct.user_id).order_by(func.sum(OrderProduct.price * OrderProduct.quantity).desc()).limit(limit).all()

    # Получаем данные пользователей одним запросом
    user_ids = [r.user_id for r in rows]
    users_map = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        users_map = {u.id: u for u in users}

    result = []
    for i, r in enumerate(rows, 1):
        u = users_map.get(r.user_id)
        result.append({
            "rank": i,
            "user_id": r.user_id,
            "email": u.email if u else None,
            "gmv": round(float(r.gmv or 0), 2),
            "items": int(r.items or 0),
            "is_active": u.is_active if u else False,
        })

    return {
        "period_days": period_days,
        "since": since.isoformat(),
        "total_sellers": len(result),
        "top_sellers": result,
    }


@router.get("/analytics/onboarding-funnel")
def get_onboarding_funnel(
    period_days: int = Query(30, ge=1, le=365, description="Анализировать регистрации за N дней"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Воронка онбординга: показывает, на каком этапе теряются пользователи.
    Этапы: Регистрация → Добавили ключи → Завершили backfill → Активны (есть заказы).
    """
    now = get_now_utc()
    since = now - _timedelta(days=period_days)

    # Этап 1: Зарегистрировались за период
    registered = db.query(User).filter(
        User.created_at >= since,
        User.deleted_at.is_(None),
    ).all()
    registered_ids = {u.id for u in registered}
    registered_count = len(registered_ids)

    if registered_count == 0:
        return {
            "period_days": period_days,
            "stages": [
                {"name": "Регистрация", "count": 0, "conversion": 100.0},
                {"name": "Добавили Ozon ключи", "count": 0, "conversion": 0.0},
                {"name": "Завершили backfill", "count": 0, "conversion": 0.0},
                {"name": "Активны (есть заказы)", "count": 0, "conversion": 0.0},
            ],
        }

    # Этап 2: Добавили Ozon ключи
    with_creds = db.query(OzonCredential.user_id).filter(
        OzonCredential.user_id.in_(registered_ids)
    ).distinct().all()
    with_creds_ids = {r[0] for r in with_creds}
    with_creds_count = len(with_creds_ids)

    # Этап 3: Завершили backfill
    completed_backfill = db.query(SyncStatus.user_id).filter(
        SyncStatus.user_id.in_(registered_ids),
        SyncStatus.backfill_is_complete.is_(True),
    ).all()
    backfill_ids = {r[0] for r in completed_backfill}
    backfill_count = len(backfill_ids)

    # Этап 4: Активны (есть заказы)
    with_orders = db.query(OrderPosting.user_id).filter(
        OrderPosting.user_id.in_(registered_ids)
    ).distinct().all()
    active_ids = {r[0] for r in with_orders}
    active_count = len(active_ids)

    def pct(n):
        return round(n / registered_count * 100, 1) if registered_count > 0 else 0.0

    return {
        "period_days": period_days,
        "total_registered": registered_count,
        "stages": [
            {"name": "Регистрация", "count": registered_count, "conversion": 100.0},
            {"name": "Добавили Ozon ключи", "count": with_creds_count, "conversion": pct(with_creds_count)},
            {"name": "Завершили backfill", "count": backfill_count, "conversion": pct(backfill_count)},
            {"name": "Активны (есть заказы)", "count": active_count, "conversion": pct(active_count)},
        ],
    }


def _serialize_user_brief_list(users: list[User]) -> list[dict]:
    """Сериализация списка пользователей для аналитики."""
    return [
        {
            "id": u.id,
            "email": u.email,
            "is_demo": u.is_demo,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


# ============================================================================
# Phase 4: Impersonation («войти под пользователем»)
# ============================================================================

@router.post("/users/{user_id}/impersonate")
def impersonate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Impersonation: админ получает короткоживущий JWT целевого пользователя,
    чтобы увидеть дашборд его глазами (для поддержки).

    Токен содержит:
      - sub = email целевого пользователя
      - impersonated_by = ID админа (для аудита)

    Ограничения (для frontend):
      - В режиме impersonation НЕ показываются/меняются credentials.
      - Запрещены смена пароля, подписки, удаление данных.

    ВНИМАНИЕ: бэкенд НЕ блокирует эти действия автоматически (это ответственность frontend).
    Бэкенд лишь логирует все действия и сохраняет impersonated_by в request.state.
    """
    from utils.auth import create_access_token
    from datetime import timedelta

    target_user = db.query(User).filter(
        User.id == user_id,
        User.deleted_at.is_(None),
    ).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if not target_user.is_active:
        raise HTTPException(status_code=400, detail="Нельзя войти под заблокированного пользователя")

    if target_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Impersonation других администраторов запрещён."
        )

    # Генерируем короткоживущий токен (10 минут) с claim impersonated_by
    token = create_access_token(
        data={
            "sub": target_user.email,
            "impersonated_by": current_user.id,
            "impersonation_target": target_user.id,
        },
        expires_delta=timedelta(minutes=10),
    )

    # Логируем действие
    _log_admin_action(
        db,
        admin_user_id=current_user.id,
        action_type="impersonate",
        target_user_id=user_id,
        details={"token_ttl_minutes": 10},
    )

    # Тегируем в логе пользователя
    log_user_event(
        user_id,
        f"ВНИМАНИЕ: Администратор {current_user.email} (ID {current_user.id}) вошёл в режим impersonation.",
        "warning",
    )

    logger.info(
        f"Admin {current_user.id} ({current_user.email}) impersonated user {user_id} ({target_user.email})"
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_minutes": 10,
        "impersonated_user": _serialize_user_brief(target_user),
        "warning": "Режим поддержки. Действия ограничены. Сессия истечёт через 10 минут.",
    }


# ============================================================================
# Phase 5: Управление монетизацией
# ============================================================================

class SubscriptionExtendRequest(BaseModel):
    """Схема для POST /admin/users/{id}/subscription/extend."""
    days: int  # Сколько дней добавить (может быть отрицательным для уменьшения)
    keep_demo: bool = False  # Если True, то даже при добавлении дней статус останется Demo
    reason: Optional[str] = None  # Причина (компенсация, тест, и т.д.)


class SubscriptionActivateRequest(BaseModel):
    """Схема для POST /admin/users/{id}/subscription/activate-paid."""
    days: int = 30  # На сколько дней выдать доступ
    make_demo: bool = False  # Если True, устанавливает/возвращает статус Demo
    reason: Optional[str] = None


@router.post("/users/{user_id}/subscription/extend")
def extend_subscription(
    user_id: int,
    payload: SubscriptionExtendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Продление подписки пользователя на N дней.
    Используется для компенсаций, тестовых периодов, партнёрских договорённостей.

    Если подписка уже активна — дни добавляются к текущей дате окончания.
    Если истекла — отсчёт идёт от текущего момента.
    """
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    now = get_now_utc()
    old_end = user.subscription_end_date

    # Если подписка ещё активна — добавляем к текущему концу.
    # Если истекла или её не было — отсчёт от сейчас.
    if user.subscription_end_date and user.subscription_end_date > now:
        user.subscription_end_date = user.subscription_end_date + _timedelta(days=payload.days)
    else:
        user.subscription_end_date = now + _timedelta(days=payload.days)

    # Снимаем demo-флаг только если payload.keep_demo=False (по умолчанию)
    # И если мы добавляем дни (days > 0).
    # Если days=0, просто сохраняем текущий статус, но если keep_demo=False и мы в Demo, ничего не меняем?
    # Нет, логика такая: если keep_demo=False и days != 0, переводим в Premium.
    if not payload.keep_demo and payload.days != 0:
        user.is_demo = False

    db.commit()

    _log_admin_action(
        db,
        admin_user_id=current_user.id,
        action_type="extend_subscription",
        target_user_id=user_id,
        details={
            "days_added": payload.days,
            "keep_demo": payload.keep_demo,
            "old_end_date": old_end.isoformat() if old_end else None,
            "new_end_date": user.subscription_end_date.isoformat() if user.subscription_end_date else None,
            "reason": payload.reason,
        },
    )
    log_user_event(
        user_id,
        f"Администратор продлил подписку на {payload.days} дн. Причина: {payload.reason or 'не указана'}."
    )

    return {
        "status": "ok",
        "subscription_end_date": user.subscription_end_date.isoformat() if user.subscription_end_date else None,
        "is_demo": user.is_demo,
    }


@router.post("/users/{user_id}/subscription/activate-paid")
def activate_paid_subscription(
    user_id: int,
    payload: SubscriptionActivateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Активация подписки (Premium или Demo) без оплаты.
    """
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    now = get_now_utc()
    old_end = user.subscription_end_date
    old_demo = user.is_demo

    user.is_demo = payload.make_demo
    user.subscription_end_date = now + _timedelta(days=payload.days)
    db.commit()

    _log_admin_action(
        db,
        admin_user_id=current_user.id,
        action_type="activate_paid" if not payload.make_demo else "set_demo",
        target_user_id=user_id,
        details={
            "days_granted": payload.days,
            "old_end_date": old_end.isoformat() if old_end else None,
            "new_end_date": user.subscription_end_date.isoformat() if user.subscription_end_date else None,
            "was_demo": old_demo,
            "is_now_demo": user.is_demo,
            "reason": payload.reason,
        },
    )
    log_user_event(
        user_id,
        f"Администратор установил режим {'Demo' if user.is_demo else 'Premium'} на {payload.days} дн. Причина: {payload.reason or 'не указана'}."
    )

    return {
        "status": "ok",
        "subscription_end_date": user.subscription_end_date.isoformat() if user.subscription_end_date else None,
        "is_demo": user.is_demo,
    }


@router.get("/users/{user_id}/subscription/history")
def get_subscription_history(
    user_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    История изменений подписки пользователя.
    Читается из AdminActionLog (action_type IN ['extend_subscription', 'activate_paid']).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    rows = db.query(AdminActionLog).filter(
        AdminActionLog.target_user_id == user_id,
        AdminActionLog.action_type.in_(["extend_subscription", "activate_paid"]),
    ).order_by(AdminActionLog.created_at.desc()).limit(limit).all()

    # Получаем email админов одним запросом
    admin_ids = {r.admin_user_id for r in rows if r.admin_user_id}
    admins_map = {}
    if admin_ids:
        admins = db.query(User).filter(User.id.in_(admin_ids)).all()
        admins_map = {a.id: a.email for a in admins}

    return {
        "user_id": user_id,
        "current_subscription_end_date": user.subscription_end_date.isoformat() if user.subscription_end_date else None,
        "current_is_demo": user.is_demo,
        "history": [
            {
                "id": r.id,
                "action_type": r.action_type,
                "admin_email": admins_map.get(r.admin_user_id, "unknown"),
                "admin_id": r.admin_user_id,
                "details": r.details,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/analytics/monetization")
def get_monetization_metrics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Коммерческая аналитика платформы: соотношение demo/paid,
    конверсия demo → paid, прогноз истечений подписок.
    """
    now = get_now_utc()

    # 1. Распределение пользователей по типам подписки
    total = db.query(func.count(User.id)).filter(User.deleted_at.is_(None)).scalar() or 0
    demo_count = db.query(func.count(User.id)).filter(
        User.deleted_at.is_(None), User.is_demo.is_(True)
    ).scalar() or 0
    paid_active = db.query(func.count(User.id)).filter(
        User.deleted_at.is_(None),
        User.is_demo.is_(False),
        User.subscription_end_date > now,
    ).scalar() or 0
    paid_expired = db.query(func.count(User.id)).filter(
        User.deleted_at.is_(None),
        User.is_demo.is_(False),
        or_(
            User.subscription_end_date <= now,
            User.subscription_end_date.is_(None),
        )
    ).scalar() or 0

    # 2. Конверсия demo → paid (по AdminActionLog)
    demo_to_paid_conversions = db.query(
        func.count(AdminActionLog.id)
    ).filter(
        AdminActionLog.action_type == "activate_paid"
    ).scalar() or 0

    # 3. Прогноз истечений подписок на ближайшие 7/30 дней
    expiring_7d = db.query(func.count(User.id)).filter(
        User.deleted_at.is_(None),
        User.is_demo.is_(False),
        User.subscription_end_date.between(now, now + _timedelta(days=7)),
    ).scalar() or 0

    expiring_30d = db.query(func.count(User.id)).filter(
        User.deleted_at.is_(None),
        User.is_demo.is_(False),
        User.subscription_end_date.between(now, now + _timedelta(days=30)),
    ).scalar() or 0

    # 4. Регистрации за 30 дней (для расчёта конверсии)
    registrations_30d = db.query(func.count(User.id)).filter(
        User.deleted_at.is_(None),
        User.created_at >= now - _timedelta(days=30),
    ).scalar() or 0

    conversion_rate = round(demo_to_paid_conversions / registrations_30d * 100, 1) if registrations_30d > 0 else 0.0

    return {
        "distribution": {
            "total": total,
            "demo": demo_count,
            "paid_active": paid_active,
            "paid_expired": paid_expired,
        },
        "conversion": {
            "demo_to_paid_total": demo_to_paid_conversions,
            "registrations_30d": registrations_30d,
            "conversion_rate_pct": conversion_rate,
        },
        "expiring_soon": {
            "in_7_days": expiring_7d,
            "in_30_days": expiring_30d,
        },
    }


# ============================================================================
# Phase 6: System Health & Integrity
# ============================================================================

@router.get("/health/db-stats")
def get_db_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Database Load Monitor: размеры таблиц, кол-во строк, топ «тяжёлых» пользователей.
    Помогает понять, когда пора шардировать или чистить данные.
    """
    from sqlalchemy import text

    # Размеры таблиц через pg_total_relation_size (только для PostgreSQL)
    table_names = [
        "users", "ozon_credentials", "orders", "order_headers",
        "order_postings", "order_products", "costs", "product_costs",
        "ozon_accruals", "sync_status", "admin_action_logs", "system_settings",
    ]

    table_stats = []
    try:
        for table_name in table_names:
            # Размер таблицы (с индексами)
            size_result = db.execute(
                text("SELECT pg_total_relation_size(:table) as size, pg_size_pretty(pg_total_relation_size(:table)) as size_pretty"),
                {"table": table_name}
            ).fetchone()

            if size_result:
                # Кол-во строк (приблизительно, через pg_class.reltuples для скорости)
                count_result = db.execute(
                    text(f"SELECT COUNT(*) FROM {table_name}")
                ).scalar()
                table_stats.append({
                    "table": table_name,
                    "size_bytes": int(size_result[0] or 0),
                    "size_pretty": size_result[1],
                    "rows": int(count_result or 0),
                })
    except Exception as e:
        logger.warning(f"DB stats query failed (possibly SQLite): {e}")
        # Фоллбек для SQLite — только кол-во строк
        for table_name in table_names:
            try:
                count_result = db.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
                table_stats.append({
                    "table": table_name,
                    "size_bytes": 0,
                    "size_pretty": "N/A (SQLite)",
                    "rows": int(count_result or 0),
                })
            except Exception:
                pass

    # Сортируем по размеру (от большего к меньшему)
    table_stats.sort(key=lambda x: x["size_bytes"], reverse=True)

    # Топ «тяжёлых» пользователей (по кол-ву order_postings)
    heavy_users = db.query(
        OrderPosting.user_id,
        func.count(OrderPosting.id).label("postings"),
        User.email,
    ).outerjoin(
        User, User.id == OrderPosting.user_id
    ).group_by(OrderPosting.user_id, User.email).order_by(
        func.count(OrderPosting.id).desc()
    ).limit(10).all()

    return {
        "tables": table_stats,
        "total_db_size_bytes": sum(t["size_bytes"] for t in table_stats),
        "top_heavy_users": [
            {
                "user_id": r.user_id,
                "email": r.email,
                "order_postings_count": int(r.postings),
            }
            for r in heavy_users
        ],
    }


@router.get("/health/integrity")
def get_data_integrity(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Data Integrity Checker: поиск аномалий в данных.
    Проверяет: «сироты», дубли, рассинхрон между таблицами.
    """
    # 1. OrderProduct без связи с OrderPosting (posting_id IS NULL или не существует)
    orphan_products = db.query(func.count(OrderProduct.id)).filter(
        OrderProduct.posting_id.is_(None)
    ).scalar() or 0

    # 2. Дубли OrderPosting по posting_number (в рамках одного пользователя)
    from sqlalchemy import text
    try:
        duplicate_postings = db.execute(text("""
            SELECT user_id, posting_number, COUNT(*) as cnt
            FROM order_postings
            GROUP BY user_id, posting_number
            HAVING COUNT(*) > 1
            LIMIT 20
        """)).fetchall()
        duplicates_list = [
            {"user_id": r[0], "posting_number": r[1], "count": int(r[2])}
            for r in duplicate_postings
        ]
        duplicates_count = len(duplicates_list)
    except Exception as e:
        logger.warning(f"Duplicates query failed: {e}")
        duplicates_list = []
        duplicates_count = 0

    # 3. Пользователи с is_active=True, но без credentials (не смогут синхронизироваться)
    active_without_creds = db.query(func.count(User.id)).filter(
        User.is_active.is_(True),
        User.deleted_at.is_(None),
        ~User.id.in_(db.query(OzonCredential.user_id).distinct()),
    ).scalar() or 0

    # 4. SyncStatus без соответствующего User (orphan sync_status)
    orphan_sync = db.query(func.count(SyncStatus.id)).filter(
        ~SyncStatus.user_id.in_(db.query(User.id))
    ).scalar() or 0

    # 5. Зависшие флаги is_syncing=True (дублирует Phase 2, но здесь как метрика)
    stuck_syncs = db.query(func.count(SyncStatus.id)).filter(
        SyncStatus.is_syncing.is_(True)
    ).scalar() or 0

    return {
        "issues": {
            "orphan_order_products": orphan_products,
            "duplicate_postings_groups": duplicates_count,
            "active_without_credentials": active_without_creds,
            "orphan_sync_statuses": orphan_sync,
            "stuck_sync_flags": stuck_syncs,
        },
        "duplicate_details": duplicates_list,
        "has_issues": any([
            orphan_products > 0,
            duplicates_count > 0,
            active_without_creds > 0,
            orphan_sync > 0,
            stuck_syncs > 0,
        ]),
    }


@router.get("/health/queue")
def get_queue_health(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """
    Queue & Worker Health: статус ARQ-задач и воркеров.
    Показывает активность синхронизации в реальном времени.
    """
    # 1. Текущие синхронизации (is_syncing=True)
    active_syncs = db.query(SyncStatus).filter(
        SyncStatus.is_syncing.is_(True)
    ).all()

    # 2. ARQ pool статус
    arq_pool = getattr(request.app.state, "arq_pool", None)
    arq_available = arq_pool is not None

    # 3. Задачи backfill в прогрессе
    backfill_in_progress = db.query(func.count(SyncStatus.id)).filter(
        SyncStatus.is_syncing.is_(True),
        SyncStatus.backfill_is_complete.is_(False),
        SyncStatus.backfill_cursor.is_not(None),
    ).scalar() or 0

    # 4. Недавние завершённые синхронизации (за последние 24 часа)
    now = get_now_utc()
    recent_completed = db.query(func.count(SyncStatus.id)).filter(
        SyncStatus.sync_completed_at.is_not(None),
        SyncStatus.sync_completed_at >= now - _timedelta(days=1),
    ).scalar() or 0

    # 5. Среднее время последней синхронизации
    sync_durations = []
    active_with_timing = [s for s in active_syncs if s.sync_started_at]
    for s in active_with_timing:
        if s.sync_started_at:
            # Если ещё идёт — считаем текущую длительность
            duration = (now - s.sync_started_at).total_seconds()
            sync_durations.append(duration)

    avg_active_duration = round(sum(sync_durations) / len(sync_durations)) if sync_durations else 0

    # 6. Детали по активным синхронизациям
    active_details = []
    for s in active_syncs[:20]:  # Ограничиваем 20 записями
        user = db.query(User).filter(User.id == s.user_id).first()
        active_details.append({
            "user_id": s.user_id,
            "user_email": user.email if user else None,
            "status_message": s.status_message,
            "started_at": s.sync_started_at.isoformat() if s.sync_started_at else None,
            "duration_seconds": int((now - s.sync_started_at).total_seconds()) if s.sync_started_at else 0,
            "is_backfill": s.backfill_cursor is not None and not s.backfill_is_complete,
        })

    return {
        "arq_available": arq_available,
        "active_syncs": {
            "count": len(active_syncs),
            "avg_duration_seconds": avg_active_duration,
            "backfill_in_progress": backfill_in_progress,
        },
        "recent_completed_24h": recent_completed,
        "active_details": active_details,
    }
