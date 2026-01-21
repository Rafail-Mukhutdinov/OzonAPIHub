# OzonAPIHub — AI Coding Guidelines

## Architecture Overview

**OzonAPIHub** is a FastAPI service that synchronizes Ozon FBO (fulfilled by Ozon) orders, normalizes data into SQLite, and provides analytics. It bridges the Ozon API with a Flutter frontend.

### Core Components

- **main.py**: FastAPI app initialization, router registration, CORS setup for Flutter Web (localhost only)
- **routes/**: Endpoint modules organized by domain (orders, analytics, sync, costs, enrichment)
- **services/**: Business logic (Ozon API calls, data enrichment, background sync)
- **db/database.py**: SQLAlchemy ORM models and session management (SQLite with absolute path resolution)
- **utils/common.py**: Validation helpers and shared utilities

### Data Model

**Key entities:**
- `Order`: Legacy table with raw posting data
- `OrderHeader`: Aggregated order summary (order_number, total_payout, total_commission, delivery dates)
- `OrderPosting`: Normalized posting with status, timestamps, and analytics/financial data
- `OrderProduct`: Line items within a posting (sku, offer_id, price, quantity, payout, commission)

**Normalized flow**: Ozon API → OrderPosting + OrderProduct → recalc_order_header() updates OrderHeader

## Critical Patterns & Conventions

### Async/Threading in FastAPI Routes
- **HTTPx for async Ozon calls**: Use `ozon_fbo_get_async()` / `ozon_fbo_list_async()` from `services/ozon.py`
- **Sync operations in threads**: Enrichment jobs use `asyncio.to_thread()` to avoid blocking (see [routes/enrichment_endpoints.py](routes/enrichment_endpoints.py#L25))
- **Session management**: Each thread-based enrichment gets its own `SessionLocal()` to avoid cross-thread issues

### Ozon API Integration
- **Base URL**: `https://api-seller.ozon.ru`
- **Headers**: `Client-Id`, `Api-Key`, `Content-Type: application/json`
- **Retry logic**: Automatic exponential backoff for 429, 5xx, timeouts (configurable via env)
- **Query strategy**: Always include `with: {"analytics_data": True, "financial_data": True}` flags
- **Common issue**: Ozon API is sometimes slow; DEFAULT_TIMEOUT=60s (see [services/ozon.py](services/ozon.py#L10))

### Data Enrichment Workflow
1. Fetch posting from Ozon API → parse `result` object
2. Create/update `OrderPosting` record
3. Delete old `OrderProduct` rows, insert fresh ones from Ozon financial data
4. Call `recalc_order_header(db, order_number)` to update totals
5. Financial data is nested: `financial_data.products[].{payout, commission_amount}` (see [services/enrichment.py](services/enrichment.py#L65-L75))

### Environment Configuration
Key settings in `.env`:
- `RECENT_WINDOW_HOURS`: Window for "recent" postings (default 48)
- `ENRICH_CONCURRENCY`: Max async enrichment tasks (default 4)
- `ENRICH_ON_FETCH`: Auto-enrich newly fetched postings
- `OZON_MAX_RETRIES`, `OZON_RETRY_BACKOFF_SECONDS`: API resilience

## Development Workflows

### Start the Server
```powershell
& venv\Scripts\Activate.ps1
python -m uvicorn main:app --host 127.0.0.1 --port 8080
```

### Key Endpoints (Quick Reference)
- `GET /orders` — List with filters, pagination, sorting
- `POST /orders/fbo/get` — Enrich single posting
- `POST /sync/backfill` — Fetch and enrich orders in a date range
- `GET /analytics/sales_today` — Daily delivered sales
- `GET /analytics/orders_today` — Order count today

### Adding a New Route
1. Create file in [routes/](routes/) (e.g., `routes/my_endpoint.py`)
2. Define `router = APIRouter(prefix="/my", tags=["my"])`
3. Import in [main.py](main.py) and call `app.include_router(router)`
4. Use `Depends(get_db)` for session injection

### ISO Timestamp Normalization
Always normalize date strings: `2024-01-21T10:30:45Z` → Remove trailing `Z`, parse as ISO, replace microseconds with 0, re-add `Z` (see [routes/orders.py](routes/orders.py#L10-L15))

## Common Gotchas & Solutions

**Problem**: `Order` table has raw JSON data, but normalized workflow prefers `OrderPosting`/`OrderProduct`  
**Solution**: Use `OrderPosting` for new code; keep `Order` for legacy compatibility

**Problem**: Database is SQLite with absolute path (`orders.db` at project root)  
**Solution**: Use `DB_PATH` from [db/database.py](db/database.py#L7) — do not hardcode paths

**Problem**: Session in thread-based enrichment opens and closes per posting  
**Solution**: This is intentional to avoid SQLAlchemy warnings; bulk enrichment is batched at endpoint level (see [routes/enrichment_endpoints.py](routes/enrichment_endpoints.py#L29-L35))

**Problem**: Ozon API returns `legal_info: false` by default, but you need it  
**Solution**: Add `"legal_info": True` to the `with` dict in API calls (currently disabled)

## Code Style

- **Logging**: Use `logger = logging.getLogger("uvicorn.error")` at module level
- **Error handling**: Wrap Ozon calls in try/except; re-raise as HTTPException with status_code
- **Type hints**: Use optional types (`str | None`) in function signatures
- **Pydantic models**: For request bodies, use `BaseModel` from `pydantic` (see [routes/enrichment_endpoints.py](routes/enrichment_endpoints.py#L31-L37))
- **Database queries**: Use SQLAlchemy ORM filters, not raw SQL (SQLi safety + maintainability)

## Testing & Debugging

- **Health check**: `curl http://127.0.0.1:8080/ping`
- **View logs**: Set `LOG_LEVEL=DEBUG` to see Ozon request bodies
- **Database inspection**: Use `scripts/inspect_db.py` to query tables
- **API docs**: Swagger at `http://127.0.0.1:8080/docs`
