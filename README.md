# 📊 OzonAPIHub

**Полнофункциональное SaaS-решение для мониторинга и аналитики продаж на маркетплейсе Ozon**

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Flutter](https://img.shields.io/badge/Flutter-02569B?style=flat&logo=flutter)](https://flutter.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=flat&logo=postgresql)](https://www.postgresql.org/)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python)](https://www.python.org/)

---

## 🎯 О проекте

**OzonAPIHub** — это двухкомпонентная система для автоматизации учёта и аналитики продаж на Ozon:

- 🐍 **Backend** (Python/FastAPI) — синхронизация FBO-заказов, нормализация данных, REST API
- 📱 **Frontend** (Flutter) — кроссплатформенное приложение (Web, Android, iOS, Desktop)

### Ключевые возможности

✅ **Мультитенантность** — полная изоляция данных между пользователями  
✅ **Шифрование API ключей** — безопасное хранение credentials через Fernet  
✅ **Асинхронная синхронизация** — httpx с retry механизмом для Ozon API  
✅ **Фоновая синхронизация** — автоматическое обновление каждые 5 минут  
✅ **Нормализованная БД** — PostgreSQL с оптимизированными запросами  
✅ **Аналитика продаж** — по дате, периоду, статусам, SKU  
✅ **Управление расходами** — себестоимость, реклама, логистика  
✅ **JWT аутентификация** — безопасный доступ к API  
✅ **Кроссплатформенный клиент** — единая кодовая база для всех платформ

---

## 📁 Структура проекта

```
OzonAPIHub/
├── main.py                      # FastAPI приложение
├── requirements.txt             # Python зависимости
├── .env                         # Конфигурация (не в git!)
│
├── db/
│   └── database.py              # SQLAlchemy ORM модели
│
├── routes/                      # API эндпоинты
│   ├── analytics.py             # Аналитика продаж
│   ├── auth_endpoints.py        # Аутентификация и credentials
│   ├── orders.py                # Получение заказов
│   ├── costs.py                 # Управление расходами
│   ├── enrichment_endpoints.py  # Обогащение данных
│   └── sync_endpoints.py        # Синхронизация с Ozon
│
├── services/                    # Бизнес-логика
│   ├── ozon.py                  # Асинхронные вызовы Ozon API
│   ├── enrichment.py            # Обогащение финансовыми данными
│   └── sync.py                  # Фоновая синхронизация
│
├── utils/                       # Вспомогательные утилиты
│   ├── auth.py                  # JWT токены, хеширование
│   ├── encryption.py            # Шифрование credentials
│   ├── credentials.py           # Управление доступом
│   └── common.py                # Валидация
│
├── scripts/                     # CLI утилиты
│   ├── init_postgres.py         # Инициализация БД
│   ├── add_credential.py        # Добавление API ключей
│   └── ...
│
└── ozon_sales_dashboard/        # Flutter приложение
    ├── lib/
    │   ├── main.dart
    │   ├── providers/           # State management
    │   ├── services/            # API клиенты
    │   ├── screens/             # UI экраны
    │   └── widgets/             # Переиспользуемые компоненты
    └── pubspec.yaml
```

---

## 🏗️ Архитектура

### Backend (FastAPI)

#### База данных PostgreSQL

**Основные таблицы:**

| Таблица | Назначение |
|---------|------------|
| `users` | Пользователи системы (email, пароль, подписка) |
| `ozon_credentials` | Зашифрованные API ключи (поддержка нескольких маркетплейсов) |
| `order_headers` | Агрегированная сводка по заказам |
| `order_postings` | Нормализованные постинги с аналитикой |
| `order_products` | Товары в постингах (SKU, цены, комиссии) |
| `costs` | Расходы (себестоимость, логистика, реклама) |
| `sync_status` | Статус синхронизации данных |

#### Поток данных

```
1. Ozon API (/v2/posting/fbo/list) 
   ↓
2. Сохранение в Order (legacy) или OrderPosting
   ↓
3. Обогащение через /v2/posting/fbo/get
   ↓
4. Извлечение financial_data → OrderProduct
   ↓
5. Пересчёт OrderHeader (total_payout, total_commission)
   ↓
6. Доступ через REST API
```

### Frontend (Flutter)

**Архитектура авторизации:**

```
Запуск → AuthProvider проверяет токен
   ↓
CheckAuthScreen (splash)
   ↓
├─ Токен есть → DashboardScreen
└─ Токен нет → LoginScreen
```

**State Management:** Provider (ChangeNotifier)  
**HTTP клиент:** Dio с interceptors (auto-token injection, 401 handling)  
**Хранение токена:** SharedPreferences (работает на всех платформах)

---

## 🚀 Быстрый старт

### Требования

- Python 3.11+
- PostgreSQL 14+
- Flutter 3.9+ (для фронтенда)
- Git

### 1. Клонирование репозитория

```bash
git clone https://github.com/your-repo/OzonAPIHub.git
cd OzonAPIHub
```

### 2. Настройка Backend

#### Создание виртуального окружения

```powershell
# Windows
python -m venv venv
& venv\Scripts\Activate.ps1

# Linux/macOS
python3 -m venv venv
source venv/bin/activate
```

#### Установка зависимостей

```bash
pip install -r requirements.txt
```

#### Настройка PostgreSQL

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

#### Конфигурация .env

Создайте файл `.env` в корне проекта:

```bash
# PostgreSQL
DATABASE_URL=postgresql://ozonuser:ozonpass@localhost:5432/ozondb

# Шифрование (ОБЯЗАТЕЛЬНО! Сгенерируйте новый ключ)
# python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=your-generated-fernet-key-here

# JWT
JWT_SECRET_KEY=your-secret-key-min-32-chars
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=10080  # 7 дней

# Синхронизация
SYNC_INTERVAL_SECONDS=300
RECENT_WINDOW_HOURS=48
MONTH_RECONCILE_INTERVAL_SECONDS=3600
MONTH_RECONCILE_MONTHS=3

# Обогащение
ENRICH_ON_FETCH=true
ENRICH_ON_FETCH_LIMIT=200
ENRICH_RECENT_POSTINGS=true
ENRICH_RECENT_LIMIT=100
ENRICH_CONCURRENCY=4
ENRICH_ON_STATUS_CHANGE=true

# Ozon API
OZON_MAX_RETRIES=3
OZON_RETRY_BACKOFF_SECONDS=1.5
DEFAULT_TIMEOUT=60

# Логирование
LOG_LEVEL=INFO
LOG_OZON_REQUESTS=false

# Первичная синхронизация
ENABLE_INITIAL_SYNC=true
INITIAL_WINDOW_DAYS=365
HISTORY_WINDOW_DAYS=30
```

#### Генерация ключей

```bash
# Encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# JWT secret (любая случайная строка 32+ символов)
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

#### Инициализация БД

```bash
python scripts/init_postgres.py
```

#### Запуск сервера

```bash
# Через uvicorn
python -m uvicorn main:app --host 127.0.0.1 --port 8080 --reload

# Или через скрипт
python run_server.py
```

#### Быстрая заметка по Docker deployment

Если вы запускаете сервис в Docker на сервере, теперь в проекте добавлены:
- `docker-entrypoint.sh` — инициализация PostgreSQL схемы при старте backend
- `INIT_DB_ON_STARTUP=true` в `docker-compose.yml`
- `Dockerfile` с entrypoint для автозапуска инициализации

Команды для сервера:

```bash
cd /root/OzonAPIHub
# Если на сервере установлено новое CLI Docker
docker compose build backend
docker compose up -d
```

Если `docker compose` отсутствует, установите его или используйте

```bash
apt update
apt install -y docker-compose
```

Или очистите локальные изменения перед git pull, если получите конфликт:

```bash
git checkout -- docker-compose.yml
git pull origin main
```

Swagger документация: **http://127.0.0.1:8080/docs**

### 3. Настройка Frontend

```bash
cd ozon_sales_dashboard

# Установка зависимостей
flutter pub get

# Запуск (Web)
flutter run -d chrome

# Запуск (Android)
flutter run

# Сборка для Web
flutter build web
```

---

## 🔒 Безопасность

### Аутентификация

- **JWT токены** с Bearer схемой
- **Bcrypt** хеширование паролей (max 72 байта)
- Валидация email через `email-validator`
- Автоматическая инвалидация токена при 401 ошибке

### Шифрование credentials

```python
# Используется Fernet (симметричное шифрование)
from cryptography.fernet import Fernet

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
cipher_suite = Fernet(ENCRYPTION_KEY.encode())

# Шифрование
encrypted = cipher_suite.encrypt(plaintext.encode())

# Расшифровка
decrypted = cipher_suite.decrypt(ciphertext.encode())
```

### Изоляция данных

- Все запросы фильтруются по `user_id` из JWT токена
- Невозможно получить чужие данные
- CASCADE удаление при удалении пользователя
- Уникальные индексы в рамках одного пользователя

---

## 📊 API эндпоинты

### Аутентификация

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| POST | `/auth/register` | Регистрация нового пользователя |
| POST | `/auth/login` | Вход (получение JWT токена) |
| GET | `/auth/me` | Информация о текущем пользователе |
| PUT | `/auth/me` | Обновление профиля |
| GET | `/auth/me/ozon-credentials` | Список API ключей |
| POST | `/auth/me/ozon-credentials` | Добавить новый набор ключей |
| PUT | `/auth/me/ozon-credentials/{id}/activate` | Активировать набор |
| DELETE | `/auth/me/ozon-credentials/{id}` | Удалить набор |

### Заказы

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| GET | `/orders` | Список заказов (фильтры, пагинация) |
| GET | `/orders/{posting_number}` | Детали постинга |
| GET | `/order/{order_number}` | Сводка по заказу |
| GET | `/order/{order_number}/postings` | Постинги заказа |

### Синхронизация

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| POST | `/sync/initial` | Первичная загрузка (с маркером) |
| POST | `/sync/initial/force` | Принудительная загрузка |
| POST | `/sync/history` | Импорт истории за период |

### Обогащение

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| POST | `/orders/fbo/get` | Обогатить один постинг |
| POST | `/orders/fbo/get_for_order` | Обогатить все постинги заказа |
| POST | `/orders/fbo/enrich_recent` | Обогатить недавние постинги |
| POST | `/orders/fbo/enrich_changed_recent` | Обогатить с изменённым статусом |

### Аналитика

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| GET | `/analytics/sales_today` | Продажи за сегодня (delivered) |
| GET | `/analytics/orders_today` | Количество заказов за сегодня |
| GET | `/analytics/sales_today_raw` | Продажи по всем статусам |
| GET | `/analytics/sales_by_date` | Продажи за конкретную дату |
| GET | `/analytics/sales_range` | Продажи за период |

### Расходы

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| POST | `/costs` | Добавить расход |
| GET | `/costs` | Список расходов (фильтры) |

### Утилиты

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| GET | `/ping` | Health check |
| GET | `/stats` | Статистика БД |

---

## 🔄 Workflow синхронизации

### 1. Первичная загрузка

```bash
# Через API
curl -X POST http://127.0.0.1:8080/sync/initial \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

Загружает заказы за последние `INITIAL_WINDOW_DAYS` дней (по умолчанию 365).

### 2. Фоновая синхронизация

Автоматически запускается при старте сервера:
- Каждые `SYNC_INTERVAL_SECONDS` (300 сек = 5 мин)
- Выгружает новые заказы с момента последней синхронизации
- Сверяет недавнее окно (`RECENT_WINDOW_HOURS`)
- Автоматически обогащает новые постинги

### 3. Обогащение данных

```python
# Автоматическое обогащение при выгрузке
ENRICH_ON_FETCH=true

# Фоновое обогащение недавних постингов
ENRICH_RECENT_POSTINGS=true

# Обогащение при смене статуса
ENRICH_ON_STATUS_CHANGE=true
```

### 4. Расчёт прибыли

```python
profit = total_payout - total_commission - costs
```

- `total_payout` — выплата от Ozon
- `total_commission` — комиссия Ozon
- `costs` — ваши расходы (себестоимость, реклама, логистика)

---

## 🛠️ CLI утилиты

### Инициализация БД

```bash
python scripts/init_postgres.py
```

### Добавление API ключей

```bash
python scripts/add_credential.py
```

### Просмотр содержимого БД

```bash
python scripts/inspect_db.py
```

### Обогащение за период

```bash
python scripts/enrich_date_range.py --since 2025-01-01 --to 2025-01-31
```

### Тестирование Ozon API

```bash
python scripts/ozon_probe.py
```

---

## 📱 Flutter интеграция

### Пример API клиента

```dart
import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';

class OzonApiClient {
  final Dio dio;
  
  OzonApiClient({String? baseUrl})
    : dio = Dio(BaseOptions(
        baseUrl: baseUrl ?? 'http://localhost:8080',
        connectTimeout: const Duration(seconds: 30),
      )) {
    // Автоматическое добавление токена
    dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) async {
        final prefs = await SharedPreferences.getInstance();
        final token = prefs.getString('jwt_token');
        
        if (token != null) {
          options.headers['Authorization'] = 'Bearer $token';
        }
        
        return handler.next(options);
      },
      onError: (error, handler) async {
        // Обработка 401 - автоматический выход
        if (error.response?.statusCode == 401) {
          final prefs = await SharedPreferences.getInstance();
          await prefs.remove('jwt_token');
          // Перенаправить на экран входа
        }
        return handler.next(error);
      },
    ));
  }
  
  Future<Map<String, dynamic>> getSalesRange({
    required String since,
    required String to,
  }) async {
    final resp = await dio.get('/analytics/sales_range', 
      queryParameters: {'since': since, 'to': to});
    return resp.data;
  }
}
```

### Пример использования с Provider

```dart
import 'package:provider/provider.dart';

// В main.dart
MultiProvider(
  providers: [
    ChangeNotifierProvider(create: (_) => AuthProvider()),
  ],
  child: MaterialApp(...),
)

// В виджете
final authProvider = context.watch<AuthProvider>();
if (authProvider.isAuthenticated) {
  // Показать главный экран
} else {
  // Показать экран входа
}
```

---

## 🔧 Конфигурация

### Переменные окружения (.env)

<details>
<summary>Полная конфигурация</summary>

```bash
# ============================================================================
# DATABASE
# ============================================================================
DATABASE_URL=postgresql://ozonuser:ozonpass@localhost:5432/ozondb

# ============================================================================
# SECURITY
# ============================================================================
# Fernet encryption key (32 bytes base64)
ENCRYPTION_KEY=your-fernet-key-here

# JWT settings
JWT_SECRET_KEY=your-jwt-secret-min-32-chars
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=10080  # 7 дней

# ============================================================================
# SYNCHRONIZATION
# ============================================================================
SYNC_INTERVAL_SECONDS=300              # Интервал фоновой синхронизации (5 мин)
RECENT_WINDOW_HOURS=48                 # Окно "недавних" постингов
MONTH_RECONCILE_INTERVAL_SECONDS=3600  # Месячная сверка (1 час)
MONTH_RECONCILE_MONTHS=3               # Количество месяцев для сверки

# ============================================================================
# ENRICHMENT
# ============================================================================
ENRICH_ON_FETCH=true                   # Обогащать при выгрузке
ENRICH_ON_FETCH_LIMIT=200
ENRICH_RECENT_POSTINGS=true            # Фоновое обогащение недавних
ENRICH_RECENT_LIMIT=100
ENRICH_CONCURRENCY=4                   # Параллельных задач обогащения
ENRICH_ON_STATUS_CHANGE=true           # Обогащать при смене статуса
ENRICH_STATUS_CHANGE_LIMIT=100

# ============================================================================
# OZON API
# ============================================================================
OZON_MAX_RETRIES=3                     # Количество повторных попыток
OZON_RETRY_BACKOFF_SECONDS=1.5         # Задержка между попытками
DEFAULT_TIMEOUT=60                     # Timeout запросов (секунды)

# ============================================================================
# LOGGING
# ============================================================================
LOG_LEVEL=INFO                         # DEBUG | INFO | WARNING | ERROR
LOG_OZON_REQUESTS=false                # Логировать тела запросов к Ozon

# ============================================================================
# INITIAL SYNC
# ============================================================================
ENABLE_INITIAL_SYNC=true
INITIAL_WINDOW_DAYS=365                # Загружать заказы за год
HISTORY_WINDOW_DAYS=30                 # Размер окна при импорте истории
```

</details>

---

## 📚 Дополнительная документация

- **[ROADMAP.md](ROADMAP.md)** — 🗺️ **План развития проекта (Sprint planning)**
- [MIGRATION_TO_POSTGRES.md](MIGRATION_TO_POSTGRES.md) — Миграция с SQLite на PostgreSQL
- [FLUTTER_SAAS_ARCHITECTURE.md](FLUTTER_SAAS_ARCHITECTURE.md) — Архитектура Flutter клиента
- [CHANGELOG.md](CHANGELOG.md) — История изменений
- [.github/copilot-instructions.md](.github/copilot-instructions.md) — AI coding guidelines

---

## 🐛 Известные проблемы и план улучшений

| Проблема | Статус | Приоритет | План |
|----------|--------|-----------|------|
| Нет rate limiting | ⏳ Planned | 🔴 P0 | См. [ROADMAP.md](ROADMAP.md#1️⃣-rate-limiting-приоритет-p0) |
| Нет кеширования | ⏳ Planned | 🟡 P1 | См. [ROADMAP.md](ROADMAP.md#2️⃣-кеширование-приоритет-p1) |
| CORS только localhost | ⏳ Planned | 🟡 P1 | См. [ROADMAP.md](ROADMAP.md#3️⃣-cors-для-production-приоритет-p1) |
| Нет Alembic миграций | ⏳ Planned | 🟢 P2 | См. [ROADMAP.md](ROADMAP.md#4️⃣-alembic-миграции-приоритет-p2) |
| Ozon API timeout 60s | ⏳ Planned | 🟢 P3 | См. [ROADMAP.md](ROADMAP.md#5️⃣-адаптивный-timeout-приоритет-p3) |

**📋 Подробный план реализации:** [ROADMAP.md](ROADMAP.md)

### Временные обходные пути

**Rate limiting отсутствует:**
```bash
# Уменьшите ENRICH_CONCURRENCY в .env
ENRICH_CONCURRENCY=2
```

**Медленные запросы без кеша:**
```bash
# Используйте более агрессивную синхронизацию
SYNC_INTERVAL_SECONDS=600  # 10 минут вместо 5
```

**CORS для production:**
```python
# Временно можно добавить домен вручную в main.py
allow_origins=["https://yourdomain.com"]
```

---

## 🤝 Вклад в проект

1. Fork репозиторий
2. Создайте ветку для фичи (`git checkout -b feature/amazing-feature`)
3. Commit изменения (`git commit -m 'Add amazing feature'`)
4. Push в ветку (`git push origin feature/amazing-feature`)
5. Откройте Pull Request

---

## 📝 Лицензия

Этот проект использует MIT License - см. файл [LICENSE](LICENSE) для деталей.

---

## 📧 Контакты

- **Email:** your-email@example.com
- **Telegram:** @your_telegram
- **Issues:** [GitHub Issues](https://github.com/your-repo/OzonAPIHub/issues)

---

## 🙏 Благодарности

- [FastAPI](https://fastapi.tiangolo.com/) — современный веб-фреймворк
- [Flutter](https://flutter.dev/) — кроссплатформенный UI toolkit
- [httpx](https://www.python-httpx.org/) — асинхронный HTTP клиент
- [SQLAlchemy](https://www.sqlalchemy.org/) — ORM для Python
- [Ozon Seller API](https://docs.ozon.ru/api/seller/) — документация API

---

**⭐ Если проект полезен, поставьте звезду на GitHub!**

## План Работ (Roadmap)
1. Разделить `main.py` на модули
   - routes/orders.py — эндпоинты чтения/загрузки заказов
   - services/ozon.py — обращения к Ozon API
   - services/enrichment.py — обогащение и перерасчёты
   - services/sync.py — фоновые циклы и месячная сверка
   - utils/dates.py, utils/filters.py — работа с датами и валидаторами
2. Расширить аналитику
   - `GET /analytics/sales_by_date?date=YYYY-MM-DD`
   - `GET /analytics/sales_range?since=...&to=...`
   - Добавить итоговую прибыль с учётом `Cost`
3. Улучшить устойчивость
   - Ретраи/бэк-офф для Ozon 429/5xx, настройка ENRICH_CONCURRENCY
   - Индексы и, по желанию, переход к PostgreSQL
4. Подготовка для фронта (Flutter)
   - Мини-спека API: поля, примеры
   - Базовый фильтр/поиск, пагинация

## Настройки `.env`
Рекомендуемые значения:
```
SYNC_INTERVAL_SECONDS=300
RECENT_WINDOW_HOURS=48
MONTH_RECONCILE_INTERVAL_SECONDS=3600
MONTH_RECONCILE_MONTHS=3
LOG_LEVEL=WARNING
LOG_OZON_REQUESTS=false
ENRICH_ON_FETCH=true
ENRICH_ON_FETCH_LIMIT=200
ENRICH_RECENT_POSTINGS=true
ENRICH_RECENT_LIMIT=100
ENRICH_CONCURRENCY=4
ENRICH_ON_STATUS_CHANGE=true
ENRICH_STATUS_CHANGE_LIMIT=100
```

## Быстрый старт
```powershell
& venv\Scripts\Activate.ps1
python -m uvicorn main:app --host 127.0.0.1 --port 8080
Invoke-RestMethod -Uri "http://127.0.0.1:8080/stats" -Method Get
Invoke-RestMethod -Uri "http://127.0.0.1:8080/analytics/orders_today" -Method Get
```

## API для Flutter (контракты и примеры)

- `GET /orders?since=YYYY-MM-DDTHH:MM:SSZ&to=YYYY-MM-DDTHH:MM:SSZ&limit=50&offset=0`
   - Ответ:
      ```json
      {
         "total": 123,
         "limit": 50,
         "offset": 0,
         "items": [
            {
               "id": 1,
               "order_id": 987654,
               "posting_number": "76730974-0856-1",
               "status": "delivering",
               "created_at": "2025-12-02T10:00:00Z",
               "updated_at": "2025-12-02T10:00:00Z",
               "data": {"...": "оригинальный ответ Ozon list"}
            }
         ]
      }
      ```

- `GET /order/{order_number}`
   - Ответ:
      ```json
      {
         "order_number": "76730974-0856",
         "header": {
            "first_created_at": "2025-12-01T09:00:00Z",
            "last_delivery_at": "2025-12-02T14:30:00Z",
            "total_payout": 152300,
            "total_commission": 18300,
            "profit": 134000
         },
         "postings": [
            {
               "posting_number": "76730974-0856-1",
               "status": "delivered",
               "created_at": "2025-12-01T09:00:00Z",
               "in_process_at": null,
               "fact_delivery_date": "2025-12-02T14:30:00Z",
               "substatus": null,
               "products": [
                  {
                     "sku": 2834203781,
                     "offer_id": "10001",
                     "name": "Пакеты фасовочные 15x20 см",
                     "quantity": 3,
                     "price": 120,
                     "currency_code": "RUB",
                     "commission_amount": 900,
                     "commission_percent": 6,
                     "payout": 330,
                     "total_discount_value": 0,
                     "total_discount_percent": 0
                  }
               ]
            }
         ]
      }
      ```

- `GET /order/{order_number}/postings`
   - Ответ:
      ```json
      {
         "order_number": "76730974-0856",
         "count": 2,
         "items": [
            {
               "posting_number": "76730974-0856-1",
               "status": "delivering",
               "created_at": "2025-12-01T09:00:00Z",
               "products_count": 1,
               "total_payout": 0,
               "total_commission": 0
            }
         ]
      }
      ```

- `GET /analytics/sales_today?since=YYYY-MM-DDTHH:MM:SSZ&to=YYYY-MM-DDTHH:MM:SSZ&tz_offset_hours=3`
   - Ответ:
      ```json
      {
         "range": {"since": "2025-12-01T00:00:00Z", "to": "2025-12-03T23:59:59Z"},
         "total_items": 10,
         "total_orders": 7,
         "items": [
            {
               "offer_id": "10001",
               "sku": 2834203781,
               "name": "Пакеты фасовочные 15x20 см",
               "quantity_sold": 5,
               "orders_count": 4,
               "total_payout": 550
            }
         ]
      }
      ```

- `GET /analytics/sales_today_raw?since=YYYY-MM-DDTHH:MM:SSZ&to=YYYY-MM-DDTHH:MM:SSZ&include_statuses=...&tz_offset_hours=3`
   - Ответ:
      ```json
      {
         "range": {"since": "2025-12-01T00:00:00Z", "to": "2025-12-03T23:59:59Z"},
         "items": [
            {
               "offer_id": "10001",
               "sku": 2834203781,
               "name": "Пакеты фасовочные 15x20 см",
               "quantity": 51,
               "orders_count": 51,
               "amount_raw": 11076
            }
         ],
         "total_items": 56,
         "total_orders": 56,
         "total_amount_raw": 12326,
         "statuses": ["awaiting_packaging", "awaiting_deliver", "delivering"]
      }
      ```

- `GET /analytics/orders_today`
   - Ответ:
      ```json
      {
         "date": "2025-12-02",
         "total": 23,
         "by_status": [
            {"status": "delivering", "count": 18},
            {"status": "delivered", "count": 5}
         ]
      }
      ```

### Замечания для Flutter
- Все ответы — JSON UTF-8; используйте `http`/`dio` с явным `utf8.decode` при необходимости.
- Даты — ISO с суффиксом `Z` (UTC). Для фильтров формируйте строки вида `YYYY-MM-DDTHH:MM:SSZ`.
- Список обычно пагинируется (`limit`, `offset`).
- Профит в заказе считается как `total_payout - total_commission` из нормализованных данных.
 - Для совпадения с витриной Ozon по "сегодня" используйте `tz_offset_hours=3` (МСК). Без параметра расчёт ведётся по UTC.

## Flutter: быстрый старт

- Зависимости: `dio`, `flutter_riverpod` или `provider` (по желанию), `intl`.
- Базовый клиент на Dio:
   ```dart
   import 'dart:convert';
   import 'package:dio/dio.dart';

   final dio = Dio(BaseOptions(baseUrl: 'http://127.0.0.1:8080'));

   Future<Map<String, dynamic>> salesTodayRaw({required String since, required String to}) async {
      final resp = await dio.get('/analytics/sales_today_raw', queryParameters: {'since': since, 'to': to});
      return resp.data is String ? json.decode(resp.data) : resp.data as Map<String, dynamic>;
   }
   ```
- Пример использования:
   ```dart
   final data = await salesTodayRaw(since: '2025-12-01T00:00:00Z', to: '2025-12-03T23:59:59Z');
   final items = data['items'] as List<dynamic>;
   // render items[i]['name'], items[i]['quantity'], items[i]['orders_count']
   ```

- Эндпоинты для витрины:
   - Сырые продажи: `/analytics/sales_today_raw?since=...&to=...`
   - Доставленные продажи за период: `/analytics/sales_range?since=...&to=...`
   - Заказы сегодня: `/analytics/orders_today`
   - Список заказов: `/orders?limit=50&offset=0`

## Заметки по PowerShell (кириллица)
Для корректного вывода названий на русском:
```powershell
$enc = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = $enc; $OutputEncoding = $enc
```
