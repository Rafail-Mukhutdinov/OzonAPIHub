import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter/foundation.dart';
import 'package:provider/provider.dart';
import 'package:local_auth/local_auth.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../screens/login_screen.dart';
import '../screens/dashboard_screen.dart';
import '../screens/pin_screen.dart';
import '../services/api.dart';
import '../services/update_service.dart';

/// AuthProvider — центральный узел управления сессией пользователя.
/// Хранит состояние аутентификации, токены и настройки безопасности (ПИН, биометрия).
/// Использует [ChangeNotifier] для уведомления UI об изменениях состояния.
class AuthProvider extends ChangeNotifier {
  // Ключи для хранения данных в SharedPreferences и SecureStorage
  static const String _tokenKey = 'jwt_token';
  static const String _emailKey = 'user_email';
  static const String _isAdminKey = 'is_admin';
  static const String _isDemoKey = 'is_demo';
  static const String _subEndDateKey = 'subscription_end_date';
  static const String _biometricEnabledKey = 'biometric_enabled';
  static const String _pinKey = 'user_pin';
  static const String _adminTokenBackupKey = 'admin_original_token';
  static const String _adminEmailBackupKey = 'admin_original_email';

  // Внутренние сервисы для защищенного хранения и биометрии
  final _secureStorage = const FlutterSecureStorage();
  final _localAuth = LocalAuthentication();

  String? _token;             // Активный JWT токен для запросов к API
  String? _userEmail;         // Email текущего пользователя
  String? _pinCode;           // ПИН-код для локальной защиты приложения
  String? _originalAdminToken; // Резервная копия токена админа при имитации пользователя
  bool _isAdmin = false;      // Флаг прав администратора
  bool _isDemo = false;       // Флаг демо-режима аккаунта
  DateTime? _subscriptionEndDate; // Дата окончания подписки
  bool _isAuthenticated = false;  // Флаг наличия валидного токена в сессии
  bool _isLocalAuthenticated = false; // Флаг прохождения проверки ПИН/биометрии
  bool _isLoading = true;         // Флаг процесса инициализации провайдера
  bool _biometricEnabled = false;  // Включен ли вход по отпечатку
  bool _needsBiometricPrompt = false; // Нужно ли предложить включить биометрию

  // Геттеры для доступа к состоянию из UI
  bool get isAuthenticated => _isAuthenticated;
  bool get isLocalAuthenticated => _isLocalAuthenticated;
  bool get isLoading => _isLoading;
  bool get needsBiometricPrompt => _needsBiometricPrompt;
  bool get isImpersonating => _originalAdminToken != null;
  String? get token => _token;
  String? get userEmail => _userEmail;
  bool get isAdmin => _isAdmin;
  bool get isDemo => _isDemo;
  DateTime? get subscriptionEndDate => _subscriptionEndDate;
  bool get biometricEnabled => _biometricEnabled;
  bool get hasPin => _pinCode?.length == 4;

  AuthProvider() {
    _initAuth();
  }

  /// Инициализация провайдера: загрузка данных из хранилища при старте приложения.
  Future<void> _initAuth() async {
    try {
      final prefs = await SharedPreferences.getInstance();

      if (kIsWeb) {
        // На Web используем обычные настройки (SecureStorage требует HTTPS/спец.настройки)
        _token = prefs.getString(_tokenKey);
        _originalAdminToken = prefs.getString(_adminTokenBackupKey);
        _pinCode = null;
      } else {
        // На Mobile используем защищенное хранилище для чувствительных данных
        try {
          _token = await _secureStorage.read(key: _tokenKey);
          _pinCode = await _secureStorage.read(key: _pinKey);
          _originalAdminToken = await _secureStorage.read(key: _adminTokenBackupKey);
        } catch (e) {
          debugPrint("_initAuth: secureStorage error: $e");
        }
      }

      _userEmail = prefs.getString(_emailKey);
      _isAdmin = prefs.getBool(_isAdminKey) ?? false;
      _isDemo = prefs.getBool(_isDemoKey) ?? false;
      final subDateStr = prefs.getString(_subEndDateKey);
      if (subDateStr != null) {
        _subscriptionEndDate = DateTime.tryParse(subDateStr);
      }
      _biometricEnabled = prefs.getBool(_biometricEnabledKey) ?? false;

      final token = _token;
      _isAuthenticated = token != null && token.isNotEmpty;
      _isLocalAuthenticated = false;
      _isLoading = false;
      
      // Уведомляем систему, что данные загружены
      notifyListeners();
    } catch (e) {
      debugPrint("Init auth error: $e");
      _isLoading = false;
      notifyListeners();
    }
  }

  /// Установка ПИН-кода для локальной защиты.
  Future<void> setPin(String pin) async {
    if (kIsWeb) return;
    try {
      await _secureStorage.write(key: _pinKey, value: pin);
      _pinCode = pin;
    } catch (e) {
      debugPrint("setPin: secureStorage write error: $e");
      _pinCode = pin;
    }
    notifyListeners();
  }

  /// Проверка введенного ПИН-кода.
  bool verifyPin(String enteredPin) {
    if (_pinCode == enteredPin) {
      _isLocalAuthenticated = true;
      notifyListeners();
      return true;
    }
    return false;
  }

  /// Попытка аутентификации через биометрию (отпечаток/лицо).
  Future<bool> authenticateWithBiometrics() async {
    if (kIsWeb) return false;
    if (!_biometricEnabled) return false;
    try {
      final canAuthenticate = await _localAuth.canCheckBiometrics || await _localAuth.isDeviceSupported();
      if (!canAuthenticate) return false;

      final success = await _localAuth.authenticate(
        localizedReason: 'Подтвердите личность для входа',
        options: const AuthenticationOptions(
          stickyAuth: true,
          biometricOnly: true,
          useErrorDialogs: true,
        ),
      );

      if (success) {
        _isLocalAuthenticated = true;
        notifyListeners();
      }
      return success;
    } on PlatformException catch (e) {
      debugPrint("Biometric error: $e");
      return false;
    }
  }

  /// Включение или выключение использования биометрии.
  Future<void> setBiometricEnabled(bool enabled) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_biometricEnabledKey, enabled);
    _biometricEnabled = enabled;
    notifyListeners();
  }

  /// Обновление данных профиля пользователя (роль, статус демо, подписка).
  Future<void> updateProfile({
    bool? isAdmin,
    bool? isDemo,
    DateTime? subscriptionEndDate,
  }) async {
    final prefs = await SharedPreferences.getInstance();
    if (isAdmin != null) {
      _isAdmin = isAdmin;
      await prefs.setBool(_isAdminKey, isAdmin);
    }
    if (isDemo != null) {
      _isDemo = isDemo;
      await prefs.setBool(_isDemoKey, isDemo);
    }
    if (subscriptionEndDate != null) {
      _subscriptionEndDate = subscriptionEndDate;
      await prefs.setString(_subEndDateKey, subscriptionEndDate.toIso8601String());
    }
    notifyListeners();
  }

  /// Основной метод для сохранения токена после успешного входа или регистрации.
  /// Автоматически уведомляет [notifyListeners], обновляя UI на [AuthGate].
  Future<void> setToken(String token, {String? email, bool? isAdmin, String? pin}) async {
    final prefs = await SharedPreferences.getInstance();
    
    if (kIsWeb) {
      await prefs.setString(_tokenKey, token);
    } else {
      try {
        await _secureStorage.write(key: _tokenKey, value: token);
      } catch (e) {
        debugPrint("setToken: secureStorage write error: $e");
      }
    }

    _token = token;

    if (pin != null) {
      await setPin(pin);
    }

    if (email != null) {
      await prefs.setString(_emailKey, email);
      _userEmail = email;
    }
    if (isAdmin != null) {
      await prefs.setBool(_isAdminKey, isAdmin);
      _isAdmin = isAdmin;
    }

    _isAuthenticated = true;
    _isLocalAuthenticated = true;

    // Предлагаем включить биометрию только на мобильных при первом входе
    if (!kIsWeb && !_biometricEnabled) {
      _needsBiometricPrompt = true;
    }

    notifyListeners();
  }

  /// Скрытие диалога предложения биометрии.
  void dismissBiometricPrompt() {
    _needsBiometricPrompt = false;
    notifyListeners();
  }

  /// Вход в режим имитации (Impersonation): админ входит под видом другого пользователя.
  Future<void> enterImpersonation(String impersonationToken, String targetEmail) async {
    final prefs = await SharedPreferences.getInstance();
    
    _originalAdminToken = _token;
    if (kIsWeb) {
      await prefs.setString(_adminTokenBackupKey, _token!);
      await prefs.setString(_adminEmailBackupKey, _userEmail!);
    } else {
      await _secureStorage.write(key: _adminTokenBackupKey, value: _token!);
      await prefs.setString(_adminEmailBackupKey, _userEmail!);
    }

    _token = impersonationToken;
    _userEmail = targetEmail;
    _isAdmin = false;

    if (kIsWeb) {
      await prefs.setString(_tokenKey, impersonationToken);
      await prefs.setString(_emailKey, targetEmail);
      await prefs.setBool(_isAdminKey, false);
    } else {
      await _secureStorage.write(key: _tokenKey, value: impersonationToken);
      await prefs.setString(_emailKey, targetEmail);
      await prefs.setBool(_isAdminKey, false);
    }

    notifyListeners();
  }

  /// Выход из режима имитации и возврат к правам администратора.
  Future<void> stopImpersonating() async {
    if (_originalAdminToken == null) return;

    final prefs = await SharedPreferences.getInstance();
    final adminToken = _originalAdminToken!;
    final adminEmail = prefs.getString(_adminEmailBackupKey) ?? 'Admin';

    _token = adminToken;
    _userEmail = adminEmail;
    _originalAdminToken = null;
    _isAdmin = true;

    if (kIsWeb) {
      await prefs.setString(_tokenKey, adminToken);
      await prefs.setString(_emailKey, adminEmail);
      await prefs.remove(_adminTokenBackupKey);
      await prefs.remove(_adminEmailBackupKey);
      await prefs.setBool(_isAdminKey, true);
    } else {
      await _secureStorage.write(key: _tokenKey, value: adminToken);
      await prefs.setString(_emailKey, adminEmail);
      await _secureStorage.delete(key: _adminTokenBackupKey);
      await prefs.remove(_adminEmailBackupKey);
      await prefs.setBool(_isAdminKey, true);
    }

    notifyListeners();
  }

  /// Локальный выход: блокировка сессии (на мобильных) или полная очистка (на Web).
  Future<void> logout() async {
    debugPrint("AuthProvider: Locking session...");
    if (kIsWeb) {
      await clearAllData();
    } else {
      _isLocalAuthenticated = false;
      notifyListeners();
    }
  }

  /// Обработка ситуации, когда токен просрочен (ошибка 401).
  /// Удаляет только токен, заставляя пользователя ввести пароль заново.
  Future<void> handleSessionExpired() async {
    debugPrint("AuthProvider: Session expired, clearing token only...");
    if (kIsWeb) {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_tokenKey);
    } else {
      try {
        await _secureStorage.delete(key: _tokenKey);
      } catch (_) {}
    }
    _token = null;
    _isAuthenticated = false;
    _isLocalAuthenticated = false;
    notifyListeners();
  }

  /// Полная очистка всех данных пользователя и настроек из памяти и хранилища.
  Future<void> clearAllData() async {
    debugPrint("AuthProvider: Clearing all data...");
    if (!kIsWeb) {
      try {
        await _secureStorage.deleteAll();
      } catch (e) {
        debugPrint("clearAllData: secureStorage deleteAll error: $e");
      }
    }
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.clear();
    } catch (e) {
      debugPrint("clearAllData: SharedPreferences clear error: $e");
    }
    _token = null;
    _pinCode = null;
    _originalAdminToken = null;
    _isAuthenticated = false;
    _isLocalAuthenticated = false;
    notifyListeners();
  }
}

/// Виджет-контроллер, определяющий, какой экран показать пользователю в зависимости от состояния AuthProvider.
class AuthGate extends StatefulWidget {
  const AuthGate({super.key});

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> with WidgetsBindingObserver {
  bool _biometricAttempted = false; // Предотвращает зацикливание вызова биометрии
  bool _promptShown = false;        // Флаг показа предложения включить биометрию
  bool _updateChecked = false;      // Флаг проверки обновлений в текущей сессии

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      setState(() {
        _updateChecked = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final authProvider = context.watch<AuthProvider>();

    if (!authProvider.isAuthenticated) {
      _biometricAttempted = false;
      _promptShown = false;
      _updateChecked = false;
    }

    if (authProvider.isLoading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    // 1. Проверка авторизации на сервере (наличие токена)
    if (!authProvider.isAuthenticated) {
      return const LoginScreen();
    }

    // 2. Проверка локальной авторизации (ПИН или биометрия) для мобильных устройств
    if (!kIsWeb && !authProvider.isLocalAuthenticated) {
      if (!authProvider.hasPin) return const LoginScreen();

      if (authProvider.biometricEnabled && !_biometricAttempted) {
        _biometricAttempted = true;
        WidgetsBinding.instance.addPostFrameCallback((_) async {
          await authProvider.authenticateWithBiometrics();
        });
      }

      return PinScreen(
        onAuthenticated: () {
          setState(() => _biometricAttempted = false);
        },
      );
    }

    // 3. Основной контент приложения после прохождения всех проверок
    if (!kIsWeb) {
      // Фоновые проверки при входе
      if (!_updateChecked) {
        _updateChecked = true;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          final api = OzonApiClient(authProvider: authProvider);
          UpdateService(api).checkForUpdates(context);
        });
      }

      // Предложение включить биометрию, если она еще не настроена
      if (authProvider.needsBiometricPrompt && !_promptShown) {
        _promptShown = true;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          _showBiometricDialog(context, authProvider);
        });
      }
    }

    return const DashboardScreen();
  }

  /// Показ диалогового окна с предложением использовать биометрию.
  void _showBiometricDialog(BuildContext context, AuthProvider auth) {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => AlertDialog(
        title: const Row(
          children: [
            Icon(Icons.fingerprint, color: Colors.blue, size: 28),
            SizedBox(width: 12),
            Text('Вход по отпечатку'),
          ],
        ),
        content: const Text(
          'Хотите использовать биометрию для быстрого входа в приложение?',
        ),
        actions: [
          TextButton(
            onPressed: () {
              auth.dismissBiometricPrompt();
              Navigator.of(dialogContext).pop();
            },
            child: const Text('Позже'),
          ),
          FilledButton(
            onPressed: () async {
              await auth.setBiometricEnabled(true);
              auth.dismissBiometricPrompt();
              if (mounted) Navigator.of(dialogContext).pop();
            },
            child: const Text('Включить'),
          ),
        ],
      ),
    );
  }
}
