import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart'; // Для проверки kIsWeb
import '../utils/platform_nav.dart'; // Условный импорт для навигации
import '../services/auth_service.dart';
import '../services/api.dart';
import 'register_screen.dart';

import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';

/// LoginScreen — экран входа в приложение.
/// Обеспечивает ввод учетных данных пользователя, их валидацию и процесс авторизации через [AuthService].
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  // Глобальный ключ для управления состоянием и валидацией формы ввода
  final _formKey = GlobalKey<FormState>();
  
  // Контроллеры текстовых полей для сбора данных
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _pinController = TextEditingController(); // Используется только на мобильных устройствах
  
  late final AuthService _authService;
  
  bool _isLoading = false; // Флаг активности сетевого запроса
  String? _errorMessage;   // Хранит текст ошибки от сервера для отображения пользователю

  @override
  void initState() {
    super.initState();
    _authService = AuthService();
  }

  @override
  void dispose() {
    // Освобождение ресурсов контроллеров для предотвращения утечек памяти
    _emailController.dispose();
    _passwordController.dispose();
    _pinController.dispose();
    super.dispose();
  }

  /// Логика выполнения входа в систему.
  Future<void> _handleLogin() async {
    // 1. Запуск встроенной валидации всех полей в [Form]
    if (!_formKey.currentState!.validate()) {
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final email = _emailController.text.trim();
      final pin = kIsWeb ? null : _pinController.text.trim();

      // 2. Запрос к API для получения JWT токена
      final token = await _authService.login(
        email,
        _passwordController.text,
      );

      if (mounted) {
        final authProvider = Provider.of<AuthProvider>(context, listen: false);
        
        // 3. Сохранение токена и инициализация локальной сессии (включая ПИН-код)
        // Это действие через notifyListeners() переключит AuthGate на DashboardScreen
        await authProvider.setToken(token, email: email, pin: pin);

        // 4. Попытка загрузки расширенных данных профиля (роль, подписка)
        try {
          final profileData = await OzonApiClient().getProfile();
          final bool isAdmin = profileData['is_admin'] ?? false;
          final bool isDemo = profileData['is_demo'] ?? false;
          final String? subEndStr = profileData['subscription_end_date'];
          DateTime? subEndDate;
          if (subEndStr != null) {
            subEndDate = DateTime.tryParse(subEndStr);
          }
          
          await authProvider.updateProfile(
            isAdmin: isAdmin,
            isDemo: isDemo,
            subscriptionEndDate: subEndDate,
          );
        } catch (e) {
          debugPrint('Profile fetch error: $e');
          // Ошибка загрузки профиля не блокирует вход, если токен валиден
        }
      }
    } catch (e) {
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
            // Ограничение ширины карточки для удобства на десктопных версиях
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
                        'Seller Hub',
                        style: Theme.of(context).textTheme.headlineSmall,
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 8),
                      const Text('Вход в систему', textAlign: TextAlign.center),
                      const SizedBox(height: 32),
                      
                      if (kIsWeb)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 24.0),
                          child: OutlinedButton.icon(
                            onPressed: () => goToLanding(),
                            icon: const Icon(Icons.arrow_back),
                            label: const Text('На главную страницу'),
                            style: OutlinedButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 12)),
                          ),
                        ),

                      // Поле ввода Email с валидацией формата
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
                      
                      // Поле ввода Пароля
                      TextFormField(
                        controller: _passwordController,
                        decoration: const InputDecoration(
                          labelText: 'Пароль',
                          border: OutlineInputBorder(),
                          prefixIcon: Icon(Icons.lock),
                        ),
                        obscureText: true,
                        validator: (value) {
                          if (value == null || value.isEmpty) return 'Введите пароль';
                          return null;
                        },
                      ),
                      const SizedBox(height: 16),

                      // Секция ПИН-кода (только для мобильных устройств)
                      if (!kIsWeb) ...[
                        TextFormField(
                          controller: _pinController,
                          decoration: const InputDecoration(
                            labelText: 'ПИН-код для этого устройства',
                            border: OutlineInputBorder(),
                            prefixIcon: Icon(Icons.dialpad),
                            helperText: 'Цифры будут использоваться для быстрого входа',
                          ),
                          keyboardType: TextInputType.number,
                          maxLength: 4,
                          obscureText: true,
                          validator: (value) {
                            if (kIsWeb) return null;
                            if (value == null || value.isEmpty) return 'Придумайте ПИН-код';
                            if (value.length != 4) return 'Нужно 4 цифры';
                            return null;
                          },
                        ),
                        const SizedBox(height: 24),
                      ],
                      
                      if (_errorMessage != null)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 16),
                          child: Text(_errorMessage!, style: const TextStyle(color: Colors.red), textAlign: TextAlign.center),
                        ),
                      
                      // Кнопка входа с индикацией загрузки
                      FilledButton(
                        onPressed: _isLoading ? null : _handleLogin,
                        child: _isLoading
                            ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                            : const Text('Войти'),
                      ),
                      const SizedBox(height: 16),
                      
                      // Переход на экран регистрации
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
