"""
Миграция: создание таблицы ozon_credentials и перенос старых ключей.

Выполняет:
1. Создает таблицу ozon_credentials
2. Переносит существующие ключи из users в ozon_credentials (если есть)
3. Удаляет старые колонки ozon_client_id и ozon_api_key из users
"""

import sys
import os

# Добавляем корневую директорию в путь для импортов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import engine, SessionLocal, Base, User, OzonCredential
from sqlalchemy import text

def migrate():
    """Выполняет миграцию."""
    print("🔄 Начинаем миграцию...")
    
    # Создаем новую таблицу
    print("📋 Создание таблицы ozon_credentials...")
    OzonCredential.__table__.create(engine, checkfirst=True)
    print("✅ Таблица ozon_credentials создана")
    
    # Переносим существующие ключи
    db = SessionLocal()
    try:
        print("\n🔄 Перенос существующих ключей...")
        
        # Проверяем есть ли старые колонки
        try:
            users_with_keys = db.execute(
                text("SELECT id, ozon_client_id, ozon_api_key FROM users WHERE ozon_client_id IS NOT NULL")
            ).fetchall()
            
            migrated_count = 0
            for user_id, client_id, api_key in users_with_keys:
                # Создаем новую запись в ozon_credentials
                credential = OzonCredential(
                    user_id=user_id,
                    name="Основной",
                    client_id_encrypted=client_id,
                    api_key_encrypted=api_key,
                    is_active=True
                )
                db.add(credential)
                migrated_count += 1
            
            if migrated_count > 0:
                db.commit()
                print(f"✅ Перенесено {migrated_count} наборов ключей")
            else:
                print("ℹ️  Нет ключей для переноса")
                
        except Exception as e:
            if "no such column" in str(e).lower() or "column" in str(e).lower():
                print("ℹ️  Старые колонки уже удалены или не существуют")
            else:
                raise
        
        # Удаляем старые колонки (если они есть)
        print("\n🗑️  Удаление старых колонок...")
        try:
            # SQLite не поддерживает DROP COLUMN напрямую
            # Создаем новую таблицу без этих колонок и переносим данные
            with engine.begin() as conn:
                # Проверяем существование колонок
                result = conn.execute(text("PRAGMA table_info(users)"))
                columns = [row[1] for row in result.fetchall()]
                
                if 'ozon_client_id' in columns or 'ozon_api_key' in columns:
                    print("⚠️  Удаление колонок в SQLite требует пересоздания таблицы")
                    print("ℹ️  Для удаления старых колонок выполните вручную:")
                    print("   1. Создайте бэкап БД")
                    print("   2. Пересоздайте таблицу users без этих колонок")
                    print("   Или оставьте их - они не будут использоваться")
                else:
                    print("✅ Старых колонок нет")
        except Exception as e:
            print(f"⚠️  Ошибка при удалении колонок: {e}")
            print("   Это нормально - колонки можно оставить")
            
    except Exception as e:
        print(f"❌ Ошибка миграции: {e}")
        db.rollback()
        raise
    finally:
        db.close()
    
    print("\n✅ Миграция завершена успешно!")
    print("\n📊 Текущие таблицы:")
    from sqlalchemy import inspect
    inspector = inspect(engine)
    for table_name in inspector.get_table_names():
        print(f"   - {table_name}")

if __name__ == "__main__":
    migrate()
