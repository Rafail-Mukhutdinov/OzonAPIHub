
import os
import requests
import logging
import asyncio
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from db.database import Order, OrderHeader, OrderPosting, OrderProduct, Cost, get_db, SessionLocal
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

load_dotenv()

# Конфиг из окружения
ENABLE_INITIAL_SYNC = os.getenv('ENABLE_INITIAL_SYNC', 'true').lower() in ('1', 'true', 'yes')
SYNC_INTERVAL_SECONDS = int(os.getenv('SYNC_INTERVAL_SECONDS', '300'))
INITIAL_WINDOW_DAYS = int(os.getenv('INITIAL_WINDOW_DAYS', '365'))
START_DATE_RAW = os.getenv('START_DATE')
HISTORY_WINDOW_DAYS = int(os.getenv('HISTORY_WINDOW_DAYS', '30'))

app = FastAPI()
# Управление уровнем логов: LOG_LEVEL=DEBUG|INFO|WARNING|ERROR|CRITICAL
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
try:
    _lvl = getattr(logging, LOG_LEVEL, logging.INFO)
except Exception:
    _lvl = logging.INFO
# Настройка логирования для работы с uvicorn
# Используем logger uvicorn.error для вывода в консоль
logger = logging.getLogger("uvicorn.error")
LOG_OZON_REQUESTS = os.getenv('LOG_OZON_REQUESTS', 'false').lower() in ('1', 'true', 'yes')
ENRICH_RECENT_POSTINGS = os.getenv('ENRICH_RECENT_POSTINGS', 'true').lower() in ('1', 'true', 'yes')
ENRICH_RECENT_LIMIT = int(os.getenv('ENRICH_RECENT_LIMIT', '100'))
RECENT_WINDOW_HOURS = int(os.getenv('RECENT_WINDOW_HOURS', '48'))
ENRICH_CONCURRENCY = int(os.getenv('ENRICH_CONCURRENCY', '4'))
ENRICH_ON_FETCH = os.getenv('ENRICH_ON_FETCH', 'true').lower() in ('1', 'true', 'yes')
ENRICH_ON_FETCH_LIMIT = int(os.getenv('ENRICH_ON_FETCH_LIMIT', '200'))
ENRICH_ON_STATUS_CHANGE = os.getenv('ENRICH_ON_STATUS_CHANGE', 'true').lower() in ('1', 'true', 'yes')
ENRICH_STATUS_CHANGE_LIMIT = int(os.getenv('ENRICH_STATUS_CHANGE_LIMIT', '100'))

# CORS для Flutter Web (dev): разрешаем запросы с localhost
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

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
    logger.info('запрос на ping')
    return {"message": "pong"}


def _iso_to_dt(s: str) -> datetime:
    if s is None:
        return None
    try:
        s2 = s.rstrip('Z')
        return datetime.fromisoformat(s2)
    except Exception:
        raise ValueError(f"Invalid ISO datetime: {s}")


from services.sync import fetch_and_save_orders


def _normalize_iso(s: str | None) -> str | None:
    if not s:
        return None
    dt = _iso_to_dt(s)
    dt = dt.replace(microsecond=0)
    return dt.isoformat() + 'Z'


from services.enrichment import enrich_posting_from_ozon as _enrich_posting_from_ozon










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
        logger.error(f"Ошибка обогащения постинга {item.posting_number}: {e}")
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


from services.sync import background_sync_loop

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
        logger.error(f"Ошибка получения самой ранней даты: {e}")
        return None

def _parse_start_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return _iso_to_dt(raw)
    except Exception:
        logger.warning('START_DATE не в ISO-формате, игнорируется')
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
        logger.info(f'[history sync] window: {since_iso} -> {to_iso}')
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
        logger.error(f"Ошибка в endpoint /orders/fbo: {e}")
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
        logger.error('Could not write initial sync marker')

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
            logger.info('Первичная загрузка отключена настройками')
            return
        if os.path.exists(marker_path):
            logger.info('Первичная загрузка уже выполнена (найден маркер)')
            return
        # Проверяем что база пуста (делаем большой диапазон только один раз при пустой БД)
        session = SessionLocal()
        try:
            count_rows = session.query(Order).count()
        finally:
            session.close()
        if count_rows > 0:
            logger.info('База не пустая; пропускаем первичный большой диапазон')
            return
        # Один запрос: год назад -> сейчас (будет разбит пагинацией внутри fetch_and_save_orders)
        since_dt = datetime.utcnow() - timedelta(days=365)
        to_dt = datetime.utcnow()
        since_iso = since_dt.isoformat() + 'Z'
        to_iso = to_dt.isoformat() + 'Z'
        logger.info(f'Первичная единоразовая загрузка: {since_iso} -> {to_iso}')
        try:
            result = await asyncio.to_thread(fetch_and_save_orders, since_iso, to_iso)
            logger.info(f'Результат первичной загрузки: добавлено={result.get("saved")} получено={result.get("fetched")}')
            # Сразу обогатим постинги из результата initial sync, чтобы аналитика была готова
            try:
                from services.enrichment import enrich_posting_from_ozon
                orders = result.get('orders') or []
                pns = sorted({o.get('posting_number') for o in orders if _valid_posting_number(o.get('posting_number'))})
                if pns:
                    existing = set(row[0] for row in SessionLocal().query(OrderPosting.posting_number).filter(OrderPosting.posting_number.in_(pns)).all())
                    targets = [pn for pn in pns if pn not in existing]
                    if targets:
                        sem = asyncio.Semaphore(ENRICH_CONCURRENCY)
                        async def run_one(pn):
                            async with sem:
                                await asyncio.to_thread(enrich_posting_from_ozon, pn, SessionLocal())
                        await asyncio.gather(*(run_one(pn) for pn in targets))
                        logger.info(f'Обогащение initial sync: обработано постингов={len(targets)}')
            except Exception as e:
                logger.debug(f'Ошибка обогащения во время initial sync: {e}')
        except Exception as e:
            logger.error(f'Ошибка во время первичной загрузки: {e}')
            return
        # Маркер, чтобы больше не повторять
        try:
            with open(marker_path, 'w') as f:
                f.write(datetime.utcnow().isoformat() + 'Z')
            logger.info('Первичная загрузка завершена, создан маркер')
        except Exception as e:
            logger.error(f'Не удалось записать маркер первичной загрузки: {e}')

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


# Подключение роутеров
from routes.analytics import router as analytics_router
from routes.orders import router as orders_router
from routes.sync import router as sync_router
app.include_router(analytics_router)
app.include_router(orders_router)
app.include_router(sync_router)
