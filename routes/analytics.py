from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from db.database import OrderPosting, OrderProduct, Order, get_db, User
import asyncio
import logging
from services.enrichment import enrich_posting_from_ozon
from utils.auth import get_current_user

router = APIRouter(prefix="/analytics", tags=["analytics"])
logger = logging.getLogger("OzonAPIHub")

@router.get("/daily_stats")
async def daily_stats(
    since: str, to: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Статистика для графика."""
    raw_data = db.query(Order.posting_number, Order.created_at).filter(
        Order.user_id == current_user.id, Order.created_at >= since, Order.created_at <= to
    ).all()
    norm_data = db.query(OrderPosting.posting_number, OrderPosting.created_at).filter(
        OrderPosting.user_id == current_user.id, OrderPosting.created_at >= since, OrderPosting.created_at <= to
    ).all()

    pn_to_date = {p[0]: p[1][:10] for p in (raw_data + norm_data) if p[0] and p[1]}
    all_pns = list(pn_to_date.keys())
    if not all_pns: return {"data": []}

    stats = {}
    rows = db.query(
        OrderProduct.posting_number,
        func.sum(OrderProduct.quantity).label("items"),
        func.sum(OrderProduct.price * OrderProduct.quantity).label("revenue")
    ).filter(OrderProduct.user_id == current_user.id, OrderProduct.posting_number.in_(all_pns)).group_by(OrderProduct.posting_number).all()

    for r in rows:
        day = pn_to_date.get(r.posting_number)
        if not day: continue
        if day not in stats: stats[day] = {"items": 0, "revenue": 0}
        stats[day]["items"] += int(r.items or 0)
        stats[day]["revenue"] += int(r.revenue or 0)

    result = [{"date": k, "items": v["items"], "revenue": v["revenue"]} for k, v in stats.items()]
    result.sort(key=lambda x: x["date"])
    return {"data": result}

# ПОЛНЫЙ СПИСОК АЛИАСОВ ДЛЯ СОВМЕСТИМОСТИ
@router.get("/sales_today_raw")
@router.get("/sales_range")
@router.get("/sales_report")
async def sales_report_universal(
    since: str, to: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Универсальный отчет, отвечающий на любые запросы аналитики."""
    raw_pns = db.query(Order.posting_number).filter(
        Order.user_id == current_user.id, Order.created_at >= since, Order.created_at <= to
    ).all()
    norm_pns = db.query(OrderPosting.posting_number).filter(
        OrderPosting.user_id == current_user.id, OrderPosting.created_at >= since, OrderPosting.created_at <= to
    ).all()

    all_pns = list(set([p[0] for p in raw_pns if p[0]] + [p[0] for p in norm_pns if p[0]]))
    if not all_pns: return {"items": [], "total_items": 0, "total_orders": 0, "total_amount_raw": 0}

    # Проверка и докачка деталей
    existing_pns = {p[0] for p in db.query(OrderProduct.posting_number).filter(
        OrderProduct.user_id == current_user.id, OrderProduct.posting_number.in_(all_pns)
    ).all()}
    missing = [pn for pn in all_pns if pn not in existing_pns]
    if missing:
        for pn in missing[:50]:
            try: await enrich_posting_from_ozon(pn, current_user, db)
            except: continue

    rows_items = db.query(
        OrderProduct.offer_id, OrderProduct.sku, OrderProduct.name,
        func.sum(OrderProduct.quantity).label("quantity"),
        func.sum(OrderProduct.price * OrderProduct.quantity).label("amount_raw")
    ).filter(OrderProduct.user_id == current_user.id, OrderProduct.posting_number.in_(all_pns)).group_by(OrderProduct.offer_id, OrderProduct.sku, OrderProduct.name).all()

    items = [{"offer_id": r.offer_id, "sku": r.sku, "name": r.name, "quantity": int(r.quantity or 0), "amount_raw": int(r.amount_raw or 0)} for r in rows_items]
    items.sort(key=lambda x: -x["quantity"])

    return {
        "items": items,
        "total_items": sum(i["quantity"] for i in items),
        "total_orders": len(all_pns),
        "total_amount_raw": sum(i["amount_raw"] for i in items)
    }
