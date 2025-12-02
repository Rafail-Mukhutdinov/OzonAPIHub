
import os
import requests
import logging
import asyncio
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from db.database import Order, OrderHeader, OrderPosting, OrderProduct, Cost, get_db, SessionLocal
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

load_dotenv()

# Конфиг из окружения
ENABLE_INITIAL_SYNC = os.getenv('ENABLE_INITIAL_SYNC', 'true').lower() in ('1', 'true', 'yes')
SYNC_INTERVAL_SECONDS = int(os.getenv('SYNC_INTERVAL_SECONDS', '300'))
RECENT_WINDOW_HOURS = int(os.getenv('RECENT_WINDOW_HOURS', '48'))
INITIAL_WINDOW_DAYS = int(os.getenv('INITIAL_WINDOW_DAYS', '365'))
START_DATE_RAW = os.getenv('START_DATE')  # Принудительно задать самую раннюю дату (например: 2025-07-01T00:00:00Z)
HISTORY_WINDOW_DAYS = int(os.getenv('HISTORY_WINDOW_DAYS', '30'))  # Размер окна для ручной исторической загрузки
MONTH_RECONCILE_INTERVAL_SECONDS = int(os.getenv('MONTH_RECONCILE_INTERVAL_SECONDS', '3600'))  # раз в час
MONTH_RECONCILE_MONTHS = int(os.getenv('MONTH_RECONCILE_MONTHS', '3'))  # последние 3 месяца

app = FastAPI()
# Управление уровнем логов: LOG_LEVEL=DEBUG|INFO|WARNING|ERROR|CRITICAL
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
try:
    _lvl = getattr(logging, LOG_LEVEL, logging.INFO)
except Exception:
    _lvl = logging.INFO
logging.basicConfig(level=_lvl)
LOG_OZON_REQUESTS = os.getenv('LOG_OZON_REQUESTS', 'false').lower() in ('1', 'true', 'yes')
ENRICH_RECENT_POSTINGS = os.getenv('ENRICH_RECENT_POSTINGS', 'true').lower() in ('1', 'true', 'yes')
ENRICH_RECENT_LIMIT = int(os.getenv('ENRICH_RECENT_LIMIT', '100'))
ENRICH_CONCURRENCY = int(os.getenv('ENRICH_CONCURRENCY', '4'))
ENRICH_ON_FETCH = os.getenv('ENRICH_ON_FETCH', 'true').lower() in ('1', 'true', 'yes')
ENRICH_ON_FETCH_LIMIT = int(os.getenv('ENRICH_ON_FETCH_LIMIT', '200'))
ENRICH_ON_STATUS_CHANGE = os.getenv('ENRICH_ON_STATUS_CHANGE', 'true').lower() in ('1', 'true', 'yes')
ENRICH_STATUS_CHANGE_LIMIT = int(os.getenv('ENRICH_STATUS_CHANGE_LIMIT', '100'))

def _valid_posting_number(pn: str | None) -> bool:
    """Фильтр валидности постинга: исключаем тестовые и явно некорректные значения."""
    if not pn:
        return False
    if pn.upper().startswith('TEST-POSTING'):
        return False
    if '-' not in pn:
        return False
    suffix = pn.split('-')[-1]
    return suffix.isdigit()

class OrderIn(BaseModel):
    order_id: int
    posting_number: str
    status: str
    created_at: str
    updated_at: str = None
    data: dict

class OrderOut(BaseModel):
    id: int
    order_id: int | None = None
    posting_number: str
    status: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    data: dict | None = None

    class Config:
        from_attributes = True

@app.get("/ping")
async def ping():
    return {"message": "pong"}


def _iso_to_dt(s: str) -> datetime:
    if s is None:
        return None
    try:
        s2 = s.rstrip('Z')
        return datetime.fromisoformat(s2)
    except Exception:
        raise ValueError(f"Invalid ISO datetime: {s}")


def fetch_and_save_orders(since: str = None,
                          to: str = None,
                          status: str = "",
                          limit: int = 50,
                          offset: int = 0,
                          analytics_data: bool = True,
                          financial_data: bool = True,
                          legal_info: bool = False,
                          db: Session = None):
    """
    Синхронная функция: делает запросы к Ozon, сохраняет заказы в БД и возвращает сводку.
    Если передан `db`, использует его, иначе откроет собственную сессию.
    """
    own_session = False
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        # Разбор входных дат и выбор значений по умолчанию
        if not since and not to:
            last = db.query(Order).order_by(Order.created_at.desc()).first()
            if last and last.created_at:
                since_dt = _iso_to_dt(last.created_at)
            else:
                since_dt = datetime.utcnow() - timedelta(days=7)
            to_dt = datetime.utcnow()
        else:
            since_dt = _iso_to_dt(since) if since else None
            to_dt = _iso_to_dt(to) if to else None
            if since_dt and not to_dt:
                to_dt = datetime.utcnow()
            if to_dt and not since_dt:
                since_dt = to_dt - timedelta(days=7)

        if since_dt and to_dt:
            # Нормализуем микросекунды, чтобы избежать ложного превышения лимита года
            since_dt = since_dt.replace(microsecond=0)
            to_dt = to_dt.replace(microsecond=0)
            if to_dt < since_dt:
                raise ValueError('`to` must be after `since`')
            # Проверяем только целые дни, игнорируя микросекундные расхождения
            if (to_dt - since_dt).days > 365:
                raise ValueError('PERIOD_IS_TOO_LONG (max 1 year)')

        since_iso = since_dt.isoformat() + 'Z' if since_dt else None
        to_iso = to_dt.isoformat() + 'Z' if to_dt else None

        client_id = os.getenv("OZON_CLIENT_ID")
        api_key = os.getenv("OZON_API_KEY")
        url = "https://api-seller.ozon.ru/v2/posting/fbo/list"
        headers = {
            "Client-Id": client_id,
            "Api-Key": api_key,
            "Content-Type": "application/json"
        }

        total_saved = 0
        all_orders = []
        current_offset = offset

        while True:
            # Build filter dict only with provided keys to avoid sending empty status
            filter_dict = {}
            if since_iso:
                filter_dict['since'] = since_iso
            if to_iso:
                filter_dict['to'] = to_iso
            if status:
                filter_dict['status'] = status

            body = {
                "dir": "ASC",
                "filter": filter_dict,
                "limit": limit,
                "offset": current_offset,
                "translit": True,
                "with": {
                    "analytics_data": analytics_data,
                    "financial_data": financial_data,
                    "legal_info": legal_info
                }
            }
            if LOG_OZON_REQUESTS:
                logging.debug(f"Ozon request body: {body}")
            response = requests.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
            items = data.get('result', []) or []
            if not items:
                break
            for order in items:
                res = save_order(order, db)
                if res == 'inserted':
                    total_saved += 1
                all_orders.append(order)
            if len(items) < limit:
                break
            current_offset += limit

        # После выгрузки — при необходимости обогатим все полученные постинги сразу
        if ENRICH_ON_FETCH and all_orders:
            try:
                posting_numbers = sorted({o.get('posting_number') for o in all_orders if o.get('posting_number')})
                posting_numbers = posting_numbers[:ENRICH_ON_FETCH_LIMIT]
                sem = asyncio.Semaphore(ENRICH_CONCURRENCY)
                async def _run_enrich(pn):
                    async with sem:
                        await asyncio.to_thread(_enrich_posting_from_ozon, pn, SessionLocal())
                # Запустим синхронно из текущей синхронной функции через временный цикл
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # если уже в асинхронном контексте, создадим задачу и подождём её завершение
                    loop.run_until_complete(asyncio.gather(*(_run_enrich(pn) for pn in posting_numbers)))
                else:
                    asyncio.run(asyncio.gather(*(_run_enrich(pn) for pn in posting_numbers)))
                logging.info(f"Обогащение по результатам выгрузки: обработано={len(posting_numbers)}")
            except Exception as e:
                logging.debug(f"Ошибка обогащения после выгрузки: {e}")
        return {"saved": total_saved, "fetched": len(all_orders), "orders": all_orders}
    finally:
        if own_session:
            db.close()


def _normalize_iso(s: str | None) -> str | None:
    if not s:
        return None
    dt = _iso_to_dt(s)
    dt = dt.replace(microsecond=0)
    return dt.isoformat() + 'Z'


def _to_int(val):
    try:
        if val is None:
            return None
        if isinstance(val, (int,)):
            return val
        if isinstance(val, float):
            return int(round(val))
        # strings like "220.00"
        return int(round(float(str(val).replace(',', '.'))))
    except Exception:
        return None


def _recalc_order_header(db: Session, order_number: str):
    products = db.query(OrderProduct).join(OrderPosting, OrderPosting.posting_number == OrderProduct.posting_number) \
        .filter(OrderPosting.order_number == order_number).all()
    total_payout = sum((_to_int(p.payout) or 0) for p in products)
    total_commission = sum((_to_int(p.commission_amount) or 0) for p in products)
    # dates
    postings = db.query(OrderPosting).filter(OrderPosting.order_number == order_number).all()
    first_created = None
    last_delivery = None
    for p in postings:
        if p.created_at:
            first_created = min(first_created, p.created_at) if first_created else p.created_at
        if p.fact_delivery_date:
            last_delivery = max(last_delivery, p.fact_delivery_date) if last_delivery else p.fact_delivery_date
    hdr = db.query(OrderHeader).filter(OrderHeader.order_number == order_number).first()
    if not hdr:
        hdr = OrderHeader(order_number=order_number)
        db.add(hdr)
    hdr.first_created_at = first_created
    hdr.last_delivery_at = last_delivery
    hdr.total_payout = total_payout
    hdr.total_commission = total_commission
    db.commit()


def _enrich_posting_from_ozon(posting_number: str, db: Session):
    client_id = os.getenv("OZON_CLIENT_ID")
    api_key = os.getenv("OZON_API_KEY")
    if not client_id or not api_key:
        raise HTTPException(status_code=500, detail="OZON credentials not configured")
    url = "https://api-seller.ozon.ru/v2/posting/fbo/get"
    headers = {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }
    body = {
        "posting_number": posting_number,
        "translit": True,
        "with": {
            "analytics_data": True,
            "financial_data": True,
            "legal_info": False,
        },
    }
    r = requests.post(url, headers=headers, json=body, timeout=60)
    r.raise_for_status()
    data = r.json().get("result")
    if not data:
        return {"status": "no_result"}

    order_number = data.get("order_number")
    # upsert OrderPosting
    op = db.query(OrderPosting).filter(OrderPosting.posting_number == posting_number).first()
    if not op:
        op = OrderPosting(posting_number=posting_number)
        db.add(op)
    op.order_number = order_number
    op.status = data.get("status")
    op.created_at = data.get("created_at")
    op.in_process_at = data.get("in_process_at")
    op.fact_delivery_date = data.get("fact_delivery_date")
    op.substatus = data.get("substatus")
    op.analytics_data = data.get("analytics_data")
    op.financial_data = data.get("financial_data")
    db.commit()

    # replace products for this posting
    db.query(OrderProduct).filter(OrderProduct.posting_number == posting_number).delete()
    products = data.get("products", [])
    fin = (data.get("financial_data") or {}).get("products") or []
    fin_by_sku = {}
    fin_by_offer = {}
    for f in fin:
        # на практике в ответе встречаются product_id=SKU, а иногда sku/offer_id
        pid = f.get("product_id")
        if pid is not None:
            fin_by_sku[str(pid)] = f
        sku_key = f.get("sku")
        if sku_key is not None:
            fin_by_sku[str(sku_key)] = f
        ofr = f.get("offer_id")
        if ofr:
            fin_by_offer[str(ofr)] = f
    for pr in products:
        sku = pr.get("sku")
        offer_id_val = pr.get("offer_id")
        f = fin_by_sku.get(str(sku)) or (fin_by_offer.get(str(offer_id_val)) if offer_id_val is not None else None)
        obj = OrderProduct(
            posting_number=posting_number,
            sku=_to_int(sku),
            offer_id=str(offer_id_val) if offer_id_val is not None else None,
            name=pr.get("name"),
            quantity=_to_int(pr.get("quantity")),
            price=_to_int(pr.get("price")),
            currency_code=pr.get("currency_code"),
            commission_amount=_to_int((f or {}).get("commission_amount")),
            commission_percent=_to_int((f or {}).get("commission_percent")),
            payout=_to_int((f or {}).get("payout")),
            total_discount_value=_to_int((f or {}).get("total_discount_value")),
            total_discount_percent=_to_int((f or {}).get("total_discount_percent")),
        )
        db.add(obj)
    db.commit()

    # update header aggregates
    if order_number:
        _recalc_order_header(db, order_number)

    return {"status": "ok", "order_number": order_number, "posting_number": posting_number, "products": len(products)}


@app.get("/orders")
async def list_orders(
    since: str | None = None,
    to: str | None = None,
    status: str | None = None,
    posting_number: str | None = None,
    contains: str | None = None,
    limit: int = 50,
    offset: int = 0,
    sort: str = "-created_at",
    db: Session = Depends(get_db),
):
    """Чтение заказов из БД (DB-first): фильтры, пагинация, сортировка.
    - since/to: ISO-строки (нормализуются к '...Z')
    - status: точное совпадение
    - posting_number: точное совпадение
    - contains: подстрока для LIKE по posting_number
    - sort: 'created_at' или '-created_at'
    """
    try:
        since_iso = _normalize_iso(since)
        to_iso = _normalize_iso(to)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad date format")

    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    q = db.query(Order)
    if since_iso:
        q = q.filter(Order.created_at >= since_iso)
    if to_iso:
        q = q.filter(Order.created_at <= to_iso)
    if status:
        q = q.filter(Order.status == status)
    if posting_number:
        q = q.filter(Order.posting_number == posting_number)
    if contains:
        q = q.filter(Order.posting_number.like(f"%{contains}%"))

    total = q.count()

    if sort == "created_at":
        q = q.order_by(Order.created_at.asc())
    else:
        # по умолчанию -created_at
        q = q.order_by(Order.created_at.desc())

    rows = q.offset(offset).limit(limit).all()
    items = [
        {
            "id": r.id,
            "order_id": r.order_id,
            "posting_number": r.posting_number,
            "status": r.status,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "data": r.data,
        }
        for r in rows
    ]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@app.get("/orders/{posting_number}", response_model=OrderOut)
async def get_order_by_posting(posting_number: str, db: Session = Depends(get_db)):
    row = db.query(Order).filter(Order.posting_number == posting_number).first()
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    return row


@app.get("/order/{order_number}")
async def get_order_summary(order_number: str, db: Session = Depends(get_db)):
    header = db.query(OrderHeader).filter(OrderHeader.order_number == order_number).first()
    postings = db.query(OrderPosting).filter(OrderPosting.order_number == order_number).order_by(OrderPosting.created_at.asc()).all()
    products = db.query(OrderProduct).filter(OrderProduct.posting_number.in_([p.posting_number for p in postings])).all() if postings else []
    total_payout = sum((p.payout or 0) for p in products)
    total_commission = sum((p.commission_amount or 0) for p in products)
    profit = total_payout - total_commission
    return {
        "order_number": order_number,
        "header": {
            "first_created_at": header.first_created_at if header else None,
            "last_delivery_at": header.last_delivery_at if header else None,
            "total_payout": header.total_payout if header and header.total_payout is not None else total_payout,
            "total_commission": header.total_commission if header and header.total_commission is not None else total_commission,
            "profit": profit,
        },
        "postings": [
            {
                "posting_number": p.posting_number,
                "status": p.status,
                "created_at": p.created_at,
                "in_process_at": p.in_process_at,
                "fact_delivery_date": p.fact_delivery_date,
                "substatus": p.substatus,
                "analytics_data": p.analytics_data,
                "financial_data": p.financial_data,
                "products": [
                    {
                        "sku": pr.sku,
                        "offer_id": pr.offer_id,
                        "name": pr.name,
                        "quantity": pr.quantity,
                        "price": pr.price,
                        "currency_code": pr.currency_code,
                        "commission_amount": pr.commission_amount,
                        "commission_percent": pr.commission_percent,
                        "payout": pr.payout,
                        "total_discount_value": pr.total_discount_value,
                        "total_discount_percent": pr.total_discount_percent,
                    }
                    for pr in products if pr.posting_number == p.posting_number
                ],
            }
            for p in postings
        ],
    }


@app.get("/order/{order_number}/postings")
async def list_order_postings(order_number: str, db: Session = Depends(get_db)):
    postings = db.query(OrderPosting).filter(OrderPosting.order_number == order_number).order_by(OrderPosting.created_at.asc()).all()
    if not postings:
        # fallback: получить постинги из легаси-таблицы orders по префиксу order_number-
        prefix = order_number + "-"
        legacy_postings = db.query(Order.posting_number).filter(Order.posting_number.like(f"{prefix}%")).all()
        # вернём список как объекты с минимумом полей, чтобы интерфейс был единообразным
        postings = [
            OrderPosting(order_number=order_number, posting_number=p[0], status=None, created_at=None)
            for p in legacy_postings
        ]
    result = []
    for p in postings:
        prods = db.query(OrderProduct).filter(OrderProduct.posting_number == p.posting_number).all()
        total_payout = sum((pr.payout or 0) for pr in prods)
        total_commission = sum((pr.commission_amount or 0) for pr in prods)
        result.append({
            "posting_number": p.posting_number,
            "status": p.status,
            "created_at": p.created_at,
            "products_count": len(prods),
            "total_payout": total_payout,
            "total_commission": total_commission,
        })
    return {"order_number": order_number, "count": len(result), "items": result}


class EnrichPostingIn(BaseModel):
    posting_number: str


@app.post("/orders/fbo/get")
async def enrich_posting(item: EnrichPostingIn, db: Session = Depends(get_db)):
    try:
        result = await asyncio.to_thread(_enrich_posting_from_ozon, item.posting_number, db)
        return result
    except requests.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Ozon error: {e}")
    except Exception as e:
        logging.error(f"Ошибка обогащения постинга {item.posting_number}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class EnrichOrderIn(BaseModel):
    order_number: str


@app.post("/orders/fbo/get_for_order")
async def enrich_order(item: EnrichOrderIn, db: Session = Depends(get_db)):
    # Собираем постинги из нормализованной таблицы и из легаси orders по префиксу
    postings_norm = db.query(OrderPosting.posting_number).filter(OrderPosting.order_number == item.order_number).all()
    postings_norm = [p[0] for p in postings_norm]
    prefix = item.order_number + "-"
    legacy = db.query(Order.posting_number).filter(Order.posting_number.like(f"{prefix}%")).all()
    postings_legacy = [p[0] for p in legacy]
    postings = sorted(set(postings_norm) | set(postings_legacy))
    results = []
    for pn in postings:
        try:
            res = await asyncio.to_thread(_enrich_posting_from_ozon, pn, db)
            results.append(res)
        except Exception as e:
            results.append({"posting_number": pn, "error": str(e)})
    return {"order_number": item.order_number, "count": len(postings), "results": results}


@app.post("/orders/fbo/enrich_recent")
async def enrich_recent(limit: int = 100):
    since_iso = (datetime.utcnow() - timedelta(hours=RECENT_WINDOW_HOURS)).isoformat() + 'Z'
    session = SessionLocal()
    try:
        fresh_orders = session.query(Order.posting_number).filter(Order.created_at >= since_iso).order_by(Order.created_at.desc()).limit(limit).all()
        fresh_norm = session.query(OrderPosting.posting_number).filter(OrderPosting.created_at >= since_iso).order_by(OrderPosting.created_at.desc()).limit(limit).all()
        raw_targets = [o[0] for o in fresh_orders] + [n[0] for n in fresh_norm]
        targets = sorted({pn for pn in raw_targets if _valid_posting_number(pn)})
    finally:
        session.close()
    results = []
    for pn in targets:
        try:
            res = await asyncio.to_thread(_enrich_posting_from_ozon, pn, SessionLocal())
            results.append(res)
        except Exception as e:
            results.append({"posting_number": pn, "error": str(e)})
    return {"processed": len(targets), "results": results}


@app.post("/orders/fbo/enrich_changed_recent")
async def enrich_changed_recent(limit: int = 100):
    since_iso = (datetime.utcnow() - timedelta(hours=RECENT_WINDOW_HOURS)).isoformat() + 'Z'
    session = SessionLocal()
    try:
        recent_orders = session.query(Order).filter(Order.created_at >= since_iso).order_by(Order.created_at.desc()).limit(500).all()
        candidates = []
        for r in recent_orders:
            pn = r.posting_number
            if not _valid_posting_number(pn):
                continue
            row = session.query(OrderPosting).filter(OrderPosting.posting_number == pn).first()
            if (row.status if row else None) != r.status:
                candidates.append(pn)
        targets = sorted(set(candidates))[:limit]
    finally:
        session.close()
    results = []
    for pn in targets:
        try:
            res = await asyncio.to_thread(_enrich_posting_from_ozon, pn, SessionLocal())
            results.append(res)
        except Exception as e:
            results.append({"posting_number": pn, "error": str(e)})
    return {"processed": len(targets), "results": results}


class CostIn(BaseModel):
    type: str
    amount: int
    currency: str = "RUB"
    date: str
    scope_order_number: str | None = None
    scope_posting_number: str | None = None
    scope_sku: int | None = None
    scope_offer_id: str | None = None
    notes: str | None = None


@app.post("/costs")
async def add_cost(cost: CostIn, db: Session = Depends(get_db)):
    obj = Cost(
        type=cost.type,
        amount=cost.amount,
        currency=cost.currency,
        date=cost.date,
        scope_order_number=cost.scope_order_number,
        scope_posting_number=cost.scope_posting_number,
        scope_sku=cost.scope_sku,
        scope_offer_id=cost.scope_offer_id,
        notes=cost.notes or "",
    )
    db.add(obj)
    db.commit()
    return {"status": "ok", "id": obj.id}


@app.get("/costs")
async def list_costs(
    type: str | None = None,
    since: str | None = None,
    to: str | None = None,
    order_number: str | None = None,
    posting_number: str | None = None,
    sku: int | None = None,
    offer_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(Cost)
    if type:
        q = q.filter(Cost.type == type)
    try:
        since_iso = _normalize_iso(since)
        to_iso = _normalize_iso(to)
    except Exception:
        raise HTTPException(status_code=400, detail="Bad date format")
    if since_iso:
        q = q.filter(Cost.date >= since_iso)
    if to_iso:
        q = q.filter(Cost.date <= to_iso)
    if order_number:
        q = q.filter(Cost.scope_order_number == order_number)
    if posting_number:
        q = q.filter(Cost.scope_posting_number == posting_number)
    if sku is not None:
        q = q.filter(Cost.scope_sku == sku)
    if offer_id:
        q = q.filter(Cost.scope_offer_id == offer_id)
    total = q.count()
    rows = q.order_by(Cost.date.desc()).offset(offset).limit(min(max(limit, 1), 500)).all()
    items = [
        {
            "id": r.id,
            "type": r.type,
            "amount": r.amount,
            "currency": r.currency,
            "date": r.date,
            "scope_order_number": r.scope_order_number,
            "scope_posting_number": r.scope_posting_number,
            "scope_sku": r.scope_sku,
            "scope_offer_id": r.scope_offer_id,
            "notes": r.notes,
        }
        for r in rows
    ]
    return {"total": total, "items": items, "limit": limit, "offset": offset}


async def background_sync_loop(app: FastAPI, interval_seconds: int = 300):
    """Асинхронный цикл:
    1) Инкремент новых заказов
    2) Повторная проверка недавнего окна для обновлений статусов
    Сохраняет отметки времени в app.state для диагностики.
    """
    logging.info("Фоновая синхронизация запущена")
    try:
        while True:
            try:
                start_new = datetime.utcnow()
                res_new = await asyncio.to_thread(fetch_and_save_orders)
                app.state.last_sync_new = datetime.utcnow().isoformat() + 'Z'
                app.state.last_sync_new_saved = res_new.get('saved')
                app.state.last_sync_new_fetched = res_new.get('fetched')
                logging.info(f"Инкрементальная синхронизация: добавлено={res_new.get('saved')} получено={res_new.get('fetched')}")

                recent_since_dt = datetime.utcnow() - timedelta(hours=RECENT_WINDOW_HOURS)
                recent_since = recent_since_dt.isoformat() + 'Z'
                res_recent = await asyncio.to_thread(fetch_and_save_orders, recent_since, None)
                app.state.last_sync_recent = datetime.utcnow().isoformat() + 'Z'
                app.state.last_sync_recent_saved = res_recent.get('saved')
                app.state.last_sync_recent_fetched = res_recent.get('fetched')
                app.state.last_sync_interval_seconds = interval_seconds
                logging.info(f"Сверка недавнего окна ({RECENT_WINDOW_HOURS}ч): добавлено={res_recent.get('saved')} получено={res_recent.get('fetched')}")

                # Переобогащение только изменившихся по статусу постингов
                if ENRICH_ON_STATUS_CHANGE:
                    try:
                        recent_items = res_recent.get('orders') or []
                        session = SessionLocal()
                        try:
                            candidates = []
                            for it in recent_items:
                                pn = it.get('posting_number')
                                if not _valid_posting_number(pn):
                                    continue
                                new_status = it.get('status')
                                row = session.query(OrderPosting).filter(OrderPosting.posting_number == pn).first()
                                old_status = row.status if row else None
                                if new_status != old_status:
                                    candidates.append(pn)
                            targets = sorted(set(candidates))[:ENRICH_STATUS_CHANGE_LIMIT]
                        finally:
                            session.close()

                        sem = asyncio.Semaphore(ENRICH_CONCURRENCY)
                        async def run_one(pn):
                            async with sem:
                                await asyncio.to_thread(_enrich_posting_from_ozon, pn, SessionLocal())
                        if targets:
                            await asyncio.gather(*(run_one(pn) for pn in targets))
                            logging.info(f"Переобогащение по изменению статуса: обработано={len(targets)}")
                    except Exception as e:
                        logging.debug(f"Ошибка переобогащения по статусам: {e}")

                # Фоновое обогащение свежих постингов
                if ENRICH_RECENT_POSTINGS:
                    try:
                        session = SessionLocal()
                        try:
                            since_iso = (datetime.utcnow() - timedelta(hours=RECENT_WINDOW_HOURS)).isoformat() + 'Z'
                            fresh_orders = session.query(Order.posting_number).filter(Order.created_at >= since_iso).order_by(Order.created_at.desc()).limit(ENRICH_RECENT_LIMIT).all()
                            fresh_norm = session.query(OrderPosting.posting_number).filter(OrderPosting.created_at >= since_iso).order_by(OrderPosting.created_at.desc()).limit(ENRICH_RECENT_LIMIT).all()
                            targets = sorted(set([o[0] for o in fresh_orders] + [n[0] for n in fresh_norm]))
                        finally:
                            session.close()

                        async def worker(pn):
                            try:
                                await asyncio.to_thread(_enrich_posting_from_ozon, pn, SessionLocal())
                            except Exception as e:
                                logging.debug(f"enrich {pn} error: {e}")

                        sem = asyncio.Semaphore(ENRICH_CONCURRENCY)
                        async def run_with_sem(pn):
                            async with sem:
                                await worker(pn)

                        await asyncio.gather(*(run_with_sem(pn) for pn in targets))
                        logging.info(f"Обогащение свежих постингов: обработано={len(targets)}")
                    except Exception as e:
                        logging.debug(f"Ошибка фонового обогащения: {e}")

                # Авто-сверка последних месяцев по расписанию
                now = datetime.utcnow()
                if not hasattr(app.state, 'last_month_reconcile'):
                    app.state.last_month_reconcile = None
                do_reconcile = (
                    app.state.last_month_reconcile is None or
                    (now - _iso_to_dt(app.state.last_month_reconcile)).total_seconds() >= MONTH_RECONCILE_INTERVAL_SECONDS
                )
                if do_reconcile:
                    logging.info(f"Начинаю месячную сверку последних {MONTH_RECONCILE_MONTHS} месяцев")
                    # берем последние MONTH_RECONCILE_MONTHS месяцев (включая текущий месяц)
                    base = datetime(now.year, now.month, 1)
                    summaries = []  # [(ym, saved, fetched)]
                    for i in range(MONTH_RECONCILE_MONTHS):
                        start_dt = (base - timedelta(days=30*i)).replace(day=1)
                        # end is next month 1st
                        if start_dt.month == 12:
                            end_dt = datetime(start_dt.year+1, 1, 1)
                        else:
                            end_dt = datetime(start_dt.year, start_dt.month+1, 1)
                        since_iso = start_dt.isoformat() + 'Z'
                        to_iso = end_dt.isoformat() + 'Z'
                        ym = start_dt.strftime('%Y-%m')
                        try:
                            r = await asyncio.to_thread(fetch_and_save_orders, since_iso, to_iso)
                            summaries.append((ym, r.get('saved'), r.get('fetched')))
                            logging.info(f"Месячная сверка {ym}: добавлено={r.get('saved')} получено={r.get('fetched')}")
                        except Exception as e:
                            logging.error(f"Ошибка месячной сверки для {ym}: {e}")
                    app.state.last_month_reconcile = now.isoformat() + 'Z'
                    # После сверки: вывести отчёт по последним MONTH_RECONCILE_MONTHS месяцам в требуемом формате
                    try:
                        session = SessionLocal()
                        try:
                            # Отчёт идёт от старого к новому (как в примере)
                            for ym, saved, fetched in sorted(summaries, key=lambda t: t[0]):
                                count = session.query(Order).filter(Order.created_at.like(f"{ym}%")).count()
                                label = datetime.strptime(ym, '%Y-%m').strftime('%B %Y')
                                logging.info(f"{label}: добавлено={saved} получено={fetched} rows")
                            min_created = session.query(Order.created_at).order_by(Order.created_at.asc()).first()
                            max_created = session.query(Order.created_at).order_by(Order.created_at.desc()).first()
                            logging.info(f"Min created_at: {min_created[0] if min_created else None}")
                            logging.info(f"Max created_at: {max_created[0] if max_created else None}")
                        finally:
                            session.close()
                    except Exception as e:
                        logging.error(f"Ошибка формирования отчёта по месяцам: {e}")
                    logging.info("Месячная сверка завершена")
            except Exception as e:
                logging.error(f"Ошибка фоновой синхронизации: {e}")
                app.state.last_sync_error = str(e)
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logging.info("Фоновая синхронизация остановлена")
        raise

def get_earliest_order_date():
    client_id = os.getenv("OZON_CLIENT_ID")
    api_key = os.getenv("OZON_API_KEY")
    url = "https://api-seller.ozon.ru/v2/posting/fbo/list"
    headers = {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json"
    }
    body = {
        "dir": "ASC",
        "filter": {},
        "limit": 1,
        "offset": 0,
        "translit": True,
        "with": {"analytics_data": True, "financial_data": True, "legal_info": False}
    }
    try:
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()
        data = response.json()
        result = data.get('result', [])
        if result:
            return result[0].get('created_at')
        else:
            return None
    except Exception as e:
        logging.error(f"Ошибка получения самой ранней даты: {e}")
        return None

def _parse_start_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return _iso_to_dt(raw)
    except Exception:
        logging.warning('START_DATE не в ISO-формате, игнорируется')
        return None

async def history_forward_sync(start_dt: datetime, end_dt: datetime) -> list:
    """Импорт истории от start_dt до end_dt окнами по HISTORY_WINDOW_DAYS.
    Возвращает список результатов окон.
    """
    summary = []
    window_start = start_dt
    while window_start < end_dt:
        window_end = min(window_start + timedelta(days=HISTORY_WINDOW_DAYS), end_dt)
        since_iso = window_start.isoformat() + 'Z'
        to_iso = window_end.isoformat() + 'Z'
        logging.info(f'[history sync] window: {since_iso} -> {to_iso}')
        try:
            result = await asyncio.to_thread(fetch_and_save_orders, since_iso, to_iso)
            summary.append({"since": since_iso, "to": to_iso, "saved": result.get('saved'), "fetched": result.get('fetched')})
        except Exception as e:
            summary.append({"since": since_iso, "to": to_iso, "error": str(e)})
        window_start = window_end + timedelta(seconds=1)
    return summary

def orders_exist_in_db(since, to, db: Session):
    return db.query(Order).filter(Order.created_at >= since, Order.created_at <= to).count() > 0

def save_order(order: dict, db: Session):
    db_order = db.query(Order).filter(Order.posting_number == order.get('posting_number')).first()
    if db_order:
        db_order.order_id = order.get('order_id')
        db_order.status = order.get('status')
        db_order.updated_at = order.get('created_at')
        db_order.data = order
        db.commit()
        return 'updated'
    else:
        new_order = Order(
            order_id=order.get('order_id'),
            posting_number=order.get('posting_number'),
            status=order.get('status'),
            created_at=order.get('created_at'),
            updated_at=order.get('created_at'),
            data=order
        )
        db.add(new_order)
        db.commit()
        return 'inserted'

@app.post("/orders/fbo")
async def get_fbo_orders(
    since: str = None,
    to: str = None,
    status: str = "",
    limit: int = 50,
    offset: int = 0,
    analytics_data: bool = True,
    financial_data: bool = True,
    legal_info: bool = False,
    db: Session = Depends(get_db)
):
    """Endpoint-обёртка вокруг `fetch_and_save_orders`.
    Использует зависимость `db`, чтобы контролировать сессию в рамках запроса.
    """
    try:
        result = await asyncio.to_thread(
            fetch_and_save_orders,
            since,
            to,
            status,
            limit,
            offset,
            analytics_data,
            financial_data,
            legal_info,
            db,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.error(f"Ошибка в endpoint /orders/fbo: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sync/initial")
async def run_initial_sync_endpoint():
    """Запустить initial full sync вручную. Вернёт сводку по выполненным окнам."""
    if not ENABLE_INITIAL_SYNC:
        raise HTTPException(status_code=400, detail="Initial sync disabled by config")

    root = os.path.dirname(__file__)
    marker_path = os.path.join(root, '.initial_sync_done')
    if os.path.exists(marker_path):
        return {"status": "already_done"}

    # Определяем earliest
    earliest = get_earliest_order_date()
    if earliest:
        try:
            start_dt = _iso_to_dt(earliest)
        except Exception:
            start_dt = datetime.utcnow() - timedelta(days=INITIAL_WINDOW_DAYS)
    else:
        start_dt = datetime.utcnow() - timedelta(days=INITIAL_WINDOW_DAYS)

    now = datetime.utcnow()
    window_start = start_dt
    summary = []
    while window_start < now:
        window_end = min(window_start + timedelta(days=INITIAL_WINDOW_DAYS), now)
        since_iso = window_start.isoformat() + 'Z'
        to_iso = window_end.isoformat() + 'Z'
        try:
            result = await asyncio.to_thread(fetch_and_save_orders, since_iso, to_iso)
            summary.append({"since": since_iso, "to": to_iso, "saved": result.get('saved'), "fetched": result.get('fetched')})
        except Exception as e:
            summary.append({"since": since_iso, "to": to_iso, "error": str(e)})
        window_start = window_end + timedelta(seconds=1)

    try:
        with open(marker_path, 'w') as f:
            f.write(datetime.utcnow().isoformat() + 'Z')
    except Exception:
        logging.error('Could not write initial sync marker')

    return {"status": "done", "windows": summary}


@app.post("/sync/initial/force")
async def run_initial_sync_force_endpoint():
    """Запустить initial full sync, игнорируя маркер. Полезно для повторного полного импорта."""
    if not ENABLE_INITIAL_SYNC:
        raise HTTPException(status_code=400, detail="Initial sync disabled by config")

    # Определяем earliest
    earliest = get_earliest_order_date()
    if earliest:
        try:
            start_dt = _iso_to_dt(earliest)
        except Exception:
            start_dt = datetime.utcnow() - timedelta(days=INITIAL_WINDOW_DAYS)
    else:
        start_dt = datetime.utcnow() - timedelta(days=INITIAL_WINDOW_DAYS)

    now = datetime.utcnow()
    window_start = start_dt
    summary = []
    while window_start < now:
        window_end = min(window_start + timedelta(days=INITIAL_WINDOW_DAYS), now)
        since_iso = window_start.isoformat() + 'Z'
        to_iso = window_end.isoformat() + 'Z'
        try:
            result = await asyncio.to_thread(fetch_and_save_orders, since_iso, to_iso)
            summary.append({"since": since_iso, "to": to_iso, "saved": result.get('saved'), "fetched": result.get('fetched')})
        except Exception as e:
            summary.append({"since": since_iso, "to": to_iso, "error": str(e)})
        window_start = window_end + timedelta(seconds=1)

    return {"status": "done", "windows": summary}


@app.on_event("startup")
async def startup_event():
    # При старте: сначала выполнить initial full sync (если включено и не сделано ранее), затем запустить циклический sync
    root = os.path.dirname(__file__)
    marker_path = os.path.join(root, '.initial_sync_done')

    async def run_initial_if_needed():
        if not ENABLE_INITIAL_SYNC:
            logging.info('Первичная загрузка отключена настройками')
            return
        if os.path.exists(marker_path):
            logging.info('Первичная загрузка уже выполнена (найден маркер)')
            return
        # Проверяем что база пуста (делаем большой диапазон только один раз при пустой БД)
        session = SessionLocal()
        try:
            count_rows = session.query(Order).count()
        finally:
            session.close()
        if count_rows > 0:
            logging.info('База не пустая; пропускаем первичный большой диапазон')
            return
        # Один запрос: год назад -> сейчас (будет разбит пагинацией внутри fetch_and_save_orders)
        since_dt = datetime.utcnow() - timedelta(days=365)
        to_dt = datetime.utcnow()
        since_iso = since_dt.isoformat() + 'Z'
        to_iso = to_dt.isoformat() + 'Z'
        logging.info(f'Первичная единоразовая загрузка: {since_iso} -> {to_iso}')
        try:
            result = await asyncio.to_thread(fetch_and_save_orders, since_iso, to_iso)
            logging.info(f'Результат первичной загрузки: добавлено={result.get("saved")} получено={result.get("fetched")}')
        except Exception as e:
            logging.error(f'Ошибка во время первичной загрузки: {e}')
            return
        # Маркер, чтобы больше не повторять
        try:
            with open(marker_path, 'w') as f:
                f.write(datetime.utcnow().isoformat() + 'Z')
            logging.info('Первичная загрузка завершена, создан маркер')
        except Exception as e:
            logging.error(f'Не удалось записать маркер первичной загрузки: {e}')

    # Запускаем initial sync (если нужно), затем фоновую задачу
    await run_initial_if_needed()
    # Инициализируем диагностические поля
    app.state.last_sync_new = None
    app.state.last_sync_recent = None
    app.state.last_sync_error = None
    app.state.sync_task = asyncio.create_task(background_sync_loop(app, SYNC_INTERVAL_SECONDS))


@app.on_event("shutdown")
async def shutdown_event():
    task = getattr(app.state, 'sync_task', None)
    if task:
        task.cancel()

@app.get("/stats")
async def stats(db: Session = Depends(get_db)):
    """Диагностика: количество строк, min/max created_at, последние времена синхронизаций."""
    total = db.query(Order).count()
    min_created = db.query(Order.created_at).order_by(Order.created_at.asc()).first()
    max_created = db.query(Order.created_at).order_by(Order.created_at.desc()).first()
    return {
        "total_rows": total,
        "min_created_at": min_created[0] if min_created else None,
        "max_created_at": max_created[0] if max_created else None,
        "last_sync_new": getattr(app.state, 'last_sync_new', None),
        "last_sync_new_saved": getattr(app.state, 'last_sync_new_saved', None),
        "last_sync_new_fetched": getattr(app.state, 'last_sync_new_fetched', None),
        "last_sync_recent": getattr(app.state, 'last_sync_recent', None),
        "last_sync_recent_saved": getattr(app.state, 'last_sync_recent_saved', None),
        "last_sync_recent_fetched": getattr(app.state, 'last_sync_recent_fetched', None),
        "last_sync_error": getattr(app.state, 'last_sync_error', None),
        "sync_interval_seconds": getattr(app.state, 'last_sync_interval_seconds', SYNC_INTERVAL_SECONDS),
    }

@app.post('/sync/history')
async def run_history_sync(start: str, end: str = None):
    """Ручной импорт истории по окнам HISTORY_WINDOW_DAYS.
    start: ISO дата начала (обязательно)
    end: ISO дата конца (по умолчанию сейчас)
    """
    try:
        start_dt = _iso_to_dt(start)
        end_dt = _iso_to_dt(end) if end else datetime.utcnow()
    except Exception:
        raise HTTPException(status_code=400, detail='Bad date format')
    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail='end < start')
    summary = await history_forward_sync(start_dt, end_dt)
    return {"status": "done", "windows": summary}


@app.get("/analytics/sales_today")
async def analytics_sales_today(db: Session = Depends(get_db)):
    """Возвращает сводку продаж за сегодня по артикулам (offer_id), SKU и названию.
    Считаем продажи как товары в постингах со статусом 'delivered' и датой фактической доставки сегодня (UTC).
    Поля:
    - offer_id
    - sku
    - name
    - quantity_sold (суммарно)
    - total_payout (сумма выплат по позициям)
    """
    today_prefix = datetime.utcnow().date().isoformat()  # YYYY-MM-DD
    # Находим постинги со статусом delivered и fact_delivery_date в пределах сегодняшней даты
    postings = db.query(OrderPosting.posting_number).\
        filter(OrderPosting.status == 'delivered').\
        filter(OrderPosting.fact_delivery_date.like(f"{today_prefix}%")).all()

    posting_numbers = [p[0] for p in postings]
    if not posting_numbers:
        return {"date": today_prefix, "items": [], "total_items": 0}

    # Собираем продукты по найденным постингам
    products = db.query(OrderProduct).filter(OrderProduct.posting_number.in_(posting_numbers)).all()
    # Агрегируем по offer_id (если пусто, используем sku как ключ)
    agg = {}
    for pr in products:
        key = pr.offer_id or (str(pr.sku) if pr.sku is not None else "<no-offer>")
        if key not in agg:
            agg[key] = {
                "offer_id": pr.offer_id,
                "sku": pr.sku,
                "name": pr.name,
                "quantity_sold": 0,
                "total_payout": 0,
            }
        agg[key]["quantity_sold"] += pr.quantity or 0
        agg[key]["total_payout"] += pr.payout or 0

    items = sorted(agg.values(), key=lambda x: (-x["quantity_sold"], x.get("offer_id") or ""))
    total_items = sum(i["quantity_sold"] for i in items)
    return {"date": today_prefix, "items": items, "total_items": total_items}


@app.get("/analytics/orders_today")
async def analytics_orders_today(db: Session = Depends(get_db)):
    """Количество заказов за сегодня и разрез по статусам.
    Берём записи из легаси таблицы `Order` по полю created_at в пределах текущей даты (UTC).
    Возвращает:
    - total: общее количество
    - by_status: список {status, count}
    """
    start = datetime.utcnow().date().isoformat() + 'T00:00:00Z'
    end = datetime.utcnow().date().isoformat() + 'T23:59:59Z'
    q = db.query(Order).filter(Order.created_at >= start).filter(Order.created_at <= end)
    total = q.count()
    # Собираем статусы
    rows = q.all()
    stats = {}
    for r in rows:
        st = r.status or "unknown"
        stats[st] = stats.get(st, 0) + 1
    by_status = [{"status": k, "count": v} for k, v in sorted(stats.items(), key=lambda x: (-x[1], x[0]))]
    return {"date": start[:10], "total": total, "by_status": by_status}
