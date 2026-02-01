"""
Пример обновления существующих endpoints для SaaS режима.

БЫЛО (SQLite, без мультитенантности):
    @router.get("/orders")
    async def list_orders(db: Session = Depends(get_db)):
        q = db.query(Order)
        ...

СТАЛО (PostgreSQL, SaaS):
    from utils.auth import get_current_user
    
    @router.get("/orders")
    async def list_orders(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
    ):
        # Автоматическая фильтрация по текущему пользователю
        q = db.query(Order).filter(Order.user_id == current_user.id)
        ...
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from db.database import get_db, User, Order, OrderPosting
from utils.auth import get_current_user

router = APIRouter(tags=["saas-examples"])


# ============================================================================
# Пример 1: Список заказов с фильтрацией по пользователю
# ============================================================================

@router.get("/orders/saas-example")
async def list_orders_saas(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # <-- Добавили dependency
):
    """
    Список заказов текущего пользователя.
    
    Требует JWT токен в заголовке:
        Authorization: Bearer <token>
    """
    # Фильтрация только по данным текущего пользователя
    q = db.query(Order).filter(Order.user_id == current_user.id)
    
    total = q.count()
    items = q.offset(offset).limit(limit).all()
    
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": o.id,
                "posting_number": o.posting_number,
                "status": o.status,
                "created_at": o.created_at,
            }
            for o in items
        ]
    }


# ============================================================================
# Пример 2: Создание заказа с привязкой к пользователю
# ============================================================================

@router.post("/orders/saas-example")
async def create_order_saas(
    posting_number: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Создание заказа с автоматической привязкой к текущему пользователю."""
    
    # Автоматически добавляем user_id
    new_order = Order(
        user_id=current_user.id,  # <-- Ключевое изменение
        posting_number=posting_number,
        status="new"
    )
    
    db.add(new_order)
    db.commit()
    db.refresh(new_order)
    
    return {"id": new_order.id, "posting_number": new_order.posting_number}


# ============================================================================
# Пример 3: Работа с Ozon API используя credentials пользователя
# ============================================================================

@router.post("/orders/sync-from-ozon")
async def sync_from_ozon(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Синхронизация заказов из Ozon API.
    
    Использует индивидуальные Ozon credentials пользователя.
    """
    from utils.encryption import get_user_ozon_headers
    from services.ozon import ozon_fbo_list_async
    
    # Получаем заголовки с credentials пользователя
    headers = get_user_ozon_headers(current_user)
    
    # Вызываем Ozon API (нужно обновить ozon.py для приема headers)
    # data = await ozon_fbo_list_async(
    #     filter_dict={},
    #     limit=50,
    #     offset=0,
    #     with_flags={"analytics_data": True, "financial_data": True},
    #     custom_headers=headers  # <-- Передаем кастомные headers
    # )
    
    return {
        "status": "ok",
        "message": "Синхронизация запущена",
        "user_id": current_user.id
    }


# ============================================================================
# Пример 4: Опциональная аутентификация (public + private данные)
# ============================================================================

from typing import Optional

@router.get("/orders/public")
async def public_orders(
    db: Session = Depends(get_db),
    current_user: Optional[User] = None  # Опциональный пользователь
):
    """
    Публичный endpoint с опциональной аутентификацией.
    
    - Без токена: показываем демо-данные
    - С токеном: показываем данные пользователя
    """
    if current_user:
        # Авторизованный пользователь - показываем его данные
        q = db.query(Order).filter(Order.user_id == current_user.id)
    else:
        # Гость - показываем демо-данные
        demo_user = db.query(User).filter(User.is_demo == True).first()
        if demo_user:
            q = db.query(Order).filter(Order.user_id == demo_user.id)
        else:
            return {"items": [], "message": "Demo data not available"}
    
    items = q.limit(10).all()
    return {"items": [{"id": o.id, "posting_number": o.posting_number} for o in items]}


# ============================================================================
# Миграция существующих endpoints - чеклист
# ============================================================================

"""
ДЛЯ КАЖДОГО ENDPOINT В ПРОЕКТЕ:

1. Добавить dependency get_current_user:
   ✓ current_user: User = Depends(get_current_user)

2. Добавить фильтр по user_id во все SELECT запросы:
   ✓ .filter(Model.user_id == current_user.id)

3. Добавить user_id во все INSERT операции:
   ✓ Model(user_id=current_user.id, ...)

4. Обновить вызовы Ozon API для использования credentials пользователя:
   ✓ headers = get_user_ozon_headers(current_user)

5. Обновить фоновые задачи (sync, enrichment):
   ✓ Запускать отдельно для каждого пользователя
   ✓ Или использовать user_id из контекста задачи

6. Добавить проверки на наличие Ozon credentials:
   ✓ if not current_user.ozon_client_id:
         raise HTTPException(400, "Please configure Ozon API keys")

ФАЙЛЫ ДЛЯ ОБНОВЛЕНИЯ:
- routes/orders.py
- routes/analytics.py
- routes/sync_endpoints.py
- routes/enrichment_endpoints.py
- routes/costs.py
- services/ozon.py (добавить параметр custom_headers)
- services/sync.py (добавить user_id в функции)
- services/enrichment.py (добавить user_id в функции)
"""
