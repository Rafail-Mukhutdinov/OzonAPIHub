"""
Скрипт для автоматического добавления API-ключей Ozon тестовому пользователю.

Назначение:
    - Используется разработчиком для быстрой настройки тестового окружения.
    - Имитирует действия пользователя через веб-интерфейс (Login -> Add Credentials).

Логика работы:
    1. Считывает логин/пароль и ключи Ozon из переменных окружения (.env).
    2. Выполняет авторизацию в приложении (POST /auth/login) и получает токен.
    3. Отправляет запрос на сохранение API-ключей (POST /auth/me/ozon-credentials).

Ключевые переменные:
    - TEST_EMAIL / TEST_PASSWORD: Данные для входа в Hub.
    - OZON_CLIENT_ID / OZON_API_KEY: Ключи продавца из кабинета Ozon Seller.
    - base: URL API сервера приложения (по умолчанию localhost:8080).
"""
import os
import requests
from dotenv import load_dotenv

# Загрузка настроек из файла .env
load_dotenv()

# Считывание необходимых параметров
email = os.getenv('TEST_EMAIL')
password = os.getenv('TEST_PASSWORD')
client_id = os.getenv('OZON_CLIENT_ID')
api_key = os.getenv('OZON_API_KEY')

# Валидация входных данных
if not email or not password:
    raise SystemExit('Ошибка: Не установлены TEST_EMAIL или TEST_PASSWORD в .env')
if not client_id or not api_key:
    raise SystemExit('Ошибка: Не установлены OZON_CLIENT_ID или OZON_API_KEY в .env')

# URL адрес сервера API
base = os.getenv('API_URL', 'http://localhost:8080')

# Шаг 1: Авторизация для получения JWT токена
print(f"Попытка входа для {email}...")
resp = requests.post(f'{base}/auth/login', data={'username': email, 'password': password})
print('Статус авторизации:', resp.status_code)
resp.raise_for_status()

token = resp.json().get('access_token')
headers = {'Authorization': f'Bearer {token}'}

# Шаг 2: Создание записи с ключами Ozon в профиле пользователя
payload = {
    'marketplace': 'ozon',
    'name': 'Основной магазин',
    'client_id': client_id,
    'api_key': api_key
}

print("Добавление API-ключей Ozon...")
resp = requests.post(f'{base}/auth/me/ozon-credentials', json=payload, headers=headers)
print('Статус создания ключей:', resp.status_code)
print('Ответ сервера:', resp.text)
