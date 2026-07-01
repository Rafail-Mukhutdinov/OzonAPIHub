from sqlalchemy.orm import Session
from sqlalchemy import desc
from db.database import ProductCost
from datetime import datetime
from typing import List, Optional

def set_product_cost(
    db: Session, 
    user_id: int, 
    sku: int, 
    cost_price: float, 
    effective_from: datetime, 
    offer_id: Optional[str] = None
) -> ProductCost:
    """
    Устанавливает себестоимость товара с определенной даты.
    Если на эту же секунду уже есть запись для этого SKU, она обновляется.
    """
    existing = db.query(ProductCost).filter(
        ProductCost.user_id == user_id,
        ProductCost.sku == sku,
        ProductCost.effective_from == effective_from
    ).first()
    
    if existing:
        existing.cost_price = cost_price
        if offer_id:
            existing.offer_id = offer_id
        db.commit()
        db.refresh(existing)
        return existing
    else:
        new_cost = ProductCost(
            user_id=user_id,
            sku=sku,
            offer_id=offer_id,
            cost_price=cost_price,
            effective_from=effective_from
        )
        db.add(new_cost)
        db.commit()
        db.refresh(new_cost)
        return new_cost

def get_product_cost(db: Session, user_id: int, sku: int, date: datetime) -> float:
    """
    Получает актуальную себестоимость товара на указанную дату.
    Ищет самую свежую запись, где effective_from <= date.
    """
    cost_record = db.query(ProductCost).filter(
        ProductCost.user_id == user_id,
        ProductCost.sku == sku,
        ProductCost.effective_from <= date
    ).order_by(desc(ProductCost.effective_from)).first()
    
    return cost_record.cost_price if cost_record else 0.0

def get_costs_history_for_sku(db: Session, user_id: int, sku: int) -> List[ProductCost]:
    """Возвращает историю изменения себестоимости для конкретного SKU."""
    return db.query(ProductCost).filter(
        ProductCost.user_id == user_id,
        ProductCost.sku == sku
    ).order_by(desc(ProductCost.effective_from)).all()

def delete_product_cost(db: Session, user_id: int, cost_id: int) -> bool:
    """Удаляет запись о себестоимости."""
    cost = db.query(ProductCost).filter(
        ProductCost.id == cost_id,
        ProductCost.user_id == user_id
    ).first()
    if cost:
        db.delete(cost)
        db.commit()
        return True
    return False
