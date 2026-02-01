# Flutter SaaS Integration - Финальная Структура

## Обзор изменений

Flutter приложение полностью интегрировано с SaaS backend и использует современные паттерны управления состоянием.

## Структура проекта

```
lib/
├── main.dart                          # Точка входа с MultiProvider
├── providers/
│   └── auth_provider.dart             # ChangeNotifier для авторизации
├── services/
│   ├── auth_service.dart              # API вызовы авторизации
│   └── api.dart                       # Ozon API клиент с interceptors
├── screens/
│   ├── check_auth_screen.dart         # Splash screen с проверкой токена
│   ├── login_screen.dart              # Экран входа
│   ├── register_screen.dart           # Экран регистрации
│   └── dashboard_screen.dart          # Главный экран приложения
└── widgets/
    ├── sales_table.dart               # Таблица продаж
    └── sales_chart.dart               # Графики аналитики
```

## Архитектура авторизации

### Provider Pattern

**AuthProvider** (`providers/auth_provider.dart`):
- Управляет глобальным состоянием авторизации
- Автоматически проверяет токен при запуске
- Уведомляет всех подписчиков при изменении состояния
- Методы: `setToken()`, `logout()`, `forceLogout()`

**AuthService** (`services/auth_service.dart`):
- Выполняет HTTP запросы к backend
- Callbacks для интеграции с Provider
- Методы: `login()`, `register()`, `logout()`, `getToken()`

### Поток данных

```
Запуск приложения
    ↓
MultiProvider создает AuthProvider
    ↓
AuthProvider._initAuth() проверяет SharedPreferences
    ↓
CheckAuthScreen ожидает завершения проверки
    ↓
Перенаправление:
    ├─ Токен есть → DashboardScreen
    └─ Токен нет → LoginScreen
```

### Обработка 401 ошибок

```
API запрос → 401 Unauthorized
    ↓
OzonApiClient.interceptor перехватывает ошибку
    ↓
onUnauthorized() callback
    ↓
AuthProvider.forceLogout()
    ↓
Удаление токена из SharedPreferences
    ↓
Navigator → LoginScreen
```

## API клиент (Dio)

### Interceptor для токена

```dart
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
    if (error.response?.statusCode == 401) {
      // Удалить токен и вызвать callback
      onUnauthorized?.call();
    }
    return handler.next(error);
  },
));
```

### Платформо-зависимый baseUrl

```dart
static String getDefaultBaseUrl() {
  if (!kIsWeb && Platform.isAndroid) {
    return 'http://10.0.2.2:8080';  // Android эмулятор
  }
  return 'http://127.0.0.1:8080';   // Web, iOS, Desktop
}
```

## Экраны

### CheckAuthScreen

**Цель**: Проверка авторизации при старте

**Логика**:
1. Показывает splash screen (логотип + индикатор)
2. Ждет завершения AuthProvider._initAuth()
3. Перенаправляет на Dashboard или Login

**Особенности**:
- Не использует `Consumer` для избежания лишних rebuild
- Использует `Provider.of<AuthProvider>(context, listen: false)`

### LoginScreen

**Поля**:
- Email (с валидацией формата)
- Password (минимум 6 символов)

**Процесс входа**:
1. Валидация формы
2. AuthService.login(email, password)
3. AuthProvider.setToken(token) через callback
4. Navigator → DashboardScreen

**Обработка ошибок**:
- 401: "Неверный email или пароль"
- Другие: Отображение текста ошибки

### RegisterScreen

**Поля**:
- Email
- Password
- Confirm Password (с проверкой совпадения)

**Процесс регистрации**:
1. Валидация (включая совпадение паролей)
2. AuthService.register(email, password, confirmPassword)
3. AuthProvider.setToken(token) через callback
4. Navigator → DashboardScreen

**Дополнительно**:
- Info box с информацией о пробном периоде (30 дней)

### DashboardScreen

**Особенности**:
- OzonApiClient создается с `onUnauthorized` callback
- При 401 автоматически разлогинивает пользователя
- Кнопка "Выход" использует AuthProvider.logout()

## Управление токеном

### Хранение

**SharedPreferences** (работает на Web как LocalStorage):
- Ключ: `jwt_token`
- Значение: Plain text JWT string
- Автоматическая загрузка при старте

### Безопасность

⚠️ **Важно**: В production используйте:
- HTTPS для всех запросов
- HttpOnly cookies (альтернатива localStorage)
- Refresh tokens для долгосрочных сессий

## Зависимости

```yaml
dependencies:
  flutter:
    sdk: flutter
  dio: ^5.9.0                     # HTTP клиент с interceptors
  shared_preferences: ^2.2.2      # Хранение токена (Web-compatible)
  provider: ^6.1.1                # Управление состоянием
  intl: ^0.20.2                   # Локализация дат
  fl_chart: ^0.68.0               # Графики
```

## Запуск

### 1. Установите зависимости

```bash
cd ozon_sales_dashboard
flutter pub get
```

### 2. Запустите backend

```bash
cd ..
& venv\Scripts\Activate.ps1
python -m uvicorn main:app --host 127.0.0.1 --port 8080
```

### 3. Запустите Flutter

**Web**:
```bash
flutter run -d chrome
```

**Desktop Windows**:
```bash
flutter run -d windows
```

### 4. Зарегистрируйтесь

1. Откроется CheckAuthScreen (splash)
2. Перенаправит на LoginScreen
3. Нажмите "Нет аккаунта? Зарегистрироваться"
4. Заполните форму регистрации
5. После успешной регистрации откроется DashboardScreen

### 5. Настройте Ozon credentials

```bash
curl -X PUT http://127.0.0.1:8080/auth/me/ozon-credentials \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "ozon_client_id": "ваш_client_id",
    "ozon_api_key": "ваш_api_key"
  }'
```

## Отладка

### Проверить токен в браузере

**Chrome DevTools → Application → Local Storage → http://127.0.0.1:port**

Ключ: `flutter.jwt_token`

### Очистить токен

```javascript
localStorage.removeItem('flutter.jwt_token')
```

### Логирование запросов

Добавьте в `api.dart`:

```dart
dio.interceptors.add(LogInterceptor(
  requestBody: true,
  responseBody: true,
  requestHeader: true,
  responseHeader: true,
));
```

## Production настройки

### 1. Обновите baseUrl

В `lib/services/api.dart`:

```dart
static String getDefaultBaseUrl() {
  return 'https://your-production-api.com';
}
```

### 2. Соберите релиз

```bash
flutter build web --release
```

### 3. CORS на backend

В `main.py`:

```python
origins = [
    "https://your-frontend-domain.com",
]
```

## Типичные проблемы

**Q**: После входа дашборд пустой  
**A**: Настройте Ozon credentials через API endpoint

**Q**: Токен не сохраняется  
**A**: Проверьте, что браузер не блокирует localStorage (режим инкогнито может блокировать)

**Q**: 401 после входа  
**A**: Токен истек или невалиден. Разлогиньтесь и войдите снова

**Q**: Provider not found  
**A**: Убедитесь, что используете `context` внутри виджета, обернутого в MultiProvider

## Следующие шаги

- [ ] Добавить экран настроек Ozon credentials в UI
- [ ] Реализовать "Забыли пароль?"
- [ ] Добавить индикатор статуса синхронизации
- [ ] Показывать дату окончания пробного периода
- [ ] Offline режим с кэшированием
- [ ] Refresh tokens для автоматического обновления
