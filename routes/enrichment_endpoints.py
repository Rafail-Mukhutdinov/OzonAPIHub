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
from db.database import Order, OrderPosting, OrderProduct, SessionLocal, get_db
from services.enrichment import enrich_posting_from_ozon

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/orders/fbo", tags=["enrichment"])

# Конфигурация
RECENT_WINDOW_HOURS = int(os.getenv('RECENT_WINDOW_HOURS', '48'))
ENRICH_CONCURRENCY = int(os.getenv('ENRICH_CONCURRENCY', '4'))


def _valid_posting_number(pn: str | None) -> bool:
    """Проверяет валидность номера постинга."""
    if not pn:
        return False
    if pn.upper().startswith('TEST-POSTING'):
        return False
    if '-' not in pn:
        return False
    suffix = pn.split('-')[-1]
    return suffix.isdigit()


def _enrich_with_new_session(posting_number: str):
    """Вспомогательная функция для обогащения в новой сессии."""
    session = SessionLocal()
    try:
        return enrich_posting_from_ozon(posting_number, session)
    finally:
        session.close()


class EnrichPostingIn(BaseModel):
    posting_number: str


class EnrichOrderIn(BaseModel):
    order_number: str


@router.post("/get")
async def enrich_posting(item: EnrichPostingIn, db: Session = Depends(get_db)):
    """
    Обогатить информацию по конкретному постингу из Ozon API.
    Сохранит детали в OrderPosting и OrderProduct таблицы.
    """
    try:
        result = await asyncio.to_thread(_enrich_with_new_session, item.posting_number)
        return result
    except Exception as e:
        logger.error(f"Ошибка обогащения постинга {item.posting_number}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/get_for_order")
async def enrich_order(item: EnrichOrderIn, db: Session = Depends(get_db)):
    """
    Обогатить информацию по всем постингам заказа.
    Собирает постинги из нормализованной таблицы OrderPosting и легаси таблицы Order.
    """
    # Собираем постинги из нормализованной таблицы
    postings_norm = db.query(OrderPosting.posting_number).filter(
        OrderPosting.order_number == item.order_number
    ).all()
    postings_norm = [p[0] for p in postings_norm]
    
    # Собираем легаси постинги по префиксу
    prefix = item.order_number + "-"
    legacy = db.query(Order.posting_number).filter(
        Order.posting_number.like(f"{prefix}%")
    ).all()
    postings_legacy = [p[0] for p in legacy]
    
    # Объединяем и сортируем
    postings = sorted(set(postings_norm) | set(postings_legacy))
    
    # Обогащаем каждый постинг
    results = []
    for pn in postings:
        try:
            res = await asyncio.to_thread(_enrich_with_new_session, pn)
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
async def enrich_recent(limit: int = 100):
    """
    Обогатить недавно созданные постинги (за последние RECENT_WINDOW_HOURS часов).
    Полезно для обновления информации по свежим заказам.
    """
    since_iso = (datetime.utcnow() - timedelta(hours=RECENT_WINDOW_HOURS)).isoformat() + 'Z'
    session = SessionLocal()
    
    try:
        # Собираем из двух таблиц
        fresh_orders = session.query(Order.posting_number).filter(
            Order.created_at >= since_iso
        ).order_by(Order.created_at.desc()).limit(limit).all()
        
        fresh_norm = session.query(OrderPosting.posting_number).filter(
            OrderPosting.created_at >= since_iso
        ).order_by(OrderPosting.created_at.desc()).limit(limit).all()
        
        raw_targets = [o[0] for o in fresh_orders] + [n[0] for n in fresh_norm]
        targets = sorted({pn for pn in raw_targets if _valid_posting_number(pn)})
    finally:
        session.close()
    
    # Обогащаем параллельно с ограничением на concurrency
    results = []
    for pn in targets:
        try:
            res = await asyncio.to_thread(_enrich_with_new_session, pn)
            results.append(res)
        except Exception as e:
            logger.warning(f"Ошибка обогащения недавнего постинга {pn}: {e}")
            results.append({"posting_number": pn, "error": str(e)})
    
    return {"processed": len(targets), "results": results}


@router.post("/enrich_changed_recent")
async def enrich_changed_recent(limit: int = 100):
    """
    Обогатить постинги, у которых изменился статус за последнее время.
    Полезно для синхронизации изменений статусов.
    """
    since_iso = (datetime.utcnow() - timedelta(hours=RECENT_WINDOW_HOURS)).isoformat() + 'Z'
    session = SessionLocal()
    
    try:
        # Берём недавние заказы из legacy таблицы
        recent_orders = session.query(Order).filter(
            Order.created_at >= since_iso
        ).order_by(Order.created_at.desc()).limit(500).all()
        
        candidates = []
        for r in recent_orders:
            pn = r.posting_number
            if not _valid_posting_number(pn):
                continue
            
            # Проверяем, изменился ли статус в нормализованной таблице
            row = session.query(OrderPosting).filter(
                OrderPosting.posting_number == pn
            ).first()
            
            if (row.status if row else None) != r.status:
                candidates.append(pn)
        
        targets = sorted(set(candidates))[:limit]
    finally:
        session.close()
    
    # Обогащаем
    results = []
    for pn in targets:
        try:
            res = await asyncio.to_thread(_enrich_with_new_session, pn)
            results.append(res)
        except Exception as e:
            logger.warning(f"Ошибка обогащения постинга с измененным статусом {pn}: {e}")
            results.append({"posting_number": pn, "error": str(e)})
    
    return {"processed": len(targets), "results": results}
