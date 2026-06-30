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

/**
 * AuthProvider — центральный узел управления сессией пользователя.
 * Теперь поддерживает биометрическую аутентификацию и защищенное хранение токенов.
 */
class AuthProvider extends ChangeNotifier {
  static const String _tokenKey = 'jwt_token';
  static const String _emailKey = 'user_email';
  static const String _isAdminKey = 'is_admin';
  static const String _biometricEnabledKey = 'biometric_enabled';
  static const String _pinKey = 'user_pin';

  final _secureStorage = const FlutterSecureStorage();
  final _localAuth = LocalAuthentication();

  String? _token;
  String? _userEmail;
  String? _pinCode;
  bool _isAdmin = false;
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
  String? get token => _token;
  String? get userEmail => _userEmail;
  bool get isAdmin => _isAdmin;
  bool get biometricEnabled => _biometricEnabled;
  bool get hasPin => _pinCode != null && (_pinCode?.length ?? 0) == 4;

  AuthProvider() {
    _initAuth();
  }

  Future<void> _initAuth() async {
    try {
      final prefs = await SharedPreferences.getInstance();

      if (kIsWeb) {
        // На Web используем обычные настройки (SecureStorage не работает без HTTPS)
        _token = prefs.getString(_tokenKey);
        _pinCode = null;
      } else {
        // На Mobile используем защищенное хранилище
        try {
          _token = await _secureStorage.read(key: _tokenKey);
          _pinCode = await _secureStorage.read(key: _pinKey);
        } catch (e) {
          debugPrint("_initAuth: secureStorage error: $e");
        }
      }

      _userEmail = prefs.getString(_emailKey);
      _isAdmin = prefs.getBool(_isAdminKey) ?? false;
      _biometricEnabled = prefs.getBool(_biometricEnabledKey) ?? false;

      _isAuthenticated = _token != null && _token!.isNotEmpty;
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

    // Если биометрия еще не включена, ставим флаг для показа запроса
    if (!_biometricEnabled) {
      _needsBiometricPrompt = true;
    }

    notifyListeners();
  }

  /// Сброс флага запроса биометрии
  void dismissBiometricPrompt() {
    _needsBiometricPrompt = false;
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

  Future<void> clearAllData() async {
    debugPrint("AuthProvider: Clearing all data...");
    try {
      await _secureStorage.deleteAll();
    } catch (e) {
      debugPrint("clearAllData: secureStorage deleteAll error: $e");
    }
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.clear();
    } catch (e) {
      debugPrint("clearAllData: SharedPreferences clear error: $e");
    }
    _token = null;
    _pinCode = null;
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

class _AuthGateState extends State<AuthGate> {
  bool _biometricAttempted = false;
  bool _promptShown = false;

  @override
  Widget build(BuildContext context) {
    final authProvider = context.watch<AuthProvider>();

    // Сбрасываем флаги при выходе
    if (!authProvider.isAuthenticated) {
      _biometricAttempted = false;
      _promptShown = false;
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
    if (!kIsWeb && authProvider.needsBiometricPrompt && !_promptShown) {
      _promptShown = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _showBiometricDialog(context, authProvider);
      });
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