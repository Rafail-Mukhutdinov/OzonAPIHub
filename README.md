# OzonAPIHub

Коротко: сервис на FastAPI для синхронизации FBO-постингов Ozon, нормализации в БД и аналитики. Лёгкая интеграция для фронта (Flutter) с DB-first чтением.

## Статус и Итоги
- Инкрементальная синхронизация и сверка недавнего окна.
- Месячная сверка последних месяцев.
- Обогащение постингов: сразу после выгрузки, фоновые недавние, точечно по изменению статусов.
- Нормализованная схема: `Order`, `OrderHeader`, `OrderPosting`, `OrderProduct`, `Cost`.
- Аналитика: продажи за сегодня и количество заказов за сегодня.
 - Аналитика: продажи за сегодня (delivered), количество заказов за сегодня, "сырые" продажи по незавершённым статусам с периодом (`sales_today_raw`).
- Управление логами и параметрами через `.env`.

## Эндпоинты (основные)
- `GET /orders`
- `GET /orders/{posting_number}`
- `POST /orders/fbo`
- `POST /orders/fbo/get`
- `POST /orders/fbo/get_for_order`
- `POST /orders/fbo/enrich_recent`
- `POST /orders/fbo/enrich_changed_recent`
- `GET /order/{order_number}`
- `GET /order/{order_number}/postings`
- `POST /costs`, `GET /costs`
- `GET /stats`
- `POST /sync/initial`, `POST /sync/initial/force`, `POST /sync/history`
- `GET /analytics/sales_today`, `GET /analytics/orders_today`
 - `GET /analytics/sales_today_raw` (параметры: `since`, `to`, `include_statuses`, `tz_offset_hours`)
 - `GET /analytics/sales_by_date?date=YYYY-MM-DD&tz_offset_hours=3` (delivered)
 - `GET /analytics/sales_range?since=...&to=...&tz_offset_hours=3` (delivered)

## Файлы и Модули
- `main.py`: запуск приложения, бОльшая часть логики (будет декомпозирована).
- `routes/analytics.py`: аналитические эндпоинты.
- `db/database.py`: модели ORM и доступ к БД.
- `.env`: конфигурация (ключи Ozon и рабочие параметры).

## Пояснения по Постингам
- Постинг (`posting_number`) — конкретная отгрузка в рамках заказа `order_number`.
- Один заказ может иметь несколько постингов. Детали и финансы — в `/v2/posting/fbo/get`.
- В БД: `OrderPosting` (мета постинга) и `OrderProduct` (строки товаров).

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
