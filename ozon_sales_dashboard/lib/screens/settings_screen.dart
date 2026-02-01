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
  bool _isLoading = false;
  List<Map<String, dynamic>> _credentials = [];
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _loadCredentials();
  }

  Future<void> _loadCredentials() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString('jwt_token');
      
      if (token == null) {
        throw Exception('Не авторизован');
      }

      final dio = Dio(BaseOptions(
        baseUrl: OzonApiClient.getDefaultBaseUrl(),
        headers: {'Content-Type': 'application/json'},
      ));

      final response = await dio.get(
        '/auth/me/ozon-credentials',
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );

      if (response.statusCode == 200) {
        setState(() {
          _credentials = List<Map<String, dynamic>>.from(
            response.data['credentials'] ?? []
          );
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

  Future<void> _addCredential() async {
    final result = await showDialog<Map<String, String>>(
      context: context,
      builder: (context) => _AddCredentialDialog(),
    );

    if (result == null) return;

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString('jwt_token');

      final dio = Dio(BaseOptions(
        baseUrl: OzonApiClient.getDefaultBaseUrl(),
        headers: {'Content-Type': 'application/json'},
      ));

      await dio.post(
        '/auth/me/ozon-credentials',
        data: {
          'name': result['name'],
          'client_id': result['client_id'],
          'api_key': result['api_key'],
        },
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Ключи успешно добавлены'),
            backgroundColor: Colors.green,
          ),
        );
        _loadCredentials();
      }
    } catch (e) {
      setState(() {
        _errorMessage = 'Ошибка добавления: $e';
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  Future<void> _activateCredential(int id) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString('jwt_token');

      final dio = Dio(BaseOptions(
        baseUrl: OzonApiClient.getDefaultBaseUrl(),
      ));

      await dio.put(
        '/auth/me/ozon-credentials/$id/activate',
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Ключ активирован')),
        );
        _loadCredentials();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Ошибка: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }

  Future<void> _deleteCredential(int id, String name) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Удаление ключей'),
        content: Text('Удалить набор "$name"?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style: FilledButton.styleFrom(backgroundColor: Colors.red),
            child: const Text('Удалить'),
          ),
        ],
      ),
    );

    if (confirmed != true) return;

    try {
      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString('jwt_token');

      final dio = Dio(BaseOptions(
        baseUrl: OzonApiClient.getDefaultBaseUrl(),
      ));

      await dio.delete(
        '/auth/me/ozon-credentials/$id',
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Ключ удален')),
        );
        _loadCredentials();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Ошибка: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Настройки API ключей'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                if (_errorMessage != null)
                  Container(
                    padding: const EdgeInsets.all(16),
                    color: Colors.red.shade50,
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
                
                Padding(
                  padding: const EdgeInsets.all(16),
                  child: Card(
                    color: Colors.blue.shade50,
                    child: Padding(
                      padding: const EdgeInsets.all(16),
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
                ),

                Expanded(
                  child: _credentials.isEmpty
                      ? Center(
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(Icons.vpn_key_off, size: 64, color: Colors.grey.shade400),
                              const SizedBox(height: 16),
                              Text(
                                'Нет сохраненных ключей',
                                style: TextStyle(
                                  fontSize: 18,
                                  color: Colors.grey.shade600,
                                ),
                              ),
                              const SizedBox(height: 8),
                              Text(
                                'Нажмите + чтобы добавить',
                                style: TextStyle(color: Colors.grey.shade500),
                              ),
                            ],
                          ),
                        )
                      : ListView.builder(
                          itemCount: _credentials.length,
                          itemBuilder: (context, index) {
                            final cred = _credentials[index];
                            final isActive = cred['is_active'] ?? false;
                            
                            return Card(
                              margin: const EdgeInsets.symmetric(
                                horizontal: 16,
                                vertical: 8,
                              ),
                              color: isActive ? Colors.green.shade50 : null,
                              child: ListTile(
                                leading: Icon(
                                  isActive ? Icons.check_circle : Icons.vpn_key,
                                  color: isActive ? Colors.green : Colors.grey,
                                ),
                                title: Text(
                                  cred['name'] ?? 'Без названия',
                                  style: TextStyle(
                                    fontWeight: isActive ? FontWeight.bold : null,
                                  ),
                                ),
                                subtitle: Text(
                                  'Client ID: ${cred['client_id_preview']}\n'
                                  '${isActive ? "Активный" : "Неактивный"}',
                                ),
                                isThreeLine: true,
                                trailing: Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    if (!isActive)
                                      IconButton(
                                        icon: const Icon(Icons.power_settings_new),
                                        color: Colors.blue,
                                        onPressed: () => _activateCredential(cred['id']),
                                        tooltip: 'Активировать',
                                      ),
                                    IconButton(
                                      icon: const Icon(Icons.delete),
                                      color: Colors.red,
                                      onPressed: () => _deleteCredential(
                                        cred['id'],
                                        cred['name'] ?? 'Без названия',
                                      ),
                                      tooltip: 'Удалить',
                                    ),
                                  ],
                                ),
                              ),
                            );
                          },
                        ),
                ),
              ],
            ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _addCredential,
        icon: const Icon(Icons.add),
        label: const Text('Добавить ключи'),
      ),
    );
  }
}

class _AddCredentialDialog extends StatefulWidget {
  @override
  State<_AddCredentialDialog> createState() => _AddCredentialDialogState();
}

class _AddCredentialDialogState extends State<_AddCredentialDialog> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _clientIdController = TextEditingController();
  final _apiKeyController = TextEditingController();

  @override
  void dispose() {
    _nameController.dispose();
    _clientIdController.dispose();
    _apiKeyController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Новый набор ключей'),
      content: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: _nameController,
                decoration: const InputDecoration(
                  labelText: 'Название',
                  hintText: 'Например: Основной магазин',
                  prefixIcon: Icon(Icons.label),
                ),
                validator: (value) {
                  if (value == null || value.trim().isEmpty) {
                    return 'Введите название';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 16),
              TextFormField(
                controller: _clientIdController,
                decoration: const InputDecoration(
                  labelText: 'Client ID',
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
              TextFormField(
                controller: _apiKeyController,
                decoration: const InputDecoration(
                  labelText: 'API Key',
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
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: () {
            if (_formKey.currentState!.validate()) {
              Navigator.pop(context, {
                'name': _nameController.text.trim(),
                'client_id': _clientIdController.text.trim(),
                'api_key': _apiKeyController.text.trim(),
              });
            }
          },
          child: const Text('Добавить'),
        ),
      ],
    );
  }
}
