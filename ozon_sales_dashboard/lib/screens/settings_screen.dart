import 'package:flutter/material.dart';
import 'package:dio/dio.dart';
import '../services/api.dart';
import 'package:shared_preferences/shared_preferences.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _formKey = GlobalKey<FormState>();
  final _clientIdController = TextEditingController();
  final _apiKeyController = TextEditingController();
  
  bool _isLoading = false;
  bool _isSaving = false;
  bool _ozonConfigured = false;
  String? _errorMessage;
  String? _successMessage;

  @override
  void initState() {
    super.initState();
    _loadUserInfo();
  }

  @override
  void dispose() {
    _clientIdController.dispose();
    _apiKeyController.dispose();
    super.dispose();
  }

  Future<void> _loadUserInfo() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final dio = Dio(BaseOptions(
        baseUrl: OzonApiClient.getDefaultBaseUrl(),
        headers: {'Content-Type': 'application/json'},
      ));

      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString('jwt_token');
      if (token == null) {
        throw Exception('Не авторизован');
      }

      final response = await dio.get(
        '/auth/me',
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );

      if (response.statusCode == 200) {
        setState(() {
          _ozonConfigured = response.data['ozon_configured'] ?? false;
        });
      }
    } catch (e) {
      setState(() {
        _errorMessage = 'Ошибка загрузки: $e';
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  Future<void> _saveCredentials() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }

    setState(() {
      _isSaving = true;
      _errorMessage = null;
      _successMessage = null;
    });

    try {
      final dio = Dio(BaseOptions(
        baseUrl: OzonApiClient.getDefaultBaseUrl(),
        headers: {'Content-Type': 'application/json'},
      ));

      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString('jwt_token');
      if (token == null) {
        throw Exception('Не авторизован');
      }

      final response = await dio.put(
        '/auth/me/ozon-credentials',
        data: {
          'client_id': _clientIdController.text.trim(),
          'api_key': _apiKeyController.text.trim(),
        },
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );

      if (response.statusCode == 200) {
        setState(() {
          _successMessage = 'Ozon API ключи успешно сохранены!';
          _ozonConfigured = true;
        });
        
        // Очистим поля после сохранения
        _clientIdController.clear();
        _apiKeyController.clear();
        
        // Скроем сообщение через 3 секунды
        Future.delayed(const Duration(seconds: 3), () {
          if (mounted) {
            setState(() {
              _successMessage = null;
            });
          }
        });
      }
    } on DioException catch (e) {
      String errorMsg = 'Ошибка сохранения';
      if (e.response?.statusCode == 401) {
        errorMsg = 'Сессия истекла. Войдите снова';
      } else if (e.response?.data != null) {
        errorMsg = e.response!.data['detail'] ?? errorMsg;
      }
      setState(() {
        _errorMessage = errorMsg;
      });
    } catch (e) {
      setState(() {
        _errorMessage = 'Неизвестная ошибка: $e';
      });
    } finally {
      setState(() {
        _isSaving = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Настройки'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              padding: const EdgeInsets.all(24.0),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Статус настройки
                    Card(
                      color: _ozonConfigured ? Colors.green.shade50 : Colors.orange.shade50,
                      child: Padding(
                        padding: const EdgeInsets.all(16.0),
                        child: Row(
                          children: [
                            Icon(
                              _ozonConfigured ? Icons.check_circle : Icons.warning,
                              color: _ozonConfigured ? Colors.green : Colors.orange,
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Text(
                                _ozonConfigured
                                    ? 'Ozon API настроен'
                                    : 'Требуется настройка Ozon API',
                                style: TextStyle(
                                  fontWeight: FontWeight.bold,
                                  color: _ozonConfigured ? Colors.green.shade900 : Colors.orange.shade900,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    
                    const SizedBox(height: 32),
                    
                    // Заголовок
                    const Text(
                      'Ozon API ключи',
                      style: TextStyle(
                        fontSize: 24,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    
                    const SizedBox(height: 8),
                    
                    const Text(
                      'Для загрузки данных о заказах необходимо указать API ключи из личного кабинета Ozon Seller.',
                      style: TextStyle(color: Colors.grey),
                    ),
                    
                    const SizedBox(height: 24),
                    
                    // Инструкция
                    Card(
                      color: Colors.blue.shade50,
                      child: Padding(
                        padding: const EdgeInsets.all(16.0),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Icon(Icons.info, color: Colors.blue.shade700),
                                const SizedBox(width: 8),
                                Text(
                                  'Как получить API ключи?',
                                  style: TextStyle(
                                    fontWeight: FontWeight.bold,
                                    color: Colors.blue.shade900,
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 12),
                            const Text('1. Войдите в личный кабинет Ozon Seller'),
                            const Text('2. Настройки → API ключи'),
                            const Text('3. Создайте новый API ключ'),
                            const Text('4. Скопируйте Client-Id и Api-Key'),
                          ],
                        ),
                      ),
                    ),
                    
                    const SizedBox(height: 32),
                    
                    // Поле Client ID
                    TextFormField(
                      controller: _clientIdController,
                      decoration: const InputDecoration(
                        labelText: 'Client ID',
                        hintText: 'Введите Client ID',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.key),
                      ),
                      validator: (value) {
                        if (value == null || value.trim().isEmpty) {
                          return 'Введите Client ID';
                        }
                        return null;
                      },
                    ),
                    
                    const SizedBox(height: 16),
                    
                    // Поле API Key
                    TextFormField(
                      controller: _apiKeyController,
                      decoration: const InputDecoration(
                        labelText: 'API Key',
                        hintText: 'Введите API Key',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.vpn_key),
                      ),
                      obscureText: true,
                      validator: (value) {
                        if (value == null || value.trim().isEmpty) {
                          return 'Введите API Key';
                        }
                        return null;
                      },
                    ),
                    
                    const SizedBox(height: 24),
                    
                    // Сообщения об ошибках/успехе
                    if (_errorMessage != null)
                      Container(
                        padding: const EdgeInsets.all(12),
                        margin: const EdgeInsets.only(bottom: 16),
                        decoration: BoxDecoration(
                          color: Colors.red.shade50,
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: Colors.red.shade200),
                        ),
                        child: Row(
                          children: [
                            Icon(Icons.error, color: Colors.red.shade700),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Text(
                                _errorMessage!,
                                style: TextStyle(color: Colors.red.shade900),
                              ),
                            ),
                          ],
                        ),
                      ),
                    
                    if (_successMessage != null)
                      Container(
                        padding: const EdgeInsets.all(12),
                        margin: const EdgeInsets.only(bottom: 16),
                        decoration: BoxDecoration(
                          color: Colors.green.shade50,
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: Colors.green.shade200),
                        ),
                        child: Row(
                          children: [
                            Icon(Icons.check_circle, color: Colors.green.shade700),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Text(
                                _successMessage!,
                                style: TextStyle(color: Colors.green.shade900),
                              ),
                            ),
                          ],
                        ),
                      ),
                    
                    // Кнопка сохранения
                    SizedBox(
                      width: double.infinity,
                      height: 50,
                      child: ElevatedButton(
                        onPressed: _isSaving ? null : _saveCredentials,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.blue,
                          foregroundColor: Colors.white,
                        ),
                        child: _isSaving
                            ? const SizedBox(
                                height: 20,
                                width: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                                ),
                              )
                            : const Text(
                                'Сохранить ключи',
                                style: TextStyle(fontSize: 16),
                              ),
                      ),
                    ),
                    
                    const SizedBox(height: 16),
                    
                    // Предупреждение о безопасности
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.grey.shade100,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Row(
                        children: [
                          Icon(Icons.lock, color: Colors.grey.shade700, size: 20),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Text(
                              'Ваши ключи хранятся в зашифрованном виде',
                              style: TextStyle(
                                fontSize: 12,
                                color: Colors.grey.shade700,
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
    );
  }
}
