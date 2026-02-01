import os
import logging
import httpx
import asyncio

logger = logging.getLogger("uvicorn.error")

LOG_OZON_REQUESTS = os.getenv('LOG_OZON_REQUESTS', 'false').lower() in ('1', 'true', 'yes')
BASE_URL = "https://api-seller.ozon.ru"
DEFAULT_TIMEOUT = 60
MAX_RETRIES = int(os.getenv('OZON_MAX_RETRIES', '3'))
RETRY_BACKOFF_SECONDS = float(os.getenv('OZON_RETRY_BACKOFF_SECONDS', '1.5'))


def _get_headers(client_id: str, api_key: str) -> dict:
    """Генерация заголовков для конкретного пользователя."""
    if not client_id or not api_key:
        # В SaaS режиме отсутствие ключей - это ошибка уровня пользователя,
        # которая должна обрабатываться выше.
        raise ValueError("User OZON credentials are missing")
        
    return {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }


async def ozon_fbo_list_async(client_id: str, api_key: str, filter_dict: dict, limit: int, offset: int, with_flags: dict):
    """
    Асинхронно получить список FBO постингов.
    ВАЖНО: Принимает client_id и api_key аргументами.
    """
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

    if LOG_OZON_REQUESTS:
        logger.debug(f"Ozon list body (User {client_id[:4]}...): {body}")
    
    attempt = 0
    while attempt <= MAX_RETRIES:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(url, headers=headers, json=body, timeout=DEFAULT_TIMEOUT)
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError as e:
            status = getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
            # Ошибка 401 (Unauthorized) означает неверные ключи пользователя - не ретраим
            if status == 401:
                logger.error(f"Ozon Auth Failed for client {client_id[:4]}...")
                raise 

            retryable = (
                isinstance(e, (httpx.TimeoutException, httpx.ConnectError)) or
                (status in (429, 500, 502, 503, 504))
            )
            if retryable and attempt < MAX_RETRIES:
                attempt += 1
                wait_time = RETRY_BACKOFF_SECONDS * attempt
                await asyncio.sleep(wait_time)
                continue
            raise


async def ozon_fbo_get_async(client_id: str, api_key: str, posting_number: str):
    """Асинхронно получить детали FBO постинга."""
    url = f"{BASE_URL}/v2/posting/fbo/get"
    body = {
        "posting_number": posting_number,
        "translit": True,
        "with": {"analytics_data": True, "financial_data": True, "legal_info": False},
    }
    
    headers = _get_headers(client_id, api_key)

    if LOG_OZON_REQUESTS:
        logger.debug(f"Ozon get body: {body}")
    
    attempt = 0
    while attempt <= MAX_RETRIES:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(url, headers=headers, json=body, timeout=DEFAULT_TIMEOUT)
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError as e:
            status = getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
            if status == 401:
                logger.error(f"Ozon Auth Failed for client {client_id[:4]}...")
                raise

            retryable = (
                isinstance(e, (httpx.TimeoutException, httpx.ConnectError)) or
                (status in (429, 500, 502, 503, 504))
            )
            if retryable and attempt < MAX_RETRIES:
                attempt += 1
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise


# Синхронные обёртки для обратной совместимости (используются в services/sync.py)
def ozon_fbo_list(filter_dict: dict, limit: int, offset: int, with_flags: dict = None):
    """Синхронная обёртка вокруг async функции."""
    return asyncio.run(ozon_fbo_list_async(filter_dict, limit, offset, with_flags))


def ozon_fbo_get(posting_number: str):
    """Синхронная обёртка вокруг async функции."""
    return asyncio.run(ozon_fbo_get_async(posting_number))
