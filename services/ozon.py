"""
Низкоуровневый клиент для работы с Ozon Seller API.
Содержит методы для выполнения HTTP-запросов к Ozon, обработки ошибок и повторных попыток (retries).
"""

import os
import logging
import httpx
import asyncio

logger = logging.getLogger("OzonAPIHub")

# Настройки берутся из переменных окружения (.env)
LOG_OZON_REQUESTS = os.getenv('LOG_OZON_REQUESTS', 'false').lower() in ('1', 'true', 'yes')
BASE_URL = "https://api-seller.ozon.ru"
DEFAULT_TIMEOUT = 60 # Таймаут ожидания ответа от Ozon (секунд)
MAX_RETRIES = int(os.getenv('OZON_MAX_RETRIES', '3'))
RETRY_BACKOFF_SECONDS = float(os.getenv('OZON_RETRY_BACKOFF_SECONDS', '1.5'))


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


async def ozon_fbo_list_async(client_id: str, api_key: str, filter_dict: dict, limit: int = 50, offset: int = 0, with_flags: dict = None):
    """
    Асинхронно получить список FBO постингов (отправлений со склада Ozon).
    Документация: https://docs.ozon.ru/api/seller/#operation/PostingAPI_GetFboPostingList
    """
    url = f"{BASE_URL}/v2/posting/fbo/list"
    body = {
        "dir": "ASC",            # Сортировка по дате (от старых к новым)
        "filter": filter_dict,    # Фильтры по датам и статусам
        "limit": limit,           # Количество записей
        "offset": offset,         # Смещение для пагинации
        "translit": True,
        # Запрашиваем аналитические и финансовые данные (комиссии, выплаты)
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
                r.raise_for_status() # Вызывает ошибку для кодов 4xx/5xx
                return r.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.error(f"Ozon Auth Failed for client {client_id[:4]}...")
                raise # При ошибке авторизации сразу прерываемся

            # Если превышен лимит запросов (429) или ошибка сервера (5xx), пробуем еще раз
            if e.response.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                attempt += 1
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            # Ошибки сети и таймауты тоже пробуем переотправить
            if attempt < MAX_RETRIES:
                attempt += 1
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise


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

# Синхронные обёртки для вызова из старого кода или REPL
def ozon_fbo_list(client_id: str, api_key: str, filter_dict: dict, limit: int, offset: int, with_flags: dict = None):
    """Синхронная версия получения списка постингов."""
    return asyncio.run(ozon_fbo_list_async(client_id, api_key, filter_dict, limit, offset, with_flags))

def ozon_fbo_get(client_id: str, api_key: str, posting_number: str):
    """Синхронная версия получения деталей постинга."""
    return asyncio.run(ozon_fbo_get_async(client_id, api_key, posting_number))
