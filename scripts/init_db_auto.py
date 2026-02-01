#!/usr/bin/env python3
"""
Автоматическая инициализация PostgreSQL базы данных для Docker контейнера
"""
import os
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, inspect
from db.database import Base, User, Order, OrderHeader, OrderPosting, OrderProduct

def init_database():
    """Автоматически создает все таблицы в базе данных"""
    
    # Получаем DATABASE_URL из переменных окружения
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: DATABASE_URL не установлен в переменных окружения!")
        sys.exit(1)
    
    print("=" * 60)
    print("OzonAPIHub - Автоматическая инициализация базы данных")
    print("=" * 60)
    print(f"Database URL: {database_url.replace(database_url.split(':')[2].split('@')[0], '***')}")
    print()
    
    try:
        # Создаем engine
        engine = create_engine(database_url)
        
        # Проверяем существующие таблицы
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        
        if existing_tables:
            print(f"✓ Найдено существующих таблиц: {len(existing_tables)}")
            print(f"  Таблицы: {', '.join(existing_tables)}")
        else:
            print("✗ Таблицы не найдены. Создаем...")
        
        print()
        print("Создание всех таблиц...")
        
        # Создаем все таблицы
        Base.metadata.create_all(bind=engine)
        
        # Проверяем результат
        inspector = inspect(engine)
        new_tables = inspector.get_table_names()
        
        print()
        print("=" * 60)
        print(f"✓ Успешно! Всего таблиц: {len(new_tables)}")
        print()
        print("Список таблиц:")
        for table in new_tables:
            print(f"  - {table}")
        
        print()
        print("База данных готова к работе!")
        print("=" * 60)
        
        return 0
        
    except Exception as e:
        print()
        print("=" * 60)
        print(f"✗ ОШИБКА при инициализации базы данных:")
        print(f"  {type(e).__name__}: {e}")
        print("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(init_database())
