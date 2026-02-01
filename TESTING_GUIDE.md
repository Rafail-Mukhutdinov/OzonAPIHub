# Быстрый старт - Тестирование авторизации

## Текущий статус

✅ Backend: Запущен на http://127.0.0.1:8080  
✅ Flutter: Все зависимости установлены  
✅ Компиляция: Без ошибок  
⚠️ PostgreSQL: Не настроен (ожидается)

## Шаг 1: Настройка базы данных PostgreSQL

### Вариант A: Локальный PostgreSQL

```powershell
# Если PostgreSQL еще не установлен, скачайте с:
# https://www.postgresql.org/download/windows/

# После установки создайте базу данных:
psql -U postgres
```

В psql консоли:
```sql
CREATE DATABASE ozon_saas;
CREATE USER ozon_user WITH PASSWORD 'SecurePass2024!';
GRANT ALL PRIVILEGES ON DATABASE ozon_saas TO ozon_user;
\q
```

### Вариант B: Docker (рекомендуется для разработки)

```powershell
docker run -d `
  --name ozon_postgres `
  -e POSTGRES_DB=ozon_saas `
  -e POSTGRES_USER=ozon_user `
  -e POSTGRES_PASSWORD=SecurePass2024! `
  -p 5432:5432 `
  postgres:16-alpine
```

### Обновите .env

```env
DATABASE_URL=postgresql://ozon_user:SecurePass2024!@localhost:5432/ozon_saas
```

### Инициализируйте схему

```powershell
& venv\Scripts\Activate.ps1
python scripts/init_postgres.py
```

## Шаг 2: Перезапуск backend

```powershell
# Остановите текущий сервер (Ctrl+C в терминале где он запущен)

# Запустите снова:
& venv\Scripts\Activate.ps1
python -m uvicorn main:app --host 127.0.0.1 --port 8080 --reload
```

Проверьте что ошибок PostgreSQL нет:
```
INFO:     Uvicorn running on http://127.0.0.1:8080 (Press CTRL+C to quit)
```

## Шаг 3: Запуск Flutter Web

```powershell
cd ozon_sales_dashboard
flutter run -d chrome
```

**Ожидаемое поведение:**
1. Открывается Chrome
2. Показывается CheckAuthScreen с логотипом и spinner (1-2 секунды)
3. Автоматически перенаправляется на LoginScreen

## Шаг 4: Тестирование регистрации

1. На LoginScreen нажмите "Нет аккаунта? Зарегистрироваться"
2. Заполните форму:
   - Email: `test@example.com`
   - Password: `Test123!`
   - Confirm Password: `Test123!`
3. Нажмите "Зарегистрироваться"
4. Должен открыться DashboardScreen

## Шаг 5: Проверка токена

Откройте Chrome DevTools (F12):

**Application → Local Storage → http://127.0.0.1:XXXXX**

Должен быть ключ: `flutter.jwt_token`

Значение: `eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...` (длинная строка)

## Шаг 6: Тестирование auto-login

1. Перезагрузите страницу (F5)
2. Должен показаться CheckAuthScreen
3. Автоматически перенаправление на DashboardScreen (без экрана входа)

## Шаг 7: Тестирование logout

1. На DashboardScreen нажмите кнопку "Выход" (в AppBar)
2. Должен показаться LoginScreen
3. В DevTools → Local Storage проверьте что `jwt_token` удален

## Шаг 8: Настройка Ozon credentials

### Через API (curl)

```powershell
# Сначала войдите и скопируйте токен из DevTools

$token = "ваш_токен_из_localstorage"

curl -X PUT http://127.0.0.1:8080/auth/me/ozon-credentials `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{
    \"ozon_client_id\": \"ваш_client_id\",
    \"ozon_api_key\": \"ваш_api_key\"
  }'
```

### Через Flutter (будущая фича)

TODO: Добавить экран настроек в UI

## Диагностика проблем

### Проблема: Ошибка при регистрации

**Симптомы:** После нажатия "Зарегистрироваться" показывается ошибка

**Решение:**
1. Откройте Chrome DevTools → Network
2. Найдите запрос POST `/auth/register`
3. Проверьте Response:
   - 400: Email уже существует или валидация не прошла
   - 500: Ошибка сервера (проверьте логи backend)

### Проблема: DashboardScreen пустой

**Симптомы:** После входа дашборд показывает "Нет данных"

**Причина:** Ozon credentials не настроены

**Решение:** См. Шаг 8

### Проблема: CheckAuthScreen зависает

**Симптомы:** Spinner крутится бесконечно

**Решение:**
1. Откройте DevTools → Console
2. Проверьте ошибки JavaScript
3. Возможно SharedPreferences не работает (режим инкогнито?)

### Проблема: 401 после входа

**Симптомы:** После входа сразу возвращается на LoginScreen

**Решение:**
1. Проверьте что backend использует тот же JWT_SECRET_KEY
2. Перезапустите backend
3. Очистите localStorage и войдите снова

### Проблема: CORS ошибка

**Симптомы:** В консоли `Access-Control-Allow-Origin` ошибка

**Решение:**
Проверьте `main.py`:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:*", "http://127.0.0.1:*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Логи для диагностики

### Backend логи (важные)

```
INFO:     127.0.0.1:XXXXX - "POST /auth/register HTTP/1.1" 201 Created
INFO:     127.0.0.1:XXXXX - "POST /auth/login HTTP/1.1" 200 OK
INFO:     127.0.0.1:XXXXX - "GET /auth/me HTTP/1.1" 200 OK
```

### Flutter console (при запуске)

```
Launching lib/main.dart on Chrome in debug mode...
Waiting for connection from debug service on Chrome...
This app is linked to the debug service: ws://127.0.0.1:XXXXX/
Debug service listening on ws://127.0.0.1:XXXXX/
```

## Следующие шаги после успешного тестирования

- [ ] Добавить экран настроек Ozon credentials в UI
- [ ] Реализовать синхронизацию заказов
- [ ] Добавить экран аналитики продаж
- [ ] Настроить автоматическое обновление данных
- [ ] Добавить "Забыли пароль?"

## Полезные команды

### Очистить все данные Flutter

```powershell
cd ozon_sales_dashboard
flutter clean
flutter pub get
```

### Посмотреть логи PostgreSQL (если через Docker)

```powershell
docker logs ozon_postgres
```

### Подключиться к PostgreSQL

```powershell
docker exec -it ozon_postgres psql -U ozon_user -d ozon_saas
```

### Проверить таблицы

```sql
\dt
SELECT * FROM users;
```

### Проверить токен пользователя

```sql
SELECT email, is_trial, trial_ends_at FROM users WHERE email = 'test@example.com';
```
