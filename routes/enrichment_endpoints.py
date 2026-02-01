"""
Эндпоинты для обогащения данных постингов.
"""
import os
import asyncio
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from db.database import Order, OrderPosting, OrderProduct, SessionLocal, get_db, User
from services.enrichment import enrich_posting_from_ozon
from utils.common import valid_posting_number
from utils.auth import get_current_user

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/orders/fbo", tags=["enrichment"])

# Конфигурация
RECENT_WINDOW_HOURS = int(os.getenv('RECENT_WINDOW_HOURS', '48'))
ENRICH_CONCURRENCY = int(os.getenv('ENRICH_CONCURRENCY', '4'))


class EnrichPostingIn(BaseModel):
    posting_number: str


class EnrichOrderIn(BaseModel):
    order_number: str


def _enrich_with_new_session(posting_number: str, user_id: int):
    """
    Вспомогательная функция для обогащения в отдельной сессии (для threading).
    """
    session = SessionLocal()
    try:
        # Получаем пользователя
        user = session.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"User {user_id} not found")
        
        # Запускаем асинхронную функцию в синхронном контексте
        import asyncio
        result = asyncio.run(enrich_posting_from_ozon(posting_number, user, session))
        return result
    finally:
        session.close()


@router.post("/get")
async def enrich_posting(
    item: EnrichPostingIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Обогатить информацию по конкретному постингу из Ozon API.
    Использует Ozon credentials текущего пользователя.
    """
    try:
        result = await enrich_posting_from_ozon(item.posting_number, current_user, db)
        return result
    except Exception as e:
        logger.error(f"Ошибка обогащения постинга {item.posting_number}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/get_for_order")
async def enrich_order(
    item: EnrichOrderIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Обогатить информацию по всем постингам заказа.
    Собирает постинги из нормализованной таблицы OrderPosting и легаси таблицы Order.
    """
    # Собираем постинги из нормализованной таблицы (только для текущего пользователя)
    postings_norm = db.query(OrderPosting.posting_number).filter(
        OrderPosting.order_number == item.order_number,
        OrderPosting.user_id == current_user.id
    ).all()
    postings_norm = [p[0] for p in postings_norm]
    
    # Собираем легаси постинги по префиксу (только для текущего пользователя)
    prefix = item.order_number + "-"
    legacy = db.query(Order.posting_number).filter(
        Order.posting_number.like(f"{prefix}%"),
        Order.user_id == current_user.id
    ).all()
    postings_legacy = [p[0] for p in legacy]
    
    # Объединяем и сортируем
    postings = sorted(set(postings_norm) | set(postings_legacy))
    
    # Обогащаем каждый постинг
    results = []
    for pn in postings:
        try:
            res = await asyncio.to_thread(_enrich_with_new_session, pn, current_user.id)
            results.append(res)
        except Exception as e:
            logger.warning(f"Ошибка обогащения постинга {pn}: {e}")
            results.append({"posting_number": pn, "error": str(e)})
    
    return {
        "order_number": item.order_number,
        "count": len(postings),
        "results": results
    }


@router.post("/enrich_recent")
async def enrich_recent(
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Обогатить недавно созданные постинги (за последние RECENT_WINDOW_HOURS часов).
    Полезно для обновления информации по свежим заказам текущего пользователя.
    """
    since_iso = (datetime.utcnow() - timedelta(hours=RECENT_WINDOW_HOURS)).isoformat() + 'Z'
    
    # Собираем постинги только текущего пользователя
    fresh_orders = db.query(Order.posting_number).filter(
        Order.created_at >= since_iso,
        Order.user_id == current_user.id
    ).order_by(Order.created_at.desc()).limit(limit).all()
    
    fresh_norm = db.query(OrderPosting.posting_number).filter(
        OrderPosting.created_at >= since_iso,
        OrderPosting.user_id == current_user.id
    ).order_by(OrderPosting.created_at.desc()).limit(limit).all()
    
    raw_targets = [o[0] for o in fresh_orders] + [n[0] for n in fresh_norm]
    targets = sorted({pn for pn in raw_targets if valid_posting_number(pn)})
    
    # Обогащаем параллельно
    results = []
    for pn in targets:
        try:
            res = await asyncio.to_thread(_enrich_with_new_session, pn, current_user.id)
            results.append(res)
        except Exception as e:
            logger.warning(f"Ошибка обогащения недавнего постинга {pn}: {e}")
            results.append({"posting_number": pn, "error": str(e)})
    
    return {"processed": len(targets), "results": results}


@router.post("/enrich_changed_recent")
async def enrich_changed_recent(
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Обогатить постинги, у которых изменился статус за последнее время.
    Полезно для синхронизации изменений статусов текущего пользователя.
    """
    since_iso = (datetime.utcnow() - timedelta(hours=RECENT_WINDOW_HOURS)).isoformat() + 'Z'
    
    # Берём недавние заказы только текущего пользователя
    recent_orders = db.query(Order).filter(
        Order.created_at >= since_iso,
        Order.user_id == current_user.id
    ).order_by(Order.created_at.desc()).limit(500).all()
    
    candidates = []
    for r in recent_orders:
        pn = r.posting_number
        if not valid_posting_number(pn):
            continue
        
        # Проверяем, изменился ли статус в нормализованной таблице
        row = db.query(OrderPosting).filter(
            OrderPosting.posting_number == pn,
            OrderPosting.user_id == current_user.id
        ).first()
        
        if (row.status if row else None) != r.status:
            candidates.append(pn)
    
    targets = sorted(set(candidates))[:limit]
    
    # Обогащаем
    results = []
    for pn in targets:
        try:
            res = await asyncio.to_thread(_enrich_with_new_session, pn, current_user.id)
            results.append(res)
        except Exception as e:
            logger.warning(f"Ошибка обогащения постинга с измененным статусом {pn}: {e}")
            results.append({"posting_number": pn, "error": str(e)})
    
    return {"processed": len(targets), "results": results}
