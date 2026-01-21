/// API конфигурация
/// Поддерживает настройку через переменные окружения или явный параметр
class ApiConfig {
  static late String _baseUrl;
  static bool _initialized = false;

  /// Инициализировать конфиг с URL
  /// Если [customUrl] не передан, использует значение из String.fromEnvironment
  static void initialize({String? customUrl}) {
    if (_initialized) return;
    
    // Попытка 1: явно переданный URL
    if (customUrl != null && customUrl.isNotEmpty) {
      _baseUrl = customUrl;
    } else {
      // Попытка 2: переменная окружения (для Flutter build)
      const envUrl = String.fromEnvironment(
        'API_URL',
        defaultValue: '',
      );
      if (envUrl.isNotEmpty) {
        _baseUrl = envUrl;
      } else {
        // Попытка 3: значение по умолчанию для локальной разработки
        _baseUrl = _detectDefaultUrl();
      }
    }
    
    _initialized = true;
  }

  /// Получить текущий base URL
  static String get baseUrl {
    if (!_initialized) {
      initialize();
    }
    return _baseUrl;
  }

  /// Переустановить конфиг (для тестирования)
  static void reset() {
    _initialized = false;
  }

  /// Определить URL по умолчанию в зависимости от платформы
  static String _detectDefaultUrl() {
    // На реальном устройстве/веб нужно указывать IP вручную
    // Для локальной разработки Desktop используем localhost
    // Для Android эмулятора нужно использовать 10.0.2.2
    // Для iOS эмулятора нужно использовать localhost (после настройки туннеля)
    
    // По умолчанию: localhost для desktop и web разработки
    return 'http://127.0.0.1:8080';
  }

  /// Получить URL для Android эмулятора
  /// (10.0.2.2 указывает на хост-машину из Android эмулятора)
  static String get emulatorUrl => 'http://10.0.2.2:8080';

  /// Получить URL для реального устройства
  /// Замени X.X.X.X на IP твоего компьютера в локальной сети
  static String getDeviceUrl(String localIp) => 'http://$localIp:8080';
}
