import 'package:flutter/material.dart';
import '../services/auth_service.dart';
import '../services/api.dart';
import 'register_screen.dart';
import 'dashboard_screen.dart';

import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';

/**
 * LoginScreen — экран входа в приложение.
 * Реализует валидацию полей ввода и взаимодействие с AuthService.
 */
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  // Глобальный ключ для управления состоянием и валидацией формы
  final _formKey = GlobalKey<FormState>();
  
  // Контроллеры для извлечения текста из полей ввода
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  
  late final AuthService _authService;
  
  bool _isLoading = false; // Флаг процесса запроса к серверу
  String? _errorMessage;   // Текст ошибки от бэкенда

  @override
  void initState() {
    super.initState();
    _authService = AuthService();
  }

  @override
  void dispose() {
    // Обязательно освобождаем ресурсы контроллеров при закрытии экрана
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  /// Логика обработки нажатия кнопки "Войти"
  Future<void> _handleLogin() async {
    // Запуск валидации всех полей в Form
    if (!_formKey.currentState!.validate()) {
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final email = _emailController.text.trim();
      // Отправка запроса на сервер
      final token = await _authService.login(
        email,
        _passwordController.text,
      );

      if (mounted) {
        // Сначала сохраняем токен в провайдере
        final authProvider = Provider.of<AuthProvider>(context, listen: false);
        await authProvider.setToken(token, email: email);

        // Теперь, когда токен установлен в интерцепторах Dio, запрашиваем профиль
        try {
          final profileData = await OzonApiClient().getProfile();
          final bool isAdmin = profileData['is_admin'] ?? false;
          
          // Обновляем информацию об админе в провайдере
          await authProvider.setToken(token, email: email, isAdmin: isAdmin);
        } catch (profileError) {
          debugPrint('Ошибка получения профиля при входе: $profileError');
        }

        // Успешный вход - заменяем текущий экран на Dashboard
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (_) => const DashboardScreen()),
        );
      }
    } catch (e) {
      // Обработка ошибок (неверный пароль, отсутствие сети и т.д.)
      setState(() {
        _errorMessage = e.toString().replaceFirst('Exception: ', '');
      });
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24.0),
          child: ConstrainedBox(
            // Ограничение ширины формы для удобства на десктопе/планшете
            constraints: const BoxConstraints(maxWidth: 400),
            child: Card(
              elevation: 4,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
              child: Padding(
                padding: const EdgeInsets.all(32.0),
                child: Form(
                  key: _formKey,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Icon(Icons.account_circle, size: 80, color: Theme.of(context).primaryColor),
                      const SizedBox(height: 16),
                      Text(
                        'Sales Hub',
                        style: Theme.of(context).textTheme.headlineSmall,
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 8),
                      const Text('Вход в систему', textAlign: TextAlign.center),
                      const SizedBox(height: 32),
                      
                      // Поле ввода Email
                      TextFormField(
                        controller: _emailController,
                        decoration: const InputDecoration(
                          labelText: 'Email',
                          border: OutlineInputBorder(),
                          prefixIcon: Icon(Icons.email),
                        ),
                        keyboardType: TextInputType.emailAddress,
                        validator: (value) {
                          if (value == null || value.isEmpty) return 'Введите email';
                          if (!value.contains('@')) return 'Некорректный формат email';
                          return null;
                        },
                      ),
                      const SizedBox(height: 16),
                      
                      // Поле ввода пароля
                      TextFormField(
                        controller: _passwordController,
                        decoration: const InputDecoration(
                          labelText: 'Пароль',
                          border: OutlineInputBorder(),
                          prefixIcon: Icon(Icons.lock),
                        ),
                        obscureText: true, // Скрывает вводимые символы
                        validator: (value) {
                          if (value == null || value.isEmpty) return 'Введите пароль';
                          return null;
                        },
                      ),
                      const SizedBox(height: 24),
                      
                      if (_errorMessage != null)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 16),
                          child: Text(_errorMessage!, style: const TextStyle(color: Colors.red), textAlign: TextAlign.center),
                        ),
                      
                      FilledButton(
                        onPressed: _isLoading ? null : _handleLogin,
                        child: _isLoading
                            ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                            : const Text('Войти'),
                      ),
                      const SizedBox(height: 16),
                      
                      TextButton(
                        onPressed: _isLoading ? null : () {
                          Navigator.of(context).push(MaterialPageRoute(builder: (_) => const RegisterScreen()));
                        },
                        child: const Text('Нет аккаунта? Зарегистрироваться'),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
