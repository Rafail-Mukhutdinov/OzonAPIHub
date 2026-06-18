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
CREATE DATABASE ozon_saas;
CREATE USER ozon_user WITH PASSWORD 'SecurePass2024!';
GRANT ALL PRIVILEGES ON DATABASE ozon_saas TO ozon_user;
\c ozon_saas
GRANT ALL ON SCHEMA public TO ozon_user;
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

---

## 🛠 Особенности обработки данных Ozon (Технические заметки)

Для обеспечения 100% совпадения с отчетами в личном кабинете Ozon Seller реализованы следующие механизмы:

1.  **Логика учета дат**: 
    *   Ozon учитывает продажи по дате принятия заказа в работу (`in_process_at`), а не по дате его создания. 
    *   В аналитических отчетах (`/analytics/daily_stats` и др.) используется приоритет: `in_process_at` -> `created_at`.
    *   Это позволяет корректно учитывать заказы, созданные в конце одних суток, но обработанные в начале других.

2.  **Двухуровневый расчет (Fallback)**:
    *   Данные в отчетах доступны мгновенно после загрузки списка заказов. 
    *   Если детальное "обогащение" (enrichment) еще не завершено, система берет количество и цены напрямую из сырого JSON (`Order.data`).
    *   После завершения обогащения данные заменяются на более точные (с учетом всех комиссий и выплат) из `OrderProduct`.

3.  **Часовые пояса**:
    *   Параметр `tz_offset_hours` (по умолчанию 3 для МСК) позволяет гибко настраивать границы суток в отчетах.

4.  **Устойчивость к пропускам**:
    *   Синхронизатор автоматически ищет заказы, для которых не было выполнено обогащение, и отправляет их в очередь, даже если статус заказа не менялся.
