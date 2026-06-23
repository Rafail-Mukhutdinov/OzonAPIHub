"""
Низкоуровневый клиент для работы с Ozon Seller API.
Содержит методы выполнения HTTP-запросов к Ozon, обработки ошибок и повторных попыток (retries).

Использует переиспользуемый httpx.AsyncClient с пулом соединений (keep-alive),
что критично для производительности при массовом обогащении и бэкфилле.
Клиент инициализируется через init_http_client() в lifespan FastAPI и в on_startup
воркера ARQ, закрывается через close_http_client(). При вызове из скриптов/REPL
(синхронные обёртки) создаётся временный клиент в собственном цикле событий.
"""

import os
import logging
import httpx
import asyncio

logger = logging.getLogger("OzonAPIHub")

# Настройки берутся из переменных окружения (.env)
LOG_OZON_REQUESTS = os.getenv('LOG_OZON_REQUESTS', 'false').lower() in ('1', 'true', 'yes')
BASE_URL = "https://api-seller.ozon.ru"
DEFAULT_TIMEOUT = 60  # Таймаут ожидания ответа от Ozon (секунд)
MAX_RETRIES = int(os.getenv('OZON_MAX_RETRIES', '3'))
RETRY_BACKOFF_SECONDS = float(os.getenv('OZON_RETRY_BACKOFF_SECONDS', '1.5'))

# HTTP-коды, на которые ретраим (временные сбои Ozon или сети)
_RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# Модульный синглтон httpx-клиента.
# Живёт в одном цикле событий (event loop) — например, в цикле uvicorn или воркера ARQ.
# НЕ должен переиспользоваться между разными asyncio.run() (см. синхронные обёртки ниже).
_client: httpx.AsyncClient | None = None


def init_http_client() -> httpx.AsyncClient:
    """
    Создаёт и возвращает переиспользуемый httpx.AsyncClient с пулом соединений.
    Безопасно вызывать повторно: если клиент уже жив — возвращает его.
    Вызывать в lifespan FastAPI и в on_startup воркера ARQ.
    """
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=httpx.Limits(
                max_connections=int(os.getenv('OZON_MAX_CONNECTIONS', '50')),
                max_keepalive_connections=int(os.getenv('OZON_KEEPALIVE_CONNECTIONS', '20')),
                keepalive_expiry=float(os.getenv('OZON_KEEPALIVE_EXPIRY', '30')),
            ),
        )
        logger.info("HTTP client for Ozon API initialized (connection pool)")
    return _client


async def close_http_client() -> None:
    """
    Закрывает пул соединений httpx-клиента.
    Вызывать при остановке приложения/воркера (shutdown).
    """
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        logger.info("HTTP client for Ozon API closed")
    _client = None


def _get_client() -> httpx.AsyncClient:
    """
    Возвращает текущий синглтон-клиент. При необходимости создаёт лениво.
    Используется только на асинхронных путях (сервер/воркер), где цикл событий долгоживущий.
    """
    if _client is None or _client.is_closed:
        init_http_client()
    return _client


def _get_headers(client_id: str, api_key: str) -> dict:
    """
    Генерация HTTP-заголовков для аутентификации в Ozon API.
    Требует Client-Id и Api-Key конкретного магазина.
    """
    if not client_id or not api_key:
        raise ValueError("User OZON credentials are missing")

    return {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    body: dict,
    op_label: str,
) -> dict:
    """
    Выполняет POST-запрос к Ozon с retry на временные сбои.

    Стратегия:
    - 401 — ошибка авторизации, НЕ ретраим (бессмысленно), пробрасываем сразу.
    - 429/5xx и сетевые ошибки — ретраим с линейным backoff (RETRY_BACKOFF_SECONDS * попытка).
    - Прочие 4xx — не ретрябельные, пробрасываем сразу.
    - При исчерпании попыток пробрасываем последнее исключение после детального логирования.

    Контракт: успех => dict (распарсенный JSON), сбой => исключение.
    Функция никогда не возвращает None.
    """
    last_exc: Exception | None = None

    # range(MAX_RETRIES + 1) => попытки 0..MAX_RETRIES включительно (всего MAX_RETRIES + 1 шт.)
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = await client.post(url, headers=headers, json=body, timeout=DEFAULT_TIMEOUT)
            r.raise_for_status()  # Вызывает httpx.HTTPStatusError для кодов 4xx/5xx
            return r.json()
        except httpx.HTTPStatusError as e:
            last_exc = e
            status = e.response.status_code

            # Ошибки авторизации не ретраим — повтор даст тот же результат
            if status == 401:
                logger.error(f"Ozon Auth Failed ({op_label}): HTTP 401")
                raise

            if status in _RETRY_STATUS_CODES and attempt < MAX_RETRIES:
                backoff = RETRY_BACKOFF_SECONDS * (attempt + 1)
                logger.warning(
                    f"Ozon {op_label}: HTTP {status}, retry {attempt + 1}/{MAX_RETRIES} через {backoff:.1f}s"
                )
                await asyncio.sleep(backoff)
                continue

            # Либо неретрябельный 4xx, либо исчерпаны попытки на ретрябельной ошибке
            logger.error(f"Ozon {op_label}: HTTP {status} после {attempt + 1} попытк(и/ок), запрос отменён")
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                backoff = RETRY_BACKOFF_SECONDS * (attempt + 1)
                logger.warning(
                    f"Ozon {op_label}: сетевая ошибка {type(e).__name__}, "
                    f"retry {attempt + 1}/{MAX_RETRIES} через {backoff:.1f}s"
                )
                await asyncio.sleep(backoff)
                continue
            logger.error(f"Ozon {op_label}: {type(e).__name__} после {attempt + 1} попытк(и/ок), запрос отменён")
            raise

    # Защитный запасной выход: теоретически недостижимо,
    # т.к. любая ветка выше либо возвращает значение, либо пробрасывает исключение.
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"Ozon {op_label}: неожиданный выход из retry-цикла без результата")


async def ozon_fbo_list_async(
    client_id: str,
    api_key: str,
    filter_dict: dict,
    limit: int = 50,
    offset: int = 0,
    with_flags: dict = None,
    sort_dir: str = "ASC",
):
    """Асинхронно получить список FBO постингов."""
    url = f"{BASE_URL}/v2/posting/fbo/list"
    body = {
        "dir": sort_dir,            # По умолчанию ASC (от старых к новым)
        "filter": filter_dict,
        "limit": limit,
        "offset": offset,
        "translit": True,
        "with": with_flags or {"analytics_data": True, "financial_data": True, "legal_info": False},
    }
    headers = _get_headers(client_id, api_key)

    # Логируем только начало постраничного прохода, чтобы не засорять логи
    if offset == 0:
        logger.info(f"Ozon API: Запрос списка заказов ({sort_dir}, since={filter_dict.get('since')})")
    if LOG_OZON_REQUESTS:
        logger.debug(f"Ozon list request for client {client_id[:4]}...: {body}")

    return await _post_with_retry(
        _get_client(), url, headers, body,
        op_label=f"fbo/list client={client_id[:4]}"
    )


async def ozon_fbo_get_async(client_id: str, api_key: str, posting_number: str):
    """
    Асинхронно получить полные детали конкретного FBO постинга.
    Используется для получения списка товаров внутри заказа и их точной стоимости/комиссий.
    """
    url = f"{BASE_URL}/v2/posting/fbo/get"
    body = {
        "posting_number": posting_number,
        "translit": True,
        "with": {"analytics_data": True, "financial_data": True, "legal_info": False},
    }
    headers = _get_headers(client_id, api_key)

    return await _post_with_retry(
        _get_client(), url, headers, body,
        op_label=f"fbo/get pn={posting_number}"
    )


async def ozon_product_info_list_async(client_id: str, api_key: str, skus: list[int]):
    """
    Асинхронно получить информацию о товарах по списку SKU.
    Используется для получения ссылок на изображения.
    """
    if not skus:
        return {"items": []}

    url = f"{BASE_URL}/v3/product/info/list"
    body = {
        "sku": skus
    }
    headers = _get_headers(client_id, api_key)

    return await _post_with_retry(
        _get_client(), url, headers, body,
        op_label=f"product/info/list(v3) count={len(skus)}"
    )


# Синхронные обёртки для вызова из старого кода или REPL.
# ВАЖНО: asyncio.run() создаёт и уничтожает собственный цикл событий,
# поэтому синглтон-клиент здесь НЕ переиспользуется — создаётся временный.
def ozon_fbo_list(client_id: str, api_key: str, filter_dict: dict, limit: int, offset: int, with_flags: dict = None):
    """Синхронная версия получения списка постингов (legacy/REPL)."""
    url = f"{BASE_URL}/v2/posting/fbo/list"
    body = {
        "dir": "ASC",
        "filter": filter_dict,
        "limit": limit,
        "offset": offset,
        "translit": True,
        "with": with_flags or {"analytics_data": True, "financial_data": True, "legal_info": False},
    }
    headers = _get_headers(client_id, api_key)

    async def _run():
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as tmp_client:
            return await _post_with_retry(
                tmp_client, url, headers, body,
                op_label=f"fbo/list(sync) client={client_id[:4]}"
            )

    return asyncio.run(_run())


def ozon_fbo_get(client_id: str, api_key: str, posting_number: str):
    """Синхронная версия получения деталей постинга (legacy/REPL)."""
    url = f"{BASE_URL}/v2/posting/fbo/get"
    body = {
        "posting_number": posting_number,
        "translit": True,
        "with": {"analytics_data": True, "financial_data": True, "legal_info": False},
    }
    headers = _get_headers(client_id, api_key)

    async def _run():
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as tmp_client:
            return await _post_with_retry(
                tmp_client, url, headers, body,
                op_label=f"fbo/get(sync) pn={posting_number}"
            )

    return asyncio.run(_run())
