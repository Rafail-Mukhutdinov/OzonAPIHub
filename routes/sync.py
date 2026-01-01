from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime
from db.database import get_db, OrderPosting
from services.sync import fetch_and_save_orders, run_enrichment_batch
from utils.common import valid_posting_number
import asyncio

router = APIRouter(prefix="/sync", tags=["sync"])

def _norm_iso(s: str | None) -> str | None:
    if not s:
        return None
    s2 = s.rstrip('Z')
    dt = datetime.fromisoformat(s2)
    return dt.replace(microsecond=0).isoformat() + 'Z'

@router.post("/backfill")
async def backfill(since: str, to: str, enrich: bool = True, db: Session = Depends(get_db)):
    since_iso = _norm_iso(since)
    to_iso = _norm_iso(to)
    res = await asyncio.to_thread(fetch_and_save_orders, since_iso, to_iso)
    enriched = 0
    if enrich:
        # Обогатим новые постинги, которых ещё нет в order_postings
        orders = res.get('orders') or []
        pns = [o.get('posting_number') for o in orders if valid_posting_number(o.get('posting_number'))]
        existing = set([row[0] for row in db.query(OrderPosting.posting_number).filter(OrderPosting.posting_number.in_(pns)).all()])
        targets = [pn for pn in set(pns) if pn not in existing]
        if targets:
            await run_enrichment_batch(targets)
            enriched = len(targets)
    return {"saved": res.get('saved'), "fetched": res.get('fetched'), "enriched": enriched}
