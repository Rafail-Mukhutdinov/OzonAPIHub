# PostgreSQL Migration Guide: SQLite → PostgreSQL (SaaS)

## Обзор изменений

Проект переведен с SQLite на PostgreSQL с поддержкой **мультитенантности (SaaS)**:

- ✅ Новая модель `User` для управления пользователями
- ✅ Шифрование Ozon credentials (Client ID, API Key)
- ✅ Добавлено поле `user_id` во все таблицы с данными
- ✅ CASCADE удаление при удалении пользователя
- ✅ Уникальные индексы в рамках одного пользователя

---

## Шаг 1: Установка PostgreSQL

### Windows
```powershell
# Скачайте с https://www.postgresql.org/download/windows/
# Или через Chocolatey:
choco install postgresql14

# Запуск сервиса
Start-Service postgresql-x64-14
```

### Linux/macOS
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install postgresql postgresql-contrib

# macOS (Homebrew)
brew install postgresql@14
brew services start postgresql@14
```

---

## Шаг 2: Создание базы данных и пользователя

```sql
-- Подключитесь к PostgreSQL
psql -U postgres

-- Создайте базу данных
CREATE DATABASE ozondb;

-- Создайте пользователя
CREATE USER ozonuser WITH PASSWORD 'ozonpass';

-- Выдайте права
GRANT ALL PRIVILEGES ON DATABASE ozondb TO ozonuser;

-- Подключитесь к новой БД
\c ozondb

-- Выдайте права на схему
GRANT ALL ON SCHEMA public TO ozonuser;
```

---

## Шаг 3: Настройка .env

Создайте или обновите файл `.env`:

```bash
# PostgreSQL Connection
DATABASE_URL=postgresql://ozonuser:ozonpass@localhost:5432/ozondb

# Encryption Key (ОБЯЗАТЕЛЬНО! Сгенерируйте новый ключ)
# python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=your-generated-fernet-key-here

# Ozon API (теперь хранятся ПО ПОЛЬЗОВАТЕЛЮ в БД, это для legacy/admin)
OZON_CLIENT_ID=your-legacy-client-id
OZON_API_KEY=your-legacy-api-key

# App Settings
LOG_LEVEL=INFO
SYNC_INTERVAL_SECONDS=300
RECENT_WINDOW_HOURS=48
```

---

## Шаг 4: Установка зависимостей

```powershell
& venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Новые зависимости:
- `psycopg2-binary` — PostgreSQL драйвер
- `cryptography` — шифрование Ozon credentials
- `passlib[bcrypt]` — хеширование паролей
- `python-jose` — JWT токены для аутентификации
- `alembic` — миграции БД (опционально)

---

## Шаг 5: Создание таблиц

### Вариант 1: Python скрипт (интерактивный)
```powershell
python scripts/init_postgres.py
# Выберите пункт "2. Создать все таблицы"
```

### Вариант 2: SQL скрипт
```powershell
psql -U ozonuser -d ozondb -f scripts/create_tables.sql
```

### Вариант 3: Alembic (рекомендуется для продакшена)
```powershell
# Инициализация Alembic (однократно)
alembic init alembic

# Создание первой миграции
alembic revision --autogenerate -m "Initial SaaS schema"

# Применение миграции
alembic upgrade head
```

---

## Шаг 6: Миграция данных из SQLite (опционально)

Если у вас есть данные в `orders.db`, создайте скрипт миграции:

```python
# scripts/migrate_sqlite_to_postgres.py
import sqlite3
from sqlalchemy.orm import Session
from db.database import SessionLocal, User, Order, OrderPosting
from utils.encryption import encrypt_credential

def migrate_data():
    # 1. Создайте пользователя-владельца старых данных
    pg_db: Session = SessionLocal()
    
    demo_user = User(
        email="migrated@example.com",
        hashed_password="change_me",
        ozon_client_id=encrypt_credential("YOUR_OLD_CLIENT_ID"),
        ozon_api_key=encrypt_credential("YOUR_OLD_API_KEY"),
        is_demo=False
    )
    pg_db.add(demo_user)
    pg_db.commit()
    pg_db.refresh(demo_user)
    
    # 2. Подключитесь к SQLite
    sqlite_conn = sqlite3.connect("orders.db")
    sqlite_conn.row_factory = sqlite3.Row
    cursor = sqlite_conn.cursor()
    
    # 3. Мигрируйте заказы
    cursor.execute("SELECT * FROM orders")
    for row in cursor.fetchall():
        order = Order(
            user_id=demo_user.id,
            order_id=row['order_id'],
            posting_number=row['posting_number'],
            status=row['status'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
            data=row['data']
        )
        pg_db.add(order)
    
    pg_db.commit()
    print("✓ Данные успешно мигрированы!")

if __name__ == "__main__":
    migrate_data()
```

---

## Шаг 7: Обновление кода приложения

### Изменения в `services/ozon.py`

**Было:**
```python
def _headers():
    client_id = os.getenv("OZON_CLIENT_ID")
    api_key = os.getenv("OZON_API_KEY")
    ...
```

**Стало:**
```python
from utils.encryption import get_user_ozon_headers

def _headers(user):
    return get_user_ozon_headers(user)
```

### Изменения в endpoints

**Было:**
```python
@router.get("/orders")
async def list_orders(db: Session = Depends(get_db)):
    q = db.query(Order)
    ...
```

**Стало:**
```python
from fastapi import Depends
from utils.auth import get_current_user  # Создайте этот модуль

@router.get("/orders")
async def list_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Order).filter(Order.user_id == current_user.id)
    ...
```

---

## Шаг 8: Проверка

```powershell
# Запуск сервера
python -m uvicorn main:app --reload

# Проверка подключения
Invoke-RestMethod -Uri "http://127.0.0.1:8080/ping" -Method Get
```

---

## Безопасность

⚠️ **ВАЖНО:**
1. **ENCRYPTION_KEY** должен быть уникальным и НИКОГДА не коммититься в git
2. Используйте сильные пароли для PostgreSQL
3. В продакшене используйте SSL для подключения к БД:
   ```
   DATABASE_URL=postgresql://user:pass@host:5432/db?sslmode=require
   ```
4. Храните Ozon credentials только в зашифрованном виде
5. Используйте JWT токены для аутентификации пользователей

---

## Следующие шаги

1. Создайте модуль `utils/auth.py` для JWT-аутентификации
2. Добавьте endpoints для регистрации/входа пользователей
3. Обновите все существующие endpoints для фильтрации по `user_id`
4. Настройте Alembic для управления миграциями
5. Добавьте тесты для мультитенантности

---

## Откат к SQLite (если нужно)

Просто замените в `.env`:
```bash
# DATABASE_URL=postgresql://ozonuser:ozonpass@localhost:5432/ozondb
DATABASE_URL=sqlite:///orders.db
```

Но учтите, что модели изменились (добавлен `user_id`), поэтому старая SQLite БД не будет совместима без модификаций.
