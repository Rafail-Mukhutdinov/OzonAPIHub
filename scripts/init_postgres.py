"""
Скрипт инициализации и управления структурой PostgreSQL базы данных для OzonAPIHub.

Назначение:
    - Позволяет администратору создать необходимые таблицы при первом развертывании.
    - Используется для инспекции текущей схемы данных (колонки, типы, индексы).
    - Предоставляет инструменты для очистки базы (удаление таблиц).

Логика работы:
    - Скрипт предоставляет интерактивное меню в консоли.
    - Использует SQLAlchemy MetaData для автоматического создания таблиц на основе моделей в коде.
    - Использует SQLAlchemy Inspector для чтения метаданных напрямую из живой БД.

Ключевые команды:
    1. Показать таблицы: Выводит список всех созданных таблиц.
    2. Создать таблицы: Выполняет миграцию (Base.metadata.create_all).
    3. Структура: Выводит детальное описание каждой колонки и внешних связей (Foreign Keys).
    4. Удалить: Полная очистка БД.

Требования:
    - В .env должен быть корректный DATABASE_URL.
    - Права суперпользователя или владельца схемы в PostgreSQL.
"""

import sys
import os

# Добавляем корень проекта в путь для импорта моделей из папки db
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from db.database import engine, Base, User, Order, OrderHeader, OrderPosting, OrderProduct, Cost
from sqlalchemy import inspect

def check_tables_exist():
    """
    Проверяет наличие таблиц в базе данных.
    Использует SQLAlchemy Inspector для получения актуального списка из БД.
    """
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    print(f"Существующие таблицы в БД: {existing_tables}")
    return existing_tables

def create_all_tables():
    """
    Автоматическое создание всех таблиц.
    Читает все классы, унаследованные от Base (User, Order и др.),
    генерирует SQL 'CREATE TABLE IF NOT EXISTS' и выполняет его.
    """
    print("Запуск процесса создания таблиц...")
    Base.metadata.create_all(bind=engine)
    print("✓ Таблицы успешно созданы или уже существуют!")

def drop_all_tables():
    """
    ОПАСНО: Полное удаление структуры данных.
    Требует подтверждения 'yes' в консоли.
    """
    confirm = input("ВНИМАНИЕ! Все данные и таблицы будут безвозвратно удалены. Продолжить? (yes/no): ")
    if confirm.lower() == 'yes':
        print("Удаление таблиц...")
        Base.metadata.drop_all(bind=engine)
        print("✓ База данных очищена.")
    else:
        print("Операция отменена пользователем.")

def show_schema():
    """
    Выводит детальную информацию о колонках, типах данных и индексах.
    Полезно для проверки корректности миграций.
    """
    inspector = inspect(engine)
    for table_name in inspector.get_table_names():
        print(f"\n{'='*60}")
        print(f"Таблица: {table_name}")
        print('='*60)
        
        # Список колонок
        columns = inspector.get_columns(table_name)
        for col in columns:
            nullable = "NULL" if col['nullable'] else "NOT NULL"
            print(f"  {col['name']:30} {str(col['type']):20} {nullable}")
        
        # Вывод внешних ключей (Foreign Keys) - связи между таблицами
        fks = inspector.get_foreign_keys(table_name)
        if fks:
            print("\n  Внешние ключи (Связи):")
            for fk in fks:
                print(f"    {fk['constrained_columns']} -> {fk['referred_table']}.{fk['referred_columns']}")
        
        # Индексы (Indexes) - для ускорения поиска
        indexes = inspector.get_indexes(table_name)
        if indexes:
            print("\n  Индексы:")
            for idx in indexes:
                print(f"    {idx['name']}: {idx['column_names']}")

def main():
    """
    Точка входа: интерактивный CLI.
    """
    print("="*60)
    print("OzonAPIHub - Управление базой данных PostgreSQL")
    print("="*60)
    print(f"Текущий DATABASE_URL: {os.getenv('DATABASE_URL', 'НЕ УСТАНОВЛЕН')}\n")
    
    while True:
        print("\nВыберите действие:")
        print("1. Список таблиц")
        print("2. Создать структуру (Initial setup)")
        print("3. Просмотр схемы (колонки и индексы)")
        print("4. Удалить всё (DROP ALL)")
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
            print("Выход из скрипта...")
            break
        else:
            print("Неверный ввод, попробуйте снова.")

if __name__ == "__main__":
    main()
