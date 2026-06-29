import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:local_auth/local_auth.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../screens/login_screen.dart';
import '../screens/dashboard_screen.dart';

/**
 * AuthProvider — центральный узел управления сессией пользователя.
 * Теперь поддерживает биометрическую аутентификацию и защищенное хранение токенов.
 */
class AuthProvider extends ChangeNotifier {
  static const String _tokenKey = 'jwt_token';
  static const String _emailKey = 'user_email';
  static const String _isAdminKey = 'is_admin';
  static const String _biometricEnabledKey = 'biometric_enabled';

  final _secureStorage = const FlutterSecureStorage();
  final _localAuth = LocalAuthentication();

  String? _token;
  String? _userEmail;
  bool _isAdmin = false;
  bool _isAuthenticated = false;
  bool _isLoading = true;
  bool _biometricEnabled = false;

  // Геттеры
  bool get isAuthenticated => _isAuthenticated;
  bool get isLoading => _isLoading;
  String? get token => _token;
  String? get userEmail => _userEmail;
  bool get isAdmin => _isAdmin;
  bool get biometricEnabled => _biometricEnabled;

  AuthProvider() {
    _initAuth();
  }

  /// Инициализация: проверяем наличие токена и настройки биометрии.
  Future<void> _initAuth() async {
    final prefs = await SharedPreferences.getInstance();
    
    // Токен читаем из защищенного хранилища
    _token = await _secureStorage.read(key: _tokenKey);
    
    // Остальное из обычных настроек
    _userEmail = prefs.getString(_emailKey);
    _isAdmin = prefs.getBool(_isAdminKey) ?? false;
    _biometricEnabled = prefs.getBool(_biometricEnabledKey) ?? false;

    _isAuthenticated = _token != null && _token!.isNotEmpty;
    _isLoading = false;
    notifyListeners();
  }

  /// Попытка входа по отпечатку пальца/FaceID
  Future<bool> authenticateWithBiometrics() async {
    if (!_biometricEnabled) {
      debugPrint("Biometrics not enabled in settings");
      return false;
    }

    try {
      final canAuthenticateWithBiometrics = await _localAuth.canCheckBiometrics;
      final canAuthenticate = canAuthenticateWithBiometrics || await _localAuth.isDeviceSupported();

      debugPrint("Device support: $canAuthenticate, Can check biometrics: $canAuthenticateWithBiometrics");

      if (!canAuthenticate) {
        debugPrint("Biometrics not supported or not set up on this device");
        return false;
      }

      final didAuthenticate = await _localAuth.authenticate(
        localizedReason: 'Пожалуйста, подтвердите личность для входа в OzonAPIHub',
        options: const AuthenticationOptions(
          stickyAuth: true,
          biometricOnly: true,
          useErrorDialogs: true, // Показывать системные ошибки (например, если палец не привязан)
        ),
      );

      debugPrint("Authentication result: $didAuthenticate");
      return didAuthenticate;
    } on PlatformException catch (e) {
      debugPrint("Biometric error: code=${e.code}, message=${e.message}");
      return false;
    }
  }

  /// Включение/выключение биометрии в настройках
  Future<void> setBiometricEnabled(bool enabled) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_biometricEnabledKey, enabled);
    _biometricEnabled = enabled;
    notifyListeners();
  }

  /// Сохранение сессии после логина
  Future<void> setToken(String token, {String? email, bool? isAdmin}) async {
    await _secureStorage.write(key: _tokenKey, value: token);
    _token = token;

    final prefs = await SharedPreferences.getInstance();
    if (email != null) {
      await prefs.setString(_emailKey, email);
      _userEmail = email;
    }
    if (isAdmin != null) {
      await prefs.setBool(_isAdminKey, isAdmin);
      _isAdmin = isAdmin;
    }

    _isAuthenticated = true;
    notifyListeners();
  }

  /// Выход
  Future<void> logout() async {
    await _secureStorage.delete(key: _tokenKey);
    _token = null;

    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_emailKey);
    await prefs.remove(_isAdminKey);
    // Настройку биометрии не удаляем, чтобы пользователь мог зайти снова, если захочет

    _isAuthenticated = false;
    notifyListeners();
  }

  void forceLogout() {
    logout();
  }
}

class AuthGate extends StatefulWidget {
  const AuthGate({super.key});

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  bool _biometricAttempted = false;

  @override
  Widget build(BuildContext context) {
    final authProvider = context.watch<AuthProvider>();

    if (authProvider.isLoading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    // Если токен есть и включена биометрия, пробуем её вызвать ОДИН РАЗ при загрузке
    if (authProvider.isAuthenticated && authProvider.biometricEnabled && !_biometricAttempted) {
      _biometricAttempted = true;
      
      // Вызываем после завершения кадра
      WidgetsBinding.instance.addPostFrameCallback((_) async {
        final success = await authProvider.authenticateWithBiometrics();
        if (!success) {
          // Если биометрия не прошла (отмена), можно оставить на экране входа или просить пароль
          // В данном случае, если токен есть, мы всё равно пустим, но в идеале
          // здесь должна быть логика блокировки экрана до ввода PIN или отпечатка.
          // Для MVP: если отмена — разлогиниваем для безопасности.
          authProvider.logout();
        }
      });
      
      return const Scaffold(
        body: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.fingerprint, size: 64, color: Colors.blue),
              SizedBox(height: 16),
              Text("Требуется подтверждение"),
            ],
          ),
        ),
      );
    }

    return authProvider.isAuthenticated 
        ? const DashboardScreen() 
        : const LoginScreen();
  }
}
