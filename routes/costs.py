from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from db.database import Cost, get_db, User
from utils.auth import get_current_user

router = APIRouter(prefix="/costs", tags=["costs"])


class CostIn(BaseModel):
    """Модель для создания новой записи расходов."""
    type: str
    amount: int
    currency: str = "RUB"
    date: str
    scope_order_number: str | None = None
    scope_posting_number: str | None = None
    scope_sku: int | None = None
    scope_offer_id: str | None = None
    notes: str | None = None


def _normalize_iso(s: str | None) -> str | None:
    """Нормализует ISO строку для унификации."""
    if not s:
        return None
    try:
        s2 = s.rstrip('Z')
        dt = datetime.fromisoformat(s2)
        dt = dt.replace(microsecond=0)
        return dt.isoformat() + 'Z'
    except Exception:
        raise ValueError(f"Invalid ISO datetime: {s}")


@router.post("")
def add_cost(
    cost: CostIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Добавить новую запись расходов."""
    obj = Cost(
        user_id=current_user.id,  # ФИКС: Привязка к пользователю
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
    Получить список расходов с фильтрацией.
    
    Параметры:
    - type: тип расходов (COGS, logistics, ads, withdrawal, other)
    - since, to: диапазон дат (ISO формат)
    - order_number, posting_number, sku, offer_id: фильтры по объему применения
    - limit, offset: пагинация
    """
    # ФИКС: Обязательная фильтрация по user_id
    q = db.query(Cost).filter(Cost.user_id == current_user.id)
    
    if type:
        q = q.filter(Cost.type == type)
    
    try:
        since_iso = _normalize_iso(since) if since else None
        to_iso = _normalize_iso(to) if to else None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    if since_iso:
        q = q.filter(Cost.date >= since_iso)
    if to_iso:
        q = q.filter(Cost.date <= to_iso)
    if order_number:
        q = q.filter(Cost.scope_order_number == order_number)
    if posting_number:
        q = q.filter(Cost.scope_posting_number == posting_number)
    if sku is not None:
        q = q.filter(Cost.scope_sku == sku)
    if offer_id:
        q = q.filter(Cost.scope_offer_id == offer_id)
    
    total = q.count()
    rows = q.order_by(Cost.date.desc()).offset(offset).limit(min(max(limit, 1), 500)).all()
    
    items = [
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
    
    return {"total": total, "items": items, "limit": limit, "offset": offset}
