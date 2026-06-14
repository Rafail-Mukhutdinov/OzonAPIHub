import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../screens/login_screen.dart';
import '../screens/dashboard_screen.dart';

/**
 * AuthProvider — центральный узел управления сессией пользователя.
 * Использует ChangeNotifier для уведомления UI об изменениях (вход/выход).
 * Токен хранится в SharedPreferences (аналог LocalStorage в вебе).
 */
class AuthProvider extends ChangeNotifier {
  static const String _tokenKey = 'jwt_token';
  String? _token;
  bool _isAuthenticated = false;
  bool _isLoading = true;

  // Геттеры для доступа из виджетов
  bool get isAuthenticated => _isAuthenticated;
  bool get isLoading => _isLoading;
  String? get token => _token;

  AuthProvider() {
    _initAuth(); // Проверяем сессию при запуске приложения
  }

  /// Проверяет, сохранен ли токен в памяти устройства.
  Future<void> _initAuth() async {
    final prefs = await SharedPreferences.getInstance();
    _token = prefs.getString(_tokenKey);
    // Считаем авторизованным, если токен есть и он не пустой
    _isAuthenticated = _token != null && _token!.isNotEmpty;
    _isLoading = false;
    notifyListeners(); // Перерисовываем UI
  }

  /// Метод для сохранения токена после успешного входа (Login/Register).
  Future<void> setToken(String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, token);
    _token = token;
    _isAuthenticated = true;
    notifyListeners();
  }

  /// Полный выход из системы с очисткой памяти.
  Future<void> logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
    _token = null;
    _isAuthenticated = false;
    notifyListeners();
  }

  /// Принудительный разлогин (используется API-клиентом при ошибке 401).
  void forceLogout() {
    logout();
  }
}

/**
 * AuthGate — "умный" виджет, который решает, какой экран показать пользователю.
 * Если токен есть — Dashboard, если нет — Login.
 */
class AuthGate extends StatelessWidget {
  const AuthGate({super.key});

  @override
  Widget build(BuildContext context) {
    // Слушаем изменения в AuthProvider
    final authProvider = context.watch<AuthProvider>();

    // Пока идет проверка токена в SharedPreferences, показываем спиннер
    if (authProvider.isLoading) {
      return const Scaffold(
        body: Center(
          child: CircularProgressIndicator(),
        ),
      );
    }

    // Редирект в зависимости от статуса
    return authProvider.isAuthenticated 
        ? const DashboardScreen() 
        : const LoginScreen();
  }
}
