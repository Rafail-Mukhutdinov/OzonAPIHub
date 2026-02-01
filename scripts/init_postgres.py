"""
Скрипт инициализации PostgreSQL базы данных для OzonAPIHub SaaS.

Использование:
    python scripts/init_postgres.py

Перед запуском убедитесь, что:
1. PostgreSQL установлен и запущен
2. Создана база данных: CREATE DATABASE ozondb;
3. Создан пользователь с правами: 
   CREATE USER ozonuser WITH PASSWORD 'ozonpass';
   GRANT ALL PRIVILEGES ON DATABASE ozondb TO ozonuser;
4. В .env установлена переменная DATABASE_URL
"""

import sys
import os

# Добавляем корень проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from db.database import engine, Base, User, Order, OrderHeader, OrderPosting, OrderProduct, Cost
from sqlalchemy import inspect

def check_tables_exist():
    """Проверка существования таблиц."""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    print(f"Существующие таблицы: {existing_tables}")
    return existing_tables

def create_all_tables():
    """Создание всех таблиц согласно моделям."""
    print("Создание таблиц...")
    Base.metadata.create_all(bind=engine)
    print("✓ Таблицы успешно созданы!")

def drop_all_tables():
    """ОПАСНО: Удаление всех таблиц."""
    confirm = input("ВНИМАНИЕ! Все данные будут удалены. Продолжить? (yes/no): ")
    if confirm.lower() == 'yes':
        print("Удаление таблиц...")
        Base.metadata.drop_all(bind=engine)
        print("✓ Таблицы удалены")
    else:
        print("Отменено")

def show_schema():
    """Показать структуру таблиц."""
    inspector = inspect(engine)
    for table_name in inspector.get_table_names():
        print(f"\n{'='*60}")
        print(f"Таблица: {table_name}")
        print('='*60)
        columns = inspector.get_columns(table_name)
        for col in columns:
            nullable = "NULL" if col['nullable'] else "NOT NULL"
            print(f"  {col['name']:30} {str(col['type']):20} {nullable}")
        
        # Foreign keys
        fks = inspector.get_foreign_keys(table_name)
        if fks:
            print("\n  Foreign Keys:")
            for fk in fks:
                print(f"    {fk['constrained_columns']} -> {fk['referred_table']}.{fk['referred_columns']}")
        
        # Indexes
        indexes = inspector.get_indexes(table_name)
        if indexes:
            print("\n  Indexes:")
            for idx in indexes:
                print(f"    {idx['name']}: {idx['column_names']}")

def main():
    print("="*60)
    print("OzonAPIHub - PostgreSQL Database Initialization")
    print("="*60)
    print(f"Database URL: {os.getenv('DATABASE_URL', 'NOT SET')}\n")
    
    while True:
        print("\nВыберите действие:")
        print("1. Показать существующие таблицы")
        print("2. Создать все таблицы")
        print("3. Показать структуру таблиц")
        print("4. Удалить все таблицы (ОПАСНО!)")
        print("0. Выход")
        
        choice = input("\nВаш выбор: ").strip()
        
        if choice == "1":
            check_tables_exist()
        elif choice == "2":
            create_all_tables()
        elif choice == "3":
            show_schema()
        elif choice == "4":
            drop_all_tables()
        elif choice == "0":
            print("Выход...")
            break
        else:
            print("Неверный выбор!")

if __name__ == "__main__":
    main()
