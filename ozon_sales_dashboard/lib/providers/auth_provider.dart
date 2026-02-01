import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../screens/login_screen.dart';
import '../screens/dashboard_screen.dart';

/// Провайдер для управления состоянием авторизации
class AuthProvider extends ChangeNotifier {
  static const String _tokenKey = 'jwt_token';
  String? _token;
  bool _isAuthenticated = false;
  bool _isLoading = true;

  bool get isAuthenticated => _isAuthenticated;
  bool get isLoading => _isLoading;
  String? get token => _token;

  AuthProvider() {
    _initAuth();
  }

  /// Инициализация - проверка наличия токена
  Future<void> _initAuth() async {
    final prefs = await SharedPreferences.getInstance();
    _token = prefs.getString(_tokenKey);
    _isAuthenticated = _token != null && _token!.isNotEmpty;
    _isLoading = false;
    notifyListeners();
  }

  /// Сохранить токен после успешного входа
  Future<void> setToken(String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, token);
    _token = token;
    _isAuthenticated = true;
    notifyListeners();
  }

  /// Выход - удаление токена
  Future<void> logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
    _token = null;
    _isAuthenticated = false;
    notifyListeners();
  }

  /// Принудительный выход при 401 ошибке
  void forceLogout() {
    logout();
  }
}

/// Widget-обертка для автоматического перенаправления
class AuthGate extends StatelessWidget {
  const AuthGate({super.key});

  @override
  Widget build(BuildContext context) {
    final authProvider = context.watch<AuthProvider>();

    if (authProvider.isLoading) {
      return const Scaffold(
        body: Center(
          child: CircularProgressIndicator(),
        ),
      );
    }

    return authProvider.isAuthenticated 
        ? const DashboardScreen() 
        : const LoginScreen();
  }
}
