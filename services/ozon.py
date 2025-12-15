import os
import logging
import requests
import time

LOG_OZON_REQUESTS = os.getenv('LOG_OZON_REQUESTS', 'false').lower() in ('1', 'true', 'yes')
BASE_URL = "https://api-seller.ozon.ru"
DEFAULT_TIMEOUT = 60
MAX_RETRIES = int(os.getenv('OZON_MAX_RETRIES', '3'))
RETRY_BACKOFF_SECONDS = float(os.getenv('OZON_RETRY_BACKOFF_SECONDS', '1.5'))


def _headers():
    client_id = os.getenv("OZON_CLIENT_ID")
    api_key = os.getenv("OZON_API_KEY")
    if not client_id or not api_key:
        raise RuntimeError("OZON credentials not configured")
    return {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }


def ozon_fbo_list(filter_dict: dict, limit: int, offset: int, with_flags: dict):
    url = f"{BASE_URL}/v2/posting/fbo/list"
    body = {
        "dir": "ASC",
        "filter": filter_dict,
        "limit": limit,
        "offset": offset,
        "translit": True,
        "with": with_flags or {"analytics_data": True, "financial_data": True, "legal_info": False},
    }
    if LOG_OZON_REQUESTS:
        logging.debug(f"Ozon list body: {body}")
    attempt = 0
    while True:
        try:
            r = requests.post(url, headers=_headers(), json=body, timeout=DEFAULT_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            status = getattr(getattr(e, 'response', None), 'status_code', None)
            retryable = (
                isinstance(e, (requests.Timeout, requests.ConnectionError)) or
                (status in (429, 500, 502, 503, 504))
            )
            if retryable and attempt < MAX_RETRIES:
                attempt += 1
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise


def ozon_fbo_get(posting_number: str):
    url = f"{BASE_URL}/v2/posting/fbo/get"
    body = {
        "posting_number": posting_number,
        "translit": True,
        "with": {"analytics_data": True, "financial_data": True, "legal_info": False},
    }
    if LOG_OZON_REQUESTS:
        logging.debug(f"Ozon get body: {body}")
    attempt = 0
    while True:
        try:
            r = requests.post(url, headers=_headers(), json=body, timeout=DEFAULT_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            status = getattr(getattr(e, 'response', None), 'status_code', None)
            retryable = (
                isinstance(e, (requests.Timeout, requests.ConnectionError)) or
                (status in (429, 500, 502, 503, 504))
            )
            if retryable and attempt < MAX_RETRIES:
                attempt += 1
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise
