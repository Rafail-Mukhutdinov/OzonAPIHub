"""
Миграция для добавления поля marketplace в таблицу ozon_credentials.
Гарантирует уникальность по (user_id, marketplace) вместо только (user_id, name).

Команда для запуска:
    docker exec ozon_backend python scripts/migrate_marketplace.py
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, exc
from db.database import SessionLocal, engine, OzonCredential

def migrate():
    """Выполнить миграцию"""
    db = SessionLocal()
    
    try:
        with engine.connect() as conn:
            with conn.begin():
                # Проверяем, есть ли уже колонка marketplace
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'ozon_credentials' 
                    AND column_name = 'marketplace'
                """))
                
                if result.fetchone():
                    print("✅ Колонка 'marketplace' уже существует. Миграция пропущена.")
                    return
                
                print("📝 Добавляем колонку marketplace...")
                conn.execute(text("""
                    ALTER TABLE ozon_credentials 
                    ADD COLUMN marketplace VARCHAR(50) DEFAULT 'ozon' NOT NULL
                """))
                print("✅ Колонка marketplace добавлена")
                
                # Обновляем существующие записи (уже имеют 'ozon' по умолчанию)
                print("📝 Обновляем существующие записи...")
                result = conn.execute(text(
                    "UPDATE ozon_credentials SET marketplace = 'ozon' WHERE marketplace IS NULL"
                ))
                print(f"✅ Обновлено записей: {result.rowcount}")
                
                # Удаляем старое ограничение на уникальность если оно существует
                print("📝 Удаляем старое ограничение уникальности...")
                try:
                    conn.execute(text(
                        "ALTER TABLE ozon_credentials DROP CONSTRAINT uq_user_credential_name"
                    ))
                    print("✅ Старое ограничение удалено")
                except exc.ProgrammingError:
                    print("⚠️  Старое ограничение не найдено (это OK)")
                
                # Добавляем новое ограничение на (user_id, marketplace)
                print("📝 Добавляем новое ограничение на (user_id, marketplace)...")
                try:
                    conn.execute(text("""
                        ALTER TABLE ozon_credentials 
                        ADD CONSTRAINT uq_user_marketplace UNIQUE (user_id, marketplace)
                    """))
                    print("✅ Ограничение (user_id, marketplace) добавлено")
                except exc.IntegrityError as e:
                    if "already exists" in str(e):
                        print("✅ Ограничение (user_id, marketplace) уже существует")
                    else:
                        raise
                
                # Добавляем ограничение на (user_id, name)
                print("📝 Добавляем ограничение на (user_id, name)...")
                try:
                    conn.execute(text("""
                        ALTER TABLE ozon_credentials 
                        ADD CONSTRAINT uq_user_credential_name UNIQUE (user_id, name)
                    """))
                    print("✅ Ограничение (user_id, name) добавлено")
                except exc.IntegrityError as e:
                    if "already exists" in str(e):
                        print("✅ Ограничение (user_id, name) уже существует")
                    else:
                        raise
                
                conn.commit()
                print("\n✅ Миграция завершена успешно!")
        
    except Exception as e:
        print(f"\n❌ Ошибка при миграции: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    migrate()
