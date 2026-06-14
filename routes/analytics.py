from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta, timezone
from db.database import OrderPosting, OrderProduct, Order, get_db, User
import asyncio
import logging
from services.sync import fetch_and_save_orders
from services.enrichment import enrich_posting_from_ozon
from utils.common import valid_posting_number
from utils.auth import get_current_user

router = APIRouter(prefix="/analytics", tags=["analytics"])
logger = logging.getLogger("OzonAPIHub")

def _to_msk_date(iso_str: str) -> str:
    """Превращает UTC строку из БД в дату по Москве (UTC+3)."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", ""))
        msk_dt = dt + timedelta(hours=3)
        return msk_dt.strftime("%Y-%m-%d")
    except:
        return iso_str[:10]

async def _ensure_data_for_range(db: Session, start_iso: str, end_iso: str, user_id: int):
    """Проверяет наличие заказов и докачивает их из API если нужно."""
    has_orders = db.query(Order).filter(Order.user_id == user_id, Order.created_at >= start_iso, Order.created_at <= end_iso).count() > 0
    if not has_orders:
        try:
            res = await asyncio.to_thread(fetch_and_save_orders, start_iso, end_iso, "", 50, 0, True, True, False, user_id, db)
            orders = res.get("orders") or []
            pns = [o.get("posting_number") for o in orders if valid_posting_number(o.get("posting_number"))]
            if pns:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    for pn in pns: await enrich_posting_from_ozon(pn, user, db)
        except: pass

@router.get("/daily_stats")
async def daily_stats(
    since: str, to: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 0. Сначала убеждаемся, что данные за этот период есть в базе
    await _ensure_data_for_range(db, since, to, current_user.id)

    # 1. Собираем все номера постингов и их даты по МСК
    raw_data = db.query(Order.posting_number, Order.created_at).filter(
        Order.user_id == current_user.id, Order.created_at >= since, Order.created_at <= to
    ).all()
    norm_data = db.query(OrderPosting.posting_number, OrderPosting.created_at).filter(
        OrderPosting.user_id == current_user.id, OrderPosting.created_at >= since, OrderPosting.created_at <= to
    ).all()

    pn_to_msk_date = {p[0]: _to_msk_date(p[1]) for p in (raw_data + norm_data) if p[0] and p[1]}
    all_pns = list(pn_to_msk_date.keys())
    if not all_pns: return {"data": []}

    # 2. Группируем
    stats = {}
    product_rows = db.query(
        OrderProduct.posting_number,
        func.sum(OrderProduct.quantity).label("items"),
        func.sum(OrderProduct.price * OrderProduct.quantity).label("revenue")
    ).filter(OrderProduct.user_id == current_user.id, OrderProduct.posting_number.in_(all_pns)).group_by(OrderProduct.posting_number).all()

    for r in product_rows:
        day = pn_to_msk_date.get(r.posting_number)
        if not day: continue
        if day not in stats: stats[day] = {"items": 0, "revenue": 0}
        stats[day]["items"] += int(r.items or 0)
        stats[day]["revenue"] += int(r.revenue or 0)

    result = [{"date": k, "items": v["items"], "revenue": v["revenue"]} for k, v in stats.items()]
    result.sort(key=lambda x: x["date"])
    return {"data": result}

@router.get("/sales_report")
@router.get("/sales_today_raw")
@router.get("/sales_range")
async def sales_report_universal(
    since: str, to: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _ensure_data_for_range(db, since, to, current_user.id)
    raw_pns = db.query(Order.posting_number).filter(Order.user_id == current_user.id, Order.created_at >= since, Order.created_at <= to).all()
    norm_pns = db.query(OrderPosting.posting_number).filter(OrderPosting.user_id == current_user.id, OrderPosting.created_at >= since, OrderPosting.created_at <= to).all()
    all_pns = list(set([p[0] for p in raw_pns if p[0]] + [p[0] for p in norm_pns if p[0]]))
    if not all_pns: return {"items": [], "total_items": 0, "total_orders": 0, "total_amount_raw": 0}

    rows_items = db.query(
        OrderProduct.offer_id, OrderProduct.sku, OrderProduct.name,
        func.sum(OrderProduct.quantity).label("quantity"),
        func.sum(OrderProduct.price * OrderProduct.quantity).label("amount_raw")
    ).filter(OrderProduct.user_id == current_user.id, OrderProduct.posting_number.in_(all_pns)).group_by(OrderProduct.offer_id, OrderProduct.sku, OrderProduct.name).all()

    items = [{"offer_id": r.offer_id, "sku": r.sku, "name": r.name, "quantity": int(r.quantity or 0), "amount_raw": int(r.amount_raw or 0)} for r in rows_items]
    items.sort(key=lambda x: -x["quantity"])
    return {"items": items, "total_items": sum(i["quantity"] for i in items), "total_orders": len(all_pns), "total_amount_raw": sum(i["amount_raw"] for i in items)}
