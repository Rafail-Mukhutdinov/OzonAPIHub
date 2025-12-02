import os
import requests
from dotenv import load_dotenv
load_dotenv()
client_id = os.getenv('OZON_CLIENT_ID')
api_key = os.getenv('OZON_API_KEY')
url = 'https://api-seller.ozon.ru/v2/posting/fbo/list'
headers = {
    'Client-Id': client_id,
    'Api-Key': api_key,
    'Content-Type': 'application/json'
}
body = {
    'dir': 'ASC',
    'filter': {'since': '2025-12-01T00:00:00Z', 'to': '2025-12-02T23:59:59Z', 'status': ''},
    'limit': 50,
    'offset': 0,
    'translit': True,
    'with': {'analytics_data': True, 'financial_data': True, 'legal_info': False}
}
print('Request body:', body)
resp = requests.post(url, headers=headers, json=body)
print('STATUS', resp.status_code)
print('RESPONSE:', resp.text)
