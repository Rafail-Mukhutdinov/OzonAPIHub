"""
Скрипт для ручного запуска синхронизации заказов.

Назначение:
    - Используется для мгновенного получения новых заказов из Ozon API, 
      не дожидаясь срабатывания планировщика (celery/cron).
    - Полезен при отладке процесса синхронизации.

Логика работы:
    1. Находит в базе данных первого активного пользователя, у которого есть ключи API Ozon.
    2. Инициализирует HTTP-клиент для работы с внешними запросами.
    3. Вызывает 'sync_user_orders', которая скачивает список новых заказов и сохраняет их в БД.

Ключевые переменные:
    - user: Объект пользователя, для которого запускается синхронизация.
    - DATABASE_URL: Адрес БД (подставляется дефолтный для локальной разработки, если нет в .env).
"""
import sys
import os
import asyncio
from datetime import datetime

# Настройка путей для доступа к модулям проекта
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# Установка URL базы данных по умолчанию, если переменная отсутствует в окружении
if not os.getenv("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "postgresql://ozonuser:ozonpass@localhost:5433/ozondb"

from db.database import SessionLocal, User, OzonCredential
from services.sync import sync_user_orders
from services.ozon import init_http_client, close_http_client

async def main():
    """
    Основная логика принудительной синхронизации.
    """
    db = SessionLocal()
    try:
        # Ищем любого пользователя с активными учетными данными Ozon
        user = db.query(User).join(OzonCredential).filter(OzonCredential.is_active == True).first()
        if not user:
            print("Активные пользователи с API-ключами Ozon не найдены.")
            return

        print(f"Запуск синхронизации для пользователя: {user.id} ({user.email})...")
        
        # Подготовка HTTP сессии
        init_http_client()
        
        # Запуск штатного механизма синхронизации
        success = await sync_user_orders(user, db)
        
        if success:
            print("Синхронизация успешно завершена!")
        else:
            print("Синхронизация не удалась или новых данных нет.")
            
    except Exception as e:
        print(f"Ошибка при ручной синхронизации: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Обязательное закрытие соединений
        await close_http_client()
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
