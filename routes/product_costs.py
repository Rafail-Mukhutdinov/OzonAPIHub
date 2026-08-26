"""
Эндпоинты для управления себестоимостью товаров (Product Costs).

Этот модуль позволяет пользователям задавать и отслеживать изменение себестоимости (cost price)
каждого товара (SKU) во времени. Это критически важно для точного расчета чистой прибыли,
так как себестоимость закупки может меняться. Система использует дату продажи заказа,
чтобы сопоставить её с актуальной на тот момент себестоимостью товара.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional
from db.database import get_db, User, ProductCost, OrderProduct
from utils.auth import get_current_user, verify_not_impersonating
from utils.logging_config import log_user_event
from services.costs import set_product_cost, get_costs_history_for_sku, delete_product_cost

# Инициализация роутера с префиксом /product-costs
router = APIRouter(prefix="/product-costs", tags=["product-costs"])

class ProductCostIn(BaseModel):
    """Схема входных данных для установки себестоимости."""
    sku: int                        # Уникальный идентификатор товара в системе Ozon
    offer_id: Optional[str] = None  # Артикул товара в магазине
    cost_price: float               # Цена закупки (себестоимость)
    effective_from: datetime        # Дата, с которой начинает действовать эта цена

class ProductCostOut(BaseModel):
    """Схема выходных данных (ответа сервера) с информацией о себестоимости."""
    id: int                         # ID записи в БД
    sku: int
    offer_id: Optional[str] = None
    cost_price: float
    effective_from: datetime        # Дата начала действия
    created_at: datetime           # Дата создания записи

    class Config:
        from_attributes = True

@router.post("", response_model=ProductCostOut, dependencies=[Depends(verify_not_impersonating)])
def set_cost(
    request: Request,
    cost: ProductCostIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Устанавливает себестоимость товара с определенной даты.
    Если на эту дату уже есть запись для этого SKU, она будет обновлена.
    """
    admin_id = getattr(request.state, "impersonated_by", None)
    result = set_product_cost(
        db, 
        user_id=current_user.id,
        sku=cost.sku,
        cost_price=cost.cost_price,
        effective_from=cost.effective_from,
        offer_id=cost.offer_id
    )
    log_user_event(current_user.id, f"Установлена себестоимость для SKU {cost.sku}: {cost.cost_price}", admin_id=admin_id)
    return result

@router.get("/history/{sku}", response_model=List[ProductCostOut])
def get_history(
    sku: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Возвращает историю изменения себестоимости для конкретного SKU.
    Позволяет увидеть, как менялась цена закупки товара со временем.
    """
    return get_costs_history_for_sku(db, user_id=current_user.id, sku=sku)

@router.get("/all", response_model=List[ProductCostOut])
def get_all_costs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Возвращает все записи себестоимости текущего пользователя.
    Результат отсортирован по SKU и дате действия (сначала новые).
    """
    return db.query(ProductCost).filter(ProductCost.user_id == current_user.id).order_by(ProductCost.sku, ProductCost.effective_from.desc()).all()

@router.delete("/{cost_id}", dependencies=[Depends(verify_not_impersonating)])
def delete_cost(
    request: Request,
    cost_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Удаляет конкретную запись о себестоимости по её ID.
    Если запись не найдена или не принадлежит пользователю, возвращает 404.
    """
    admin_id = getattr(request.state, "impersonated_by", None)
    success = delete_product_cost(db, user_id=current_user.id, cost_id=cost_id)
    if not success:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    log_user_event(current_user.id, f"Удалена запись себестоимости ID {cost_id}", admin_id=admin_id)
    return {"status": "ok"}

@router.get("/products/list")
def get_user_products(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Возвращает агрегированный список всех уникальных товаров пользователя,
    которые когда-либо встречались в его заказах.
    Для каждого товара подтягивается текущая актуальная себестоимость.
    Используется на фронтенде для удобного заполнения справочника цен.
    """
    from sqlalchemy import func
    from services.costs import get_product_cost
    
    # Получаем уникальные SKU и базовую информацию о них из таблицы OrderProduct
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
        # Ищем последнюю (актуальную на текущий момент) себестоимость для этого SKU
        current_cost = get_product_cost(db, current_user.id, p.sku, now)
        
        result.append({
            "sku": p.sku,
            "name": p.name,
            "offer_id": p.offer_id,
            "image_url": p.image_url,
            "current_cost": current_cost
        })
    
    # Сортировка: сначала те товары, для которых себестоимость ещё не задана (0), 
    # чтобы пользователю было проще их найти и заполнить.
    result.sort(key=lambda x: (x["current_cost"] > 0, x["name"] or ""))
    
    return {"items": result}
