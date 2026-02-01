# Flutter Web — Инструкция по запуску с JWT авторизацией

## Обзор изменений

Flutter приложение теперь поддерживает JWT аутентификацию и работает с SaaS backend. Каждый пользователь работает со своими данными Ozon.

## Установка зависимостей

```bash
cd ozon_sales_dashboard
flutter pub get
```

## Запуск приложения

### Web (рекомендовано для разработки)

```bash
flutter run -d chrome
```

### Desktop (Windows)

```bash
flutter run -d windows
```

### Android

```bash
flutter run -d android
```

## Первый запуск

### 1. Запустите Backend

```bash
cd ..
& venv\Scripts\Activate.ps1
python -m uvicorn main:app --host 127.0.0.1 --port 8080
```

### 2. Откройте Flutter приложение

При первом запуске вы увидите **экран входа** (LoginScreen).

### 3. Создайте аккаунт

- Нажмите **"Нет аккаунта? Зарегистрироваться"**
- Введите email и пароль (минимум 6 символов)
- После регистрации вы автоматически войдете в систему
- **Пробный период**: 30 дней

### 4. Настройте Ozon credentials

После входа дашборд будет пустым. Вам нужно настроить Ozon API ключи:

#### Через API (Postman/curl):

```bash
curl -X PUT http://127.0.0.1:8080/auth/me/ozon-credentials \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "ozon_client_id": "ваш_client_id",
    "ozon_api_key": "ваш_api_key"
  }'
```

#### Или через PostgreSQL:

```sql
UPDATE users 
SET ozon_client_id = encrypt_credential('ваш_client_id'),
    ozon_api_key = encrypt_credential('ваш_api_key')
WHERE email = 'ваш_email';
```

### 5. Дождитесь синхронизации

Backend автоматически начнет синхронизацию заказов каждые 5 минут (настраивается в `main.py`).

Проверьте логи сервера:

```
INFO:     User your_email@example.com: синхронизировано 42 заказов
```

### 6. Обновите дашборд

Нажмите кнопку **"Обновить"** или **иконку обновления** в AppBar.

## Основные экраны

### LoginScreen

- **Email**: Ваш email для входа
- **Пароль**: Минимум 6 символов
- **Кнопка "Войти"**: Отправляет запрос на `/auth/login`
- **Ссылка на регистрацию**: Открывает RegisterScreen

### RegisterScreen

- **Email**: Уникальный email (проверка на backend)
- **Пароль**: Минимум 6 символов
- **Подтверждение пароля**: Должно совпадать
- **Пробный период**: 30 дней автоматически

### DashboardScreen

- **AppBar**: Кнопки "Обновить" и "Выход"
- **Переключатель режимов**: Финансы / Отгрузки
- **Выбор дат**: Фильтрация по периоду
- **Фильтр статусов**: Все статусы / Отдельные
- **Таблица заказов**: Динамические данные пользователя
- **Графики**: Динамика продаж по месяцам

## Технические детали

### Хранение токена

- **Web / Desktop**: `SharedPreferences` (LocalStorage в браузере)
- **Ключ**: `jwt_token`
- **Формат**: Plain text JWT string

### API клиент

**Файл**: `lib/services/api.dart`

**Автоматические заголовки**:
```dart
Authorization: Bearer <token>
```

**Обработка 401**:
- Удаляет невалидный токен
- Вызывает `onUnauthorized` callback
- Перенаправляет на LoginScreen

### Lifecycle авторизации

```
Запуск → AuthGate (проверка токена)
  ├─ Токен есть → DashboardScreen
  └─ Токен нет → LoginScreen
      └─ Успешный вход → DashboardScreen
          └─ API возвращает 401 → Logout → LoginScreen
```

## Настройка backend URL

### Автоматический выбор

**Файл**: `lib/services/api.dart`

```dart
static String getDefaultBaseUrl() {
  if (!kIsWeb && Platform.isAndroid) {
    return 'http://10.0.2.2:8080';  // Android эмулятор
  }
  return 'http://127.0.0.1:8080';   // Web, iOS, Desktop
}
```

### Переопределение

```dart
final api = OzonApiClient(baseUrl: 'http://your-server.com:8080');
```

## Отладка

### Включить логирование запросов

**Добавьте в `lib/services/api.dart`**:

```dart
dio.interceptors.add(LogInterceptor(
  requestBody: true,
  responseBody: true,
));
```

### Проверить токен

**Flutter DevTools Console**:

```dart
import 'package:shared_preferences/shared_preferences.dart';

final prefs = await SharedPreferences.getInstance();
print(prefs.getString('jwt_token'));
```

### Очистить токен вручную

```dart
final prefs = await SharedPreferences.getInstance();
await prefs.remove('jwt_token');
```

## Производство (Production)

### 1. Обновите backend URL

В `lib/services/api.dart`:

```dart
static String getDefaultBaseUrl() {
  return 'https://your-production-api.com';
}
```

### 2. Соберите Web версию

```bash
flutter build web --release
```

Файлы в `build/web/` готовы для деплоя на любой статический хостинг (Netlify, Vercel, Firebase Hosting).

### 3. CORS настройки

В `main.py` убедитесь, что ваш домен разрешен:

```python
origins = [
    "https://your-frontend-domain.com",
]
```

## Часто задаваемые вопросы

**Q**: Почему после входа дашборд пустой?  
**A**: Нужно настроить Ozon credentials и дождаться синхронизации.

**Q**: Токен не сохраняется в Web  
**A**: Проверьте, что браузер не блокирует LocalStorage. Используйте HTTPS в production.

**Q**: 401 ошибка после входа  
**A**: Токен истек или невалиден. Разлогиньтесь и войдите снова.

**Q**: Как добавить "Забыли пароль?"  
**A**: Нужно реализовать endpoint `/auth/reset-password` на backend и экран восстановления на Flutter.

## Следующие шаги

- [ ] Добавить экран настроек Ozon credentials
- [ ] Реализовать "Забыли пароль?"
- [ ] Добавить индикатор загрузки при синхронизации
- [ ] Показывать дату последней синхронизации
- [ ] Уведомления об истечении пробного периода
- [ ] Offline режим с кэшированием данных
