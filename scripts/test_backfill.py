#!/usr/bin/env python3
"""
Тестовый скрипт для запуска первичной загрузки (backfill) и отслеживания статуса.
"""
import os
import sys
import json
import time
import requests
from datetime import datetime

# Конфиг
API_URL = os.getenv('API_URL', 'http://localhost:8080')
TEST_EMAIL = os.getenv('TEST_EMAIL', 'test@example.com')  # Измените на реальный email
TEST_PASSWORD = os.getenv('TEST_PASSWORD', 'Test@123456')  # Измените на реальный пароль

def log(msg):
    """Логирование с временем"""
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[{ts}] {msg}')

def main():
    session = requests.Session()
    
    # Шаг 1: Регистрация
    log('📝 Регистрация нового пользователя...')
    try:
        resp = session.post(f'{API_URL}/auth/register', json={
            'email': TEST_EMAIL,
            'password': TEST_PASSWORD,
            'confirm_password': TEST_PASSWORD
        })
        resp.raise_for_status()
        log(f'✅ Регистрация успешна')
    except Exception as e:
        log(f'⚠️ Регистрация: {e}')
    
    # Шаг 2: Логин
    log('🔐 Вход в систему...')
    try:
        resp = session.post(f'{API_URL}/auth/login', data={
            'username': TEST_EMAIL,
            'password': TEST_PASSWORD
        })
        resp.raise_for_status()
        token = resp.json()['access_token']
        session.headers['Authorization'] = f'Bearer {token}'
        log(f'✅ Логин успешен, токен получен')
    except Exception as e:
        log(f'❌ Ошибка логина: {e}')
        return
    
    # Шаг 3: Проверить текущий статус
    log('📊 Проверка текущего статуса...')
    try:
        resp = session.get(f'{API_URL}/auth/me/sync-status')
        resp.raise_for_status()
        status = resp.json()
        log(f'Статус: {json.dumps(status, indent=2)}')
    except Exception as e:
        log(f'⚠️ Ошибка получения статуса: {e}')
    
    # Шаг 4: Запустить первичную загрузку
    log('🚀 Запуск первичной загрузки (backfill)...')
    try:
        resp = session.post(f'{API_URL}/sync/initial')
        resp.raise_for_status()
        result = resp.json()
        log(f'✅ Загрузка запущена: {json.dumps(result, indent=2)}')
    except Exception as e:
        log(f'❌ Ошибка запуска: {e}')
        return
    
    # Шаг 5: Мониторить статус каждые 2 секунды
    log('⏱️ Мониторинг статуса (обновление каждые 2 сек)...')
    while True:
        try:
            resp = session.get(f'{API_URL}/auth/me/sync-status')
            resp.raise_for_status()
            status = resp.json()
            
            is_syncing = status['is_syncing']
            msg = status['status_message']
            total = status['total_records_synced']
            
            if is_syncing:
                print(f'\r⏳ {msg} ({total} записей)', end='', flush=True)
            else:
                print()  # Новая строка
                log(f'✅ ЗАВЕРШЕНО: {msg}')
                log(f'   Всего загружено: {total} записей')
                break
            
            time.sleep(2)
        except KeyboardInterrupt:
            log('⛔ Прервано пользователем')
            break
        except Exception as e:
            log(f'❌ Ошибка мониторинга: {e}')
            break
    
    log('✨ Готово!')

if __name__ == '__main__':
    main()
