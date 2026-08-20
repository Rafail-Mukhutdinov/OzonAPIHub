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

/**
 * AuthProvider — центральный узел управления сессией пользователя.
 * Теперь поддерживает биометрическую аутентификацию и защищенное хранение токенов.
 */
class AuthProvider extends ChangeNotifier {
  static const String _tokenKey = 'jwt_token';
  static const String _emailKey = 'user_email';
  static const String _isAdminKey = 'is_admin';
  static const String _isDemoKey = 'is_demo';
  static const String _subEndDateKey = 'subscription_end_date';
  static const String _biometricEnabledKey = 'biometric_enabled';
  static const String _pinKey = 'user_pin';
  static const String _adminTokenBackupKey = 'admin_original_token';
  static const String _adminEmailBackupKey = 'admin_original_email';

  final _secureStorage = const FlutterSecureStorage();
  final _localAuth = LocalAuthentication();

  String? _token;
  String? _userEmail;
  String? _pinCode;
  String? _originalAdminToken; // Для возврата из Impersonation
  bool _isAdmin = false;
  bool _isDemo = false;
  DateTime? _subscriptionEndDate;
  bool _isAuthenticated = false;
  bool _isLocalAuthenticated = false;
  bool _isLoading = true;
  bool _biometricEnabled = false;
  bool _needsBiometricPrompt = false;

  // Геттеры
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

  Future<void> _initAuth() async {
    try {
      final prefs = await SharedPreferences.getInstance();

      if (kIsWeb) {
        // На Web используем обычные настройки (SecureStorage не работает без HTTPS)
        _token = prefs.getString(_tokenKey);
        _originalAdminToken = prefs.getString(_adminTokenBackupKey);
        _pinCode = null;
      } else {
        // На Mobile используем защищенное хранилище
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

      // Локальная переменная нужна для null-promotion: поля класса не
      // промоутятся автоматически, так как могут измениться между
      // проверкой и доступом. Это позволяет не использовать оператор '!'.
      final token = _token;
      _isAuthenticated = token != null && token.isNotEmpty;
      _isLocalAuthenticated = false;
      _isLoading = false;
      notifyListeners();
    } catch (e) {
      debugPrint("Init auth error: $e");
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> setPin(String pin) async {
    // На Web ПИН-код не используется (отключён через kIsWeb).
    if (kIsWeb) return;
    try {
      await _secureStorage.write(key: _pinKey, value: pin);
      _pinCode = pin;
    } catch (e) {
      debugPrint("setPin: secureStorage write error: $e");
      // Если не удалось сохранить, всё равно сохраняем в памяти на сессию
      _pinCode = pin;
    }
    notifyListeners();
  }

  bool verifyPin(String enteredPin) {
    if (_pinCode == enteredPin) {
      _isLocalAuthenticated = true;
      notifyListeners();
      return true;
    }
    return false;
  }

  Future<bool> authenticateWithBiometrics() async {
    // На Web биометрия недоступна: local_auth не имеет Web-плагина,
    // а вызовы бросают MissingPluginException, который не ловится
    // как PlatformException. Досрочный выход обязателен.
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

  Future<void> setBiometricEnabled(bool enabled) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_biometricEnabledKey, enabled);
    _biometricEnabled = enabled;
    notifyListeners();
  }

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

    // Если биометрия еще не включена, ставим флаг для показа запроса.
    // Запрос имеет смысл только на мобильных устройствах.
    if (!kIsWeb && !_biometricEnabled) {
      _needsBiometricPrompt = true;
    }

    notifyListeners();
  }

  /// Сброс флага запроса биометрии
  void dismissBiometricPrompt() {
    _needsBiometricPrompt = false;
    notifyListeners();
  }

  /// Вход в режим Impersonation (подмена токена с сохранением админского)
  Future<void> enterImpersonation(String impersonationToken, String targetEmail) async {
    final prefs = await SharedPreferences.getInstance();
    
    // Сохраняем текущий админский токен и email
    _originalAdminToken = _token;
    if (kIsWeb) {
      await prefs.setString(_adminTokenBackupKey, _token!);
      await prefs.setString(_adminEmailBackupKey, _userEmail!);
    } else {
      await _secureStorage.write(key: _adminTokenBackupKey, value: _token!);
      await prefs.setString(_adminEmailBackupKey, _userEmail!); // Email не секретный, можно в prefs
    }

    // Переключаемся на токен пользователя
    _token = impersonationToken;
    _userEmail = targetEmail;
    _isAdmin = false; // В режиме имитации мы как обычный юзер

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

  /// Выход из режима Impersonation (возврат к админскому токену)
  Future<void> stopImpersonating() async {
    if (_originalAdminToken == null) return;

    final prefs = await SharedPreferences.getInstance();
    final adminToken = _originalAdminToken!;
    final adminEmail = prefs.getString(_adminEmailBackupKey) ?? 'Admin';

    // Восстанавливаем админские данные
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

  Future<void> logout() async {
    debugPrint("AuthProvider: Locking session...");
    if (kIsWeb) {
      await clearAllData();
    } else {
      _isLocalAuthenticated = false;
      notifyListeners();
    }
  }

  /// Обработка истечения срока токена (401 ошибка)
  /// Мы удаляем токен, чтобы вызвать экран логина, но ОСТАВЛЯЕМ ПИН и Email
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

  Future<void> clearAllData() async {
    debugPrint("AuthProvider: Clearing all data...");
    // SecureStorage на Web не используется (требует HTTPS),
    // поэтому чистим его только на мобильных платформах.
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

class AuthGate extends StatefulWidget {
  const AuthGate({super.key});

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> with WidgetsBindingObserver {
  bool _biometricAttempted = false;
  bool _promptShown = false;
  bool _updateChecked = false;

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
    // При возврате приложения из фона сбрасываем флаг, чтобы проверить обновления снова
    if (state == AppLifecycleState.resumed) {
      setState(() {
        _updateChecked = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final authProvider = context.watch<AuthProvider>();

    // Сбрасываем флаги при выходе
    if (!authProvider.isAuthenticated) {
      _biometricAttempted = false;
      _promptShown = false;
      _updateChecked = false;
    }

    if (authProvider.isLoading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    // 1. Если нет токена — на логин
    if (!authProvider.isAuthenticated) {
      return const LoginScreen();
    }

    // 2. Если есть токен, но не прошли ПИН/Биометрию (только на мобильных)
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

    // 3. Всё Ок — Дашборд + запрос биометрии один раз (только на мобильных)
    if (!kIsWeb) {
      if (!_updateChecked) {
        _updateChecked = true;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          final api = OzonApiClient(authProvider: authProvider);
          UpdateService(api).checkForUpdates(context);
        });
      }

      if (authProvider.needsBiometricPrompt && !_promptShown) {
        _promptShown = true;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          _showBiometricDialog(context, authProvider);
        });
      }
    }

    return const DashboardScreen();
  }

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