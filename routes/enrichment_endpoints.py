"""
Эндпоинты для обогащения данных постингов.
"""
import os
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from db.database import Order, OrderPosting, get_db, User
from services.enrichment import enrich_posting_from_ozon
from utils.common import valid_posting_number
from utils.auth import get_current_user

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/orders/fbo", tags=["enrichment"])

# Конфигурация
RECENT_WINDOW_HOURS = int(os.getenv('RECENT_WINDOW_HOURS', '48'))


class EnrichPostingIn(BaseModel):
    posting_number: str


class EnrichOrderIn(BaseModel):
    order_number: str


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
        # enrich_posting_from_ozon асинхронная, вызываем напрямую
        result = await enrich_posting_from_ozon(item.posting_number, current_user, db)
        return result
    except Exception as e:
        logger.error(f"Ошибка обогащения постинга {item.posting_number} для пользователя {current_user.id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/get_for_order")
async def enrich_order(
    item: EnrichOrderIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Обогатить информацию по всем постингам заказа.
    """
    # SQL-запросы в асинхронной функции оборачиваем в to_thread или делаем функцию синхронной.
    # Здесь удобнее сделать синхронной, но enrich_posting_from_ozon — асинхронная.
    # Поэтому оставляем async def и используем to_thread для запросов.
    
    def get_postings():
        # Собираем постинги из нормализованной таблицы
        postings_norm = db.query(OrderPosting.posting_number).filter(
            OrderPosting.order_number == item.order_number,
            OrderPosting.user_id == current_user.id
        ).all()
        p_norm = [p[0] for p in postings_norm]

        # Собираем легаси постинги
        prefix = item.order_number + "-"
        legacy = db.query(Order.posting_number).filter(
            Order.posting_number.like(f"{prefix}%"),
            Order.user_id == current_user.id
        ).all()
        p_legacy = [p[0] for p in legacy]

        return sorted(set(p_norm) | set(p_legacy))

    postings = await asyncio.to_thread(get_postings)
    
    results = []
    for pn in postings:
        try:
            res = await enrich_posting_from_ozon(pn, current_user, db)
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
    Обогатить недавно созданные постинги текущего пользователя.
    """
    # Заменяем utcnow
    since_dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=RECENT_WINDOW_HOURS)
    since_iso = since_dt.isoformat() + 'Z'
    
    def find_targets():
        fresh_orders = db.query(Order.posting_number).filter(
            Order.created_at >= since_iso,
            Order.user_id == current_user.id
        ).order_by(Order.created_at.desc()).limit(limit).all()

        fresh_norm = db.query(OrderPosting.posting_number).filter(
            OrderPosting.created_at >= since_iso,
            OrderPosting.user_id == current_user.id
        ).order_by(OrderPosting.created_at.desc()).limit(limit).all()

        raw_targets = [o[0] for o in fresh_orders] + [n[0] for n in fresh_norm]
        return sorted({pn for pn in raw_targets if valid_posting_number(pn)})

    targets = await asyncio.to_thread(find_targets)
    
    results = []
    for pn in targets:
        try:
            res = await enrich_posting_from_ozon(pn, current_user, db)
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
    Обогатить постинги, у которых изменился статус.
    """
    since_dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=RECENT_WINDOW_HOURS)
    since_iso = since_dt.isoformat() + 'Z'
    
    def find_changed():
        recent_orders = db.query(Order).filter(
            Order.created_at >= since_iso,
            Order.user_id == current_user.id
        ).order_by(Order.created_at.desc()).limit(500).all()
        
        candidates = []
        for r in recent_orders:
            pn = r.posting_number
            if not valid_posting_number(pn):
                continue

            row = db.query(OrderPosting).filter(
                OrderPosting.posting_number == pn,
                OrderPosting.user_id == current_user.id
            ).first()

            if (row.status if row else None) != r.status:
                candidates.append(pn)
        return sorted(set(candidates))[:limit]

    targets = await asyncio.to_thread(find_changed)
    
    results = []
    for pn in targets:
        try:
            res = await enrich_posting_from_ozon(pn, current_user, db)
            results.append(res)
        except Exception as e:
            logger.warning(f"Ошибка обогащения измененного постинга {pn}: {e}")
            results.append({"posting_number": pn, "error": str(e)})
    
    return {"processed": len(targets), "results": results}
