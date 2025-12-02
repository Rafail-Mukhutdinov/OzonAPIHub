
import os
import requests
import logging
import asyncio
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from db.database import Order, get_db, SessionLocal
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
logging.basicConfig(level=logging.INFO)

class OrderIn(BaseModel):
    order_id: int
    posting_number: str
    status: str
    created_at: str
    updated_at: str = None
    data: dict

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
            logging.info(f"Ozon request body: {body}")
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

        return {"saved": total_saved, "fetched": len(all_orders), "orders": all_orders}
    finally:
        if own_session:
            db.close()


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
