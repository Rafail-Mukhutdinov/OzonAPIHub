import 'package:flutter/material.dart';
import '../services/auth_service.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import 'dashboard_screen.dart';

class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();
  final _pinController = TextEditingController(); // Для ПИН-кода
  late final AuthService _authService;
  
  bool _isLoading = false;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _authService = AuthService();
  }

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    _confirmPasswordController.dispose();
    _pinController.dispose();
    super.dispose();
  }

  Future<void> _handleRegister() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final email = _emailController.text.trim();
      final pin = _pinController.text.trim();
      final token = await _authService.register(
        email,
        _passwordController.text,
        _confirmPasswordController.text,
      );

      if (mounted) {
        // Обновляем состояние провайдера, передавая ПИН
        await Provider.of<AuthProvider>(context, listen: false).setToken(
          token, 
          email: email,
          pin: pin,
        );

        // Успешная регистрация - AuthGate сам переключит экран на Dashboard
      }
    } catch (e) {
      setState(() {
        _errorMessage = e.toString().replaceFirst('Exception: ', '');
      });
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Регистрация'),
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24.0),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 400),
            child: Card(
              elevation: 4,
              child: Padding(
                padding: const EdgeInsets.all(32.0),
                child: Form(
                  key: _formKey,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Icon(
                        Icons.person_add,
                        size: 80,
                        color: Theme.of(context).primaryColor,
                      ),
                      const SizedBox(height: 16),
                      Text(
                        'Создание аккаунта',
                        style: Theme.of(context).textTheme.headlineSmall,
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 32),
                      
                      // Email поле
                      TextFormField(
                        controller: _emailController,
                        decoration: const InputDecoration(
                          labelText: 'Email',
                          border: OutlineInputBorder(),
                          prefixIcon: Icon(Icons.email),
                        ),
                        keyboardType: TextInputType.emailAddress,
                        autofillHints: const [AutofillHints.email],
                        validator: (value) {
                          if (value == null || value.isEmpty) {
                            return 'Введите email';
                          }
                          if (!value.contains('@')) {
                            return 'Введите корректный email';
                          }
                          return null;
                        },
                      ),
                      const SizedBox(height: 16),
                      
                      // Password поле
                      TextFormField(
                        controller: _passwordController,
                        decoration: const InputDecoration(
                          labelText: 'Пароль',
                          border: OutlineInputBorder(),
                          prefixIcon: Icon(Icons.lock),
                          helperText: 'Минимум 6 символов',
                        ),
                        obscureText: true,
                        autofillHints: const [AutofillHints.newPassword],
                        validator: (value) {
                          if (value == null || value.isEmpty) {
                            return 'Введите пароль';
                          }
                          if (value.length < 6) {
                            return 'Пароль должен быть не менее 6 символов';
                          }
                          return null;
                        },
                      ),
                      const SizedBox(height: 16),
                      
                      // Confirm Password поле
                      TextFormField(
                        controller: _confirmPasswordController,
                        decoration: const InputDecoration(
                          labelText: 'Подтвердите пароль',
                          border: OutlineInputBorder(),
                          prefixIcon: Icon(Icons.lock_outline),
                        ),
                        obscureText: true,
                        autofillHints: const [AutofillHints.newPassword],
                        validator: (value) {
                          if (value == null || value.isEmpty) {
                            return 'Подтвердите пароль';
                          }
                          if (value != _passwordController.text) {
                            return 'Пароли не совпадают';
                          }
                          return null;
                        },
                      ),
                      const SizedBox(height: 16),

                      // НОВОЕ: ПИН-код поле
                      TextFormField(
                        controller: _pinController,
                        decoration: const InputDecoration(
                          labelText: 'Создайте ПИН-код (4 цифры)',
                          border: OutlineInputBorder(),
                          prefixIcon: Icon(Icons.dialpad),
                          helperText: 'Для быстрого входа в приложение',
                        ),
                        keyboardType: TextInputType.number,
                        maxLength: 4,
                        obscureText: true,
                        validator: (value) {
                          if (value == null || value.isEmpty) {
                            return 'Введите ПИН-код';
                          }
                          if (value.length != 4) {
                            return 'Ровно 4 цифры';
                          }
                          if (int.tryParse(value) == null) {
                            return 'Только цифры';
                          }
                          return null;
                        },
                      ),
                      const SizedBox(height: 24),
                      
                      // Сообщение об ошибке
                      if (_errorMessage != null)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 16),
                          child: Text(
                            _errorMessage!,
                            style: const TextStyle(color: Colors.red),
                            textAlign: TextAlign.center,
                          ),
                        ),
                      
                      // Кнопка регистрации
                      FilledButton(
                        onPressed: _isLoading ? null : _handleRegister,
                        child: _isLoading
                            ? const SizedBox(
                                height: 20,
                                width: 20,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Text('Создать аккаунт'),
                      ),
                      const SizedBox(height: 16),
                      
                      // Информация о пробном периоде
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Theme.of(context).primaryColor.withOpacity(0.1),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Row(
                          children: [
                            Icon(Icons.info_outline, color: Theme.of(context).primaryColor),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                'Пробный период: 30 дней',
                                style: TextStyle(
                                  color: Theme.of(context).primaryColor,
                                  fontSize: 12,
                                ),
                              ),
                            ),
                          ],
                        ),
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
