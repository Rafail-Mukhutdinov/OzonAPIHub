import os
import sys
import requests
from dotenv import load_dotenv

"""
Запрос информации об отправлении (FBO) по номеру постинга.
API: POST https://api-seller.ozon.ru/v2/posting/fbo/get

Использование:
  python scripts/get_fbo_posting.py 35142868-0217-1

Токены берутся из .env: OZON_CLIENT_ID, OZON_API_KEY
"""

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/get_fbo_posting.py <posting_number>")
        sys.exit(1)

    posting_number = sys.argv[1]

    load_dotenv()
    client_id = os.getenv('OZON_CLIENT_ID')
    api_key = os.getenv('OZON_API_KEY')
    if not client_id or not api_key:
        print("[error] OZON_CLIENT_ID/OZON_API_KEY не заданы в .env")
        sys.exit(1)

    url = 'https://api-seller.ozon.ru/v2/posting/fbo/get'
    headers = {
        'Client-Id': client_id,
        'Api-Key': api_key,
        'Content-Type': 'application/json'
    }
    body = {
        "posting_number": posting_number,
        "translit": True,
        "with": {
            "analytics_data": True,
            "financial_data": True,
            "legal_info": False
        }
    }

    print('Request body:', body)
    resp = requests.post(url, headers=headers, json=body, timeout=60)
    print('STATUS', resp.status_code)
    try:
        print(resp.json())
    except Exception:
        print(resp.text[:1000])

if __name__ == '__main__':
    main()
