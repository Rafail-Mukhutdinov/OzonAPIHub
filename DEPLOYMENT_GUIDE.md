# РУКОВОДСТВО ПО ПРИМЕНЕНИЮ ИСПРАВЛЕНИЙ АНАЛИТИКИ

## ШАГ 1: Развертывание кода

### 1.1 Обновить файлы
Следующие файлы были исправлены:
- `routes/analytics.py` — Исправлена логика фильтрации и расширение окна
- `services/enrichment.py` — Добавлен db.commit()

### 1.2 Проверить синтаксис
```powershell
python -m py_compile routes/analytics.py services/enrichment.py
```

### 1.3 Перезагрузить сервер
```powershell
# Остановить текущий сервер (Ctrl+C если запущен)
# Запустить заново:
python -m uvicorn main:app --host 127.0.0.1 --port 8080
```

---

## ШАГ 2: Переобогащение исторических данных (опционально)

Если аналитика за 10-15 июня показывает неправильные значения, нужно переобогатить данные.

### 2.1 Проверить текущие данные

```python
# script: check_current_analytics.py
from db.database import SessionLocal, Order, OrderPosting, OrderProduct
from sqlalchemy import func

db = SessionLocal()

# Проверим количество заказов и товаров за период
orders_10_15 = db.query(Order).filter(
    Order.created_at >= "2026-06-10",
    Order.created_at <= "2026-06-15"
).count()

postings_10_15 = db.query(OrderPosting).filter(
    OrderPosting.created_at >= "2026-06-10T00:00:00Z",
    OrderPosting.created_at <= "2026-06-15T23:59:59Z"
).count()

products_10_15 = db.query(OrderProduct).filter(
    OrderProduct.posting_number.in_(
        db.query(OrderPosting.posting_number).filter(
            OrderPosting.created_at >= "2026-06-10T00:00:00Z"
        )
    )
).count()

print(f"Order за 10-15: {orders_10_15}")
print(f"OrderPosting за 10-15: {postings_10_15}")
print(f"OrderProduct за 10-15: {products_10_15}")

db.close()
```

### 2.2 Переобогатить конкретные заказы

Если товаров не хватает, нужно переобогатить:

```bash
# Обогатить заказы за дату
# Используйте эндпоинт POST /sync/backfill с параметрами:
# - since: "2026-06-10T00:00:00Z"
# - to: "2026-06-15T23:59:59Z"
```

Или через Python:

```python
# script: re_enrich_period.py
import asyncio
from datetime import datetime
from db.database import SessionLocal, OrderPosting, User
from services.enrichment import enrich_posting_from_ozon
from utils.encryption import decrypt_credential
from db.database import OzonCredential

async def re_enrich_user_postings(user_id: int, since_date: str, to_date: str):
    """Переобогащает все постинги пользователя в диапазоне дат"""
    db = SessionLocal()
    
    try:
        # Получаем все постинги в диапазоне
        postings = db.query(OrderPosting).filter(
            OrderPosting.user_id == user_id,
            OrderPosting.created_at >= f"{since_date}T00:00:00Z",
            OrderPosting.created_at <= f"{to_date}T23:59:59Z"
        ).all()
        
        print(f"Найдено {len(postings)} постингов для переобогащения")
        
        # Переобогащаем каждый
        for i, posting in enumerate(postings):
            print(f"[{i+1}/{len(postings)}] Обогащаем {posting.posting_number}...")
            result = await enrich_posting_from_ozon(posting.posting_number, user_id, db)
            if result.get("status") == "ok":
                print(f"  ✓ OK")
            else:
                print(f"  ✗ ОШИБКА: {result}")
        
        print(f"✓ Переобогащение завершено")
        
    except Exception as e:
        print(f"✗ Ошибка: {e}")
    finally:
        db.close()

# Запуск
asyncio.run(re_enrich_user_postings(
    user_id=1,  # Замените на реальный ID
    since_date="2026-06-10",
    to_date="2026-06-15"
))
```

---

## ШАГ 3: Тестирование исправлений

### 3.1 Запустить unit тесты
```bash
python test_analytics_fix.py
```

Ожидаемый результат:
```
✓ ТЕСТ 1: Конвертация времени UTC -> MSK — все PASS
✓ ТЕСТ 2: Расширение окна поиска — сокращено с 28 до 8 часов
✓ ТЕСТ 3: Детекция отмен — все форматы обработаны
✓ ТЕСТ 4: Расчет выручки — цена × количество
✓ ТЕСТ 5: String сравнение дат — ISO работает правильно
```

### 3.2 Проверить эндпоинты в Swagger

1. Открыть http://127.0.0.1:8080/docs
2. Авторизоваться
3. Протестировать endpoints:
   - `GET /analytics/daily_stats?since=2026-06-10&to=2026-06-15`
   - `GET /analytics/sales_report?since=2026-06-10&to=2026-06-15`

Ожидаемые результаты:
- Данные должны совпадать с Личным Кабинетом Озона
- Отмены должны быть исключены (если `include_cancelled=false`)
- Выручка = sum(price × quantity) за каждый товар

### 3.3 Сравнить с Озоном вручную

**За 15 июня:**
1. В Личном Кабинете Озона:
   - Выручка: XXX ₽
   - Количество товаров: YYY шт

2. В OzonAPIHub:
   ```bash
   curl -X GET "http://127.0.0.1:8080/analytics/daily_stats?since=2026-06-15&to=2026-06-15"
   ```
   - Должно быть: выручка = XXX, items = YYY

---

## ШАГ 4: Мониторинг после развертывания

### 4.1 Логирование

В файле `.env` установите:
```
LOG_LEVEL=INFO
```

Проверяйте логи:
```bash
tail -f logs/app.log
```

Ищите строки вроде:
```
[INFO] [ANALYTICS] Fetched dates: 2026-06-10_2026-06-15, postings: 42, revenue: 125000
```

### 4.2 Автоматическая проверка согласованности

Добавить в cron (Linux) или Task Scheduler (Windows):

```bash
# Каждый день в 9:00 проверять согласованность
0 9 * * * python /path/to/check_analytics_consistency.py
```

Скрипт:
```python
# scripts/check_analytics_consistency.py
from datetime import datetime, timedelta
import requests

yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

# Получить данные из API
response = requests.get(
    "http://127.0.0.1:8080/analytics/daily_stats",
    params={"since": yesterday, "to": yesterday},
    headers={"Authorization": "Bearer YOUR_TOKEN"}
)

data = response.json()
if data.get("data"):
    stats = data["data"][0]
    print(f"✓ Данные за {yesterday}: revenue={stats['revenue']}, items={stats['items']}")
else:
    print(f"✗ Ошибка: нет данных за {yesterday}")
```

---

## ШАГ 5: Откат (если что-то пошло не так)

### 5.1 Откатить изменения Git

```bash
git checkout routes/analytics.py services/enrichment.py
```

### 5.2 Очистить test файлы (опционально)

```bash
rm test_analytics_fix.py ANALYTICS_FIX_REPORT.md
```

### 5.3 Перезагрузить сервер

```powershell
# Ctrl+C для остановки
# Запустить заново
python -m uvicorn main:app --host 127.0.0.1 --port 8080
```

---

## ШАГ 6: Долгосрочные улучшения

После проверки исправлений:

1. **Добавить интеграционные тесты**
   - Создать test данные
   - Проверить аналитику
   - Автоматизировать в CI/CD

2. **Оптимизировать индексы**
   ```sql
   CREATE INDEX idx_order_posting_created_at 
   ON order_postings(user_id, created_at);
   
   CREATE INDEX idx_order_product_posting 
   ON order_products(posting_number, user_id);
   ```

3. **Добавить кэширование**
   - Кэшировать результаты на 5-15 минут
   - Redis или встроенный cache

4. **Документировать часовые пояса**
   - Добавить комментарии о UTC vs MSK
   - Убедиться что все разработчики понимают

---

## Контрольный список

- [ ] Обновлены файлы analytics.py и enrichment.py
- [ ] Проверен синтаксис (py_compile успешен)
- [ ] Перезагружен сервер
- [ ] Запущены unit тесты (test_analytics_fix.py)
- [ ] Протестированы эндпоинты в Swagger
- [ ] Сравнены данные с Личным Кабинетом Озона
- [ ] Переобогащены исторические данные (если нужно)
- [ ] Настроено логирование
- [ ] Мониторинг включен

---

## Поддержка

Если есть проблемы:

1. Проверить логи: `logs/app.log`
2. Запустить test_analytics_fix.py
3. Проверить синтаксис: `python -m py_compile routes/analytics.py`
4. Откатить изменения и перезагрузить
5. Обратиться к разработчику с логами и описанием проблемы
