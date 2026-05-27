# 🚀 Инструкция по развертыванию Backend

В этом руководстве описаны шаги по настройке серверной части OzonAPIHub, базы данных и систем безопасности.

---

## 📋 Требования
- Python 3.11+
- PostgreSQL 14+
- Настроенный доступ к Ozon Seller API

---

## 1. Установка окружения

```bash
# Клонирование
git clone https://github.com/your-repo/OzonAPIHub.git
cd OzonAPIHub

# Виртуальное окружение
python -m venv venv
source venv/bin/activate  # venv\Scripts\activate на Windows

# Зависимости
pip install -r requirements.txt
```

---

## 2. Настройка PostgreSQL

Проект поддерживает **мультитенантность**. Каждый пользователь изолирован на уровне `user_id`.

```sql
-- Создание БД и пользователя
CREATE DATABASE ozondb;
CREATE USER ozonuser WITH PASSWORD 'ozonpass';
GRANT ALL PRIVILEGES ON DATABASE ozondb TO ozonuser;
\c ozondb
GRANT ALL ON SCHEMA public TO ozonuser;
```

---

## 3. Конфигурация (.env)

Создайте файл `.env` в корне проекта на основе `.env.example`. 

### Генерация ключей безопасности:
```python
# Ключ для шифрования API-ключей пользователей (Fernet)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Секрет для JWT токенов
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Пример .env:
```env
DATABASE_URL=postgresql://ozonuser:ozonpass@localhost:5432/ozondb
ENCRYPTION_KEY=ваш_fernet_key
JWT_SECRET_KEY=ваш_jwt_secret
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=10080

SYNC_INTERVAL_SECONDS=300
INITIAL_WINDOW_DAYS=365
```

---

## 4. Инициализация базы данных

Используйте встроенный скрипт для первичного создания таблиц:
```bash
python scripts/init_postgres.py
```
*Примечание: Для дальнейших изменений схемы рекомендуется использовать Alembic (см. ROADMAP.md).*

---

## 5. Запуск сервера

Для разработки:
```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8080 --reload
```

Для production (Docker):
```bash
docker-compose up -d --build
```

---

## 🔍 Проверка и тестирование

1. **Health Check**: `GET http://localhost:8080/ping` -> `{"message": "pong"}`
2. **Swagger Docs**: `http://localhost:8080/docs`
3. **Регистрация первого пользователя**:
   Используйте Postman или curl для отправки `POST /auth/register`. После этого вы сможете войти и получить JWT токен для работы с остальными эндпоинтами.
