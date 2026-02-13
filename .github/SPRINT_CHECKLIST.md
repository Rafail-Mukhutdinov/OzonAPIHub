# ✅ Sprint Checklist - OzonAPIHub Improvements

**Последнее обновление:** 13 февраля 2026 г.  
**Статус проекта:** 📋 Planning Phase

---

## 🏃 Sprint 1: Критичные улучшения (5 дней)

### День 1-2: Rate Limiting ⏳ Not Started

**Зависимости:**
- [ ] Установлен Redis (локально или Docker)
- [ ] Добавлено в requirements.txt: `redis==5.0.1`, `slowapi==0.1.9`

**Создание файлов:**
- [ ] `utils/rate_limiter.py` — класс RateLimiter
- [ ] `middleware/rate_limit_middleware.py` — FastAPI middleware
- [ ] Обновить `main.py` — добавить middleware
- [ ] Обновить `.env` — настройки rate limiting

**Тестирование:**
- [ ] `scripts/test_rate_limit.py` — тест превышения лимитов
- [ ] Ручное тестирование через Postman/curl
- [ ] Проверка Redis счётчиков

**Критерии приёмки:**
- [ ] ✓ 429 ответ при превышении user limit (10 req/min)
- [ ] ✓ 429 при превышении global limit (100 req/min)
- [ ] ✓ Redis корректно хранит счётчики
- [ ] ✓ Публичные эндпоинты не лимитируются

**Время:** ⏱️ Планируемое: 2 дня | Фактическое: ___ дня

---

### День 3-4: Кеширование (базовое) ⏳ Not Started

**Зависимости:**
- [ ] Redis работает (из Sprint 1 Day 1-2)

**Создание файлов:**
- [ ] `utils/cache_manager.py` — класс CacheManager
- [ ] `utils/cache_decorator.py` — декоратор @cached
- [ ] Обновить `routes/analytics.py` — применить кеширование
- [ ] Обновить `services/enrichment.py` — инвалидация
- [ ] Обновить `main.py` — инициализация cache в startup

**Эндпоинты для кеширования:**
- [ ] `/analytics/sales_today` — TTL 5 минут
- [ ] `/analytics/sales_range` — TTL 5 минут
- [ ] `/analytics/orders_today` — TTL 5 минут

**Мониторинг:**
- [ ] Добавить эндпоинт `/cache/stats`
- [ ] Логирование cache HIT/MISS

**Критерии приёмки:**
- [ ] ✓ Cache hit rate >60% для аналитики
- [ ] ✓ Время ответа <100ms с кешем
- [ ] ✓ Инвалидация работает при обновлении заказов
- [ ] ✓ TTL корректно истекает

**Время:** ⏱️ Планируемое: 2 дня | Фактическое: ___ дня

---

### День 5: CORS для Production ⏳ Not Started

**Создание файлов:**
- [ ] Обновить `main.py` — окружение-зависимые CORS
- [ ] Создать `.env.production` — пример production конфига
- [ ] Обновить `README.md` — инструкции по CORS

**Настройки:**
- [ ] `ENVIRONMENT=development` для dev
- [ ] `ENVIRONMENT=production` для prod
- [ ] `ALLOWED_ORIGINS` — список разрешённых доменов

**Тестирование:**
- [ ] Dev режим — localhost работает
- [ ] Production режим — только whitelist доменов
- [ ] Preflight OPTIONS requests проходят
- [ ] Ошибка если ALLOWED_ORIGINS пуст в production

**Критерии приёмки:**
- [ ] ✓ Production домены работают
- [ ] ✓ Localhost работает в dev
- [ ] ✓ CORS errors отсутствуют

**Время:** ⏱️ Планируемое: 1 день | Фактическое: ___ день

---

## 🏃 Sprint 2: Инфраструктура (4 дня)

### День 6-7: Alembic миграции ⏳ Not Started

**Установка:**
- [ ] `pip install alembic==1.13.1`
- [ ] `alembic init alembic`

**Конфигурация:**
- [ ] Обновить `alembic/env.py` — импорт моделей, .env
- [ ] Обновить `alembic.ini` — настройки

**Создание миграций:**
- [ ] `alembic revision --autogenerate -m "Initial migration"`
- [ ] Проверить сгенерированный файл
- [ ] `alembic upgrade head`

**CI/CD:**
- [ ] `.github/workflows/migrations.yml` — автопроверка

**Документация:**
- [ ] Обновить README — секция Alembic
- [ ] Создать guide по созданию миграций

**Критерии приёмки:**
- [ ] ✓ Все модели покрыты миграциями
- [ ] ✓ `alembic upgrade head` работает
- [ ] ✓ `alembic downgrade -1` работает
- [ ] ✓ CI проверяет pending migrations

**Время:** ⏱️ Планируемое: 2 дня | Фактическое: ___ дня

---

### День 8: Расширенное кеширование ⏳ Not Started

**Эндпоинты для кеширования:**
- [ ] `/orders` — список заказов (TTL 1 мин)
- [ ] `/order/{order_number}` — детали заказа (TTL 10 мин)
- [ ] `/order/{order_number}/postings` — постинги (TTL 10 мин)
- [ ] `/stats` — статистика (TTL 30 мин)

**Оптимизация TTL:**
- [ ] Проанализировать частоту обновлений
- [ ] Настроить оптимальные значения
- [ ] Добавить в конфиг .env

**Мониторинг:**
- [ ] Расширить `/cache/stats` — детальная статистика
- [ ] Добавить логирование invalidation events

**Критерии приёмки:**
- [ ] ✓ Все основные эндпоинты кешируются
- [ ] ✓ TTL оптимизированы
- [ ] ✓ Метрики показывают улучшение

**Время:** ⏱️ Планируемое: 1 день | Фактическое: ___ день

---

### День 9: Адаптивный Timeout ⏳ Not Started

**Обновление файлов:**
- [ ] `services/ozon.py` — адаптивный timeout
- [ ] Добавить exceptions: `OzonTimeoutError`, `OzonRateLimitError`
- [ ] Улучшенная retry стратегия

**Мониторинг:**
- [ ] `utils/ozon_metrics.py` — класс OzonMetrics
- [ ] Добавить эндпоинт `/ozon/metrics`

**Настройки .env:**
- [ ] `OZON_DEFAULT_TIMEOUT=60`
- [ ] `OZON_LONG_TIMEOUT=120`
- [ ] `OZON_MAX_RETRIES=3`
- [ ] `OZON_RETRY_BACKOFF_SECONDS=2.0`

**Критерии приёмки:**
- [ ] ✓ Большие запросы используют LONG_TIMEOUT
- [ ] ✓ Retry работает для 429/5xx
- [ ] ✓ Метрики показывают снижение timeout'ов

**Время:** ⏱️ Планируемое: 1 день | Фактическое: ___ день

---

## 🏃 Sprint 3: Тестирование и документация (2 дня)

### День 10: Интеграционные тесты ⏳ Not Started

**Создание тестов:**
- [ ] `tests/test_rate_limit.py` — rate limiting
- [ ] `tests/test_cache.py` — кеширование
- [ ] `tests/test_cors.py` — CORS
- [ ] `tests/test_migrations.py` — Alembic
- [ ] `tests/test_ozon_timeout.py` — timeout и retry

**Нагрузочное тестирование:**
- [ ] `tests/load_test.py` — Locust сценарий
- [ ] Тест с 100 concurrent users
- [ ] Тест с 100 RPS

**Отказоустойчивость:**
- [ ] Тест Redis down — graceful degradation
- [ ] Тест DB down — error handling
- [ ] Тест Ozon API down — retry механизм

**Критерии приёмки:**
- [ ] ✓ Все unit тесты зелёные
- [ ] ✓ Coverage >80%
- [ ] ✓ Нагрузка 100 RPS без ошибок
- [ ] ✓ Graceful degradation работает

**Время:** ⏱️ Планируемое: 1 день | Фактическое: ___ день

---

### День 11: Документация ⏳ Not Started

**Обновление документации:**
- [ ] `README.md` — актуализация
- [ ] `ROADMAP.md` — обновление статусов
- [ ] `CHANGELOG.md` — новая версия 1.1.0
- [ ] Swagger `/docs` — описания эндпоинтов

**Новые документы:**
- [ ] `docs/DEPLOYMENT.md` — инструкции деплоя
- [ ] `docs/MONITORING.md` — мониторинг и алерты
- [ ] `docs/TROUBLESHOOTING.md` — решение проблем
- [ ] `docs/API_CLIENTS.md` — примеры клиентов

**Видео/демо:**
- [ ] Screencast — новые фичи
- [ ] Tutorial — настройка production

**Критерии приёмки:**
- [ ] ✓ Новички могут развернуть за 30 минут
- [ ] ✓ Все фичи задокументированы
- [ ] ✓ API docs актуальны

**Время:** ⏱️ Планируемое: 1 день | Фактическое: ___ день

---

## 📊 Общий прогресс

### Sprint Summary

| Sprint | Статус | Прогресс | Дней |
|--------|--------|----------|------|
| Sprint 1 | ⏳ Not Started | 0/5 | 0/5 |
| Sprint 2 | ⏳ Not Started | 0/4 | 0/4 |
| Sprint 3 | ⏳ Not Started | 0/2 | 0/2 |
| **Всего** | **⏳ Not Started** | **0/11** | **0/11** |

### Метрики

**Целевые показатели:**
- [ ] Cache Hit Rate: 0% → >60%
- [ ] Response Time (analytics): 500ms → <100ms
- [ ] Rate Limit Violations: N/A → 0
- [ ] Ozon Timeout Rate: ~5% → <2%
- [ ] Database QPS: 50 → <20

**Текущие показатели:**
- Cache Hit Rate: 0% (нет кеша)
- Response Time: ~500ms
- Rate Limit: не реализован
- Timeout Rate: ~5%
- DB QPS: ~50

---

## ⚠️ Блокеры и риски

### Текущие блокеры
_Нет блокеров_

### Потенциальные риски

| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| Redis недоступен в production | Средняя | Высокое | Graceful degradation без кеша |
| Alembic конфликты миграций | Низкая | Среднее | Code review миграций |
| CORS не работает на prod домене | Низкая | Высокое | Тестирование на staging |
| Нагрузка >100 RPS ломает систему | Средняя | Высокое | Нагрузочное тестирование |

---

## 📝 Примечания

### Уроки Sprint 1
_Будет заполнено после завершения_

### Уроки Sprint 2
_Будет заполнено после завершения_

### Уроки Sprint 3
_Будет заполнено после завершения_

---

## 🎯 Следующие шаги

**Для начала работы:**

1. Прочитать [ROADMAP.md](../ROADMAP.md)
2. Создать feature branch: `git checkout -b feature/rate-limiting`
3. Начать с Sprint 1, Day 1-2
4. Отмечать выполненные задачи в этом чек-листе
5. Коммитить регулярно с понятными сообщениями

**Git workflow:**
```bash
# Создать ветку для фичи
git checkout -b feature/rate-limiting

# После выполнения задачи
git add .
git commit -m "feat: implement rate limiting with Redis"

# Push и создание PR
git push origin feature/rate-limiting
```

---

**Последнее обновление:** 13 февраля 2026 г.  
**Автор:** OzonAPIHub Team  
**Следующий review:** После каждого Sprint
