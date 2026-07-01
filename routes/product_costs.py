"""
Эндпоинты для управления себестоимостью товаров (Product Costs).
Позволяет отслеживать изменение себестоимости во времени для каждого SKU.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional
from db.database import get_db, User, ProductCost, OrderProduct
from utils.auth import get_current_user
from services.costs import set_product_cost, get_costs_history_for_sku, delete_product_cost

router = APIRouter(prefix="/product-costs", tags=["product-costs"])

class ProductCostIn(BaseModel):
    sku: int
    offer_id: Optional[str] = None
    cost_price: float
    effective_from: datetime

class ProductCostOut(BaseModel):
    id: int
    sku: int
    offer_id: Optional[str] = None
    cost_price: float
    effective_from: datetime
    created_at: datetime

    class Config:
        from_attributes = True

@router.post("", response_model=ProductCostOut)
def set_cost(
    cost: ProductCostIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Устанавливает себестоимость товара с определенной даты."""
    return set_product_cost(
        db, 
        user_id=current_user.id,
        sku=cost.sku,
        cost_price=cost.cost_price,
        effective_from=cost.effective_from,
        offer_id=cost.offer_id
    )

@router.get("/history/{sku}", response_model=List[ProductCostOut])
def get_history(
    sku: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Возвращает историю изменения себестоимости для конкретного SKU."""
    return get_costs_history_for_sku(db, user_id=current_user.id, sku=sku)

@router.get("/all", response_model=List[ProductCostOut])
def get_all_costs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Возвращает все записи себестоимости пользователя."""
    return db.query(ProductCost).filter(ProductCost.user_id == current_user.id).order_by(ProductCost.sku, ProductCost.effective_from.desc()).all()

@router.delete("/{cost_id}")
def delete_cost(
    cost_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Удаляет запись о себестоимости."""
    success = delete_product_cost(db, user_id=current_user.id, cost_id=cost_id)
    if not success:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return {"status": "ok"}

@router.get("/products/list")
def get_user_products(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Возвращает список уникальных товаров пользователя с их текущей себестоимостью."""
    from sqlalchemy import func
    from services.costs import get_product_cost
    
    # Получаем уникальные товары
    products_raw = db.query(
        OrderProduct.sku, 
        OrderProduct.name, 
        OrderProduct.offer_id,
        func.max(OrderProduct.image_url).label("image_url")
    ).filter(OrderProduct.user_id == current_user.id).group_by(
        OrderProduct.sku, OrderProduct.name, OrderProduct.offer_id
    ).all()
    
    now = datetime.now()
    result = []
    
    for p in products_raw:
        # Ищем последнюю себестоимость
        current_cost = get_product_cost(db, current_user.id, p.sku, now)
        
        result.append({
            "sku": p.sku,
            "name": p.name,
            "offer_id": p.offer_id,
            "image_url": p.image_url,
            "current_cost": current_cost
        })
    
    # Сортируем: сначала те, где не заполнена себестоимость (0), затем по имени
    result.sort(key=lambda x: (x["current_cost"] > 0, x["name"] or ""))
    
    return {"items": result}
