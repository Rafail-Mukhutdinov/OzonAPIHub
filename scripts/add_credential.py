import os
import requests
from dotenv import load_dotenv

load_dotenv()

email = os.getenv('TEST_EMAIL')
password = os.getenv('TEST_PASSWORD')
client_id = os.getenv('OZON_CLIENT_ID')
api_key = os.getenv('OZON_API_KEY')

if not email or not password:
    raise SystemExit('Missing TEST_EMAIL or TEST_PASSWORD environment variables')
if not client_id or not api_key:
    raise SystemExit('Missing OZON_CLIENT_ID or OZON_API_KEY in .env')

base = os.getenv('API_URL', 'http://localhost:8080')

resp = requests.post(f'{base}/auth/login', data={'username': email, 'password': password})
print('login status:', resp.status_code)
resp.raise_for_status()

token = resp.json().get('access_token')
headers = {'Authorization': f'Bearer {token}'}

payload = {
    'marketplace': 'ozon',
    'name': 'Основной',
    'client_id': client_id,
    'api_key': api_key
}

resp = requests.post(f'{base}/auth/me/ozon-credentials', json=payload, headers=headers)
print('create credential status:', resp.status_code)
print(resp.text)
