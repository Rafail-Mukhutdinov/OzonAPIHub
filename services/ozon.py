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
        raise ValueError("User OZON credentials are missing")
        
    return {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }


async def ozon_fbo_list_async(client_id: str, api_key: str, filter_dict: dict, limit: int, offset: int, with_flags: dict):
    """
    Асинхронно получить список FBO постингов.
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
        logger.debug(f"Ozon list request for client {client_id[:4]}...: {body}")
    
    attempt = 0
    while attempt <= MAX_RETRIES:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(url, headers=headers, json=body, timeout=DEFAULT_TIMEOUT)
                r.raise_for_status()
                return r.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.error(f"Ozon Auth Failed for client {client_id[:4]}...")
                raise
            if e.response.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                attempt += 1
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            if attempt < MAX_RETRIES:
                attempt += 1
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
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

    attempt = 0
    while attempt <= MAX_RETRIES:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(url, headers=headers, json=body, timeout=DEFAULT_TIMEOUT)
                r.raise_for_status()
                return r.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise
            if e.response.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                attempt += 1
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            if attempt < MAX_RETRIES:
                attempt += 1
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise

# Синхронные обёртки - теперь принимают credentials
def ozon_fbo_list(client_id: str, api_key: str, filter_dict: dict, limit: int, offset: int, with_flags: dict = None):
    return asyncio.run(ozon_fbo_list_async(client_id, api_key, filter_dict, limit, offset, with_flags))

def ozon_fbo_get(client_id: str, api_key: str, posting_number: str):
    return asyncio.run(ozon_fbo_get_async(client_id, api_key, posting_number))
