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

---

## 4. Инициализация и Запуск

### Первичная настройка таблиц
```bash
python scripts/init_postgres.py
```

### Запуск в режиме разработки
```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8080 --reload
```

### Запуск через Docker (Production)
```bash
docker compose up -d --build
```

---

## 5. 🪵 Работа с логами

Система использует продвинутое логирование с разделением прав:

- **Общий лог**: `logs/app.log` — системные события, ошибки БД и запуск сервисов.
- **Логи пользователей**: `logs/users/user_{id}.log` — персональная история синхронизации, ошибки Ozon API и действия каждого пользователя.

### Просмотр логов на сервере:
```bash
# Общие логи
tail -f logs/app.log

# Логи конкретного пользователя (например, ID 1)
tail -f logs/users/user_1.log

# Логи Docker контейнера
docker compose logs -f backend
```
*Все логи имеют встроенную ротацию: файлы не превышают 5МБ и автоматически архивируются.*

---

## 🔍 Проверка

1. **Health Check**: `GET http://localhost:8080/ping` -> `{"message": "pong"}`
2. **Swagger Docs**: `http://localhost:8080/docs`
3. **Регистрация**: Используйте эндпоинт `POST /auth/register` для создания первого аккаунта.
