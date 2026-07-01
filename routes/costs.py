"""
Эндпоинты для управления дополнительными расходами (Costs).
Позволяет пользователям вручную вносить расходы (реклама, упаковка, налоги),
которые затем могут учитываться в итоговой прибыли (Profit).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from db.database import Cost, get_db, User
from utils.auth import get_current_user
from utils.logging_config import log_user_event
from utils.common import normalize_iso

router = APIRouter(prefix="/costs", tags=["costs"])


class CostIn(BaseModel):
    """Модель данных для создания новой записи расхода."""
    type: str                # Категория (например, "Логистика", "Упаковка", "Реклама")
    amount: int              # Сумма в копейках/рублях
    currency: str = "RUB"    # Валюта
    date: str                # Дата расхода (ISO)
    scope_order_number: str | None = None   # Опциональная привязка к заказу
    scope_posting_number: str | None = None # Опциональная привязка к отправлению
    scope_sku: int | None = None            # Опциональная привязка к товару
    scope_offer_id: str | None = None
    notes: str | None = None # Произвольный комментарий


@router.post("")
def add_cost(
    cost: CostIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Создает новую запись о расходе пользователя."""
    log_user_event(current_user.id, f"Добавление расхода: {cost.type} - {cost.amount} {cost.currency}")

    obj = Cost(
        user_id=current_user.id, # Привязка к текущему пользователю
        type=cost.type,
        amount=cost.amount,
        currency=cost.currency,
        date=cost.date,
        scope_order_number=cost.scope_order_number,
        scope_posting_number=cost.scope_posting_number,
        scope_sku=cost.scope_sku,
        scope_offer_id=cost.scope_offer_id,
        notes=cost.notes or "",
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)

    log_user_event(current_user.id, f"Расход сохранен (ID: {obj.id})")
    return {"status": "ok", "id": obj.id}


@router.get("")
def list_costs(
    type: str | None = None,
    since: str | None = None,
    to: str | None = None,
    order_number: str | None = None,
    posting_number: str | None = None,
    sku: int | None = None,
    offer_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Возвращает список расходов пользователя с поддержкой фильтрации и пагинации.
    """
    log_user_event(current_user.id, f"Запрос списка расходов")

    q = db.query(Cost).filter(Cost.user_id == current_user.id)
    
    # Фильтры по категории и датам
    if type: q = q.filter(Cost.type == type)
    
    try:
        since_iso = normalize_iso(since) if since else None
        to_iso = normalize_iso(to) if to else None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    if since_iso: q = q.filter(Cost.date >= since_iso)
    if to_iso: q = q.filter(Cost.date <= to_iso)

    # Фильтры по области применения (Scope)
    if order_number: q = q.filter(Cost.scope_order_number == order_number)
    if posting_number: q = q.filter(Cost.scope_posting_number == posting_number)
    if sku is not None: q = q.filter(Cost.scope_sku == sku)
    if offer_id: q = q.filter(Cost.scope_offer_id == offer_id)
    
    total = q.count()
    # Сортировка: новые сверху
    rows = q.order_by(Cost.date.desc()).offset(offset).limit(min(max(limit, 1), 500)).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": r.id,
                "type": r.type,
                "amount": r.amount,
                "currency": r.currency,
                "date": r.date,
                "scope_order_number": r.scope_order_number,
                "scope_posting_number": r.scope_posting_number,
                "scope_sku": r.scope_sku,
                "scope_offer_id": r.scope_offer_id,
                "notes": r.notes,
            }
            for r in rows
        ]
    }
