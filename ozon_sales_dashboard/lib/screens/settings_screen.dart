import 'package:flutter/material.dart';
import 'package:dio/dio.dart';
import 'package:provider/provider.dart';
import '../services/api.dart';
import '../providers/auth_provider.dart';

/**
 * SettingsScreen — экран настроек.
 * Позволяет управлять API-ключами Ozon (добавление, удаление, активация),
 * настраивать безопасность (биометрия) и управлять данными.
 */
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _isLoading = false;
  List<Map<String, dynamic>> _credentials = []; // Список подключенных магазинов
  String? _errorMessage;
  String _purgeMarketplace = 'ozon';

  // Используем наш централизованный API клиент
  late final OzonApiClient _api;

  @override
  void initState() {
    super.initState();
    _api = OzonApiClient(); // Инициализация клиента
    _loadCredentials(); // Загружаем список ключей при открытии экрана
  }

  /// Получает список всех API-ключей пользователя с сервера.
  Future<void> _loadCredentials() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final response = await _api.dio.get('/auth/me/ozon-credentials');
      setState(() {
        _credentials = List<Map<String, dynamic>>.from(
          response.data['credentials'] ?? []
        );
      });
    } catch (e) {
      setState(() => _errorMessage = 'Ошибка загрузки: $e');
    } finally {
      setState(() => _isLoading = false);
    }
  }

  /// Вызывает диалоговое окно для ввода новых ключей и отправляет их на сервер.
  Future<void> _addCredential() async {
    final result = await showDialog<Map<String, String>>(
      context: context,
      builder: (context) => _AddCredentialDialog(),
    );

    if (result == null) return;

    setState(() => _isLoading = true);

    try {
      // Используем метод из нашего OzonApiClient
      await _api.addOzonCredential(
        clientId: result['client_id']!,
        apiKey: result['api_key']!,
        marketplace: result['marketplace']!,
        name: result['name']!,
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Ключи успешно добавлены'), backgroundColor: Colors.green),
        );
        _loadCredentials(); // Обновляем список
      }
    } catch (e) {
      setState(() => _errorMessage = 'Ошибка добавления: $e');
    } finally {
      setState(() => _isLoading = false);
    }
  }

  /// Делает выбранный набор ключей активным (текущим) для аналитики.
  Future<void> _activateCredential(int id) async {
    try {
      await _api.dio.put('/auth/me/ozon-credentials/$id/activate');
      _loadCredentials();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Ошибка активации: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }

  /// Удаляет API-ключи из системы.
  Future<void> _deleteCredential(int id, String name) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Удаление'),
        content: Text('Удалить ключи для магазина "$name"?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Отмена')),
          FilledButton(onPressed: () => Navigator.pop(context, true), 
            style: FilledButton.styleFrom(backgroundColor: Colors.red), 
            child: const Text('Удалить')),
        ],
      ),
    );

    if (confirmed != true) return;

    try {
      await _api.dio.delete('/auth/me/ozon-credentials/$id');
      _loadCredentials();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Ошибка удаления: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }

  /// Полная очистка всех данных по маркетплейсу в БД.
  Future<void> _purgeData() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('ОПАСНАЯ ЗОНА'),
        content: const Text('Это удалит ВСЕ заказы и статистику из базы. Продолжить?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Отмена')),
          FilledButton(onPressed: () => Navigator.pop(context, true), 
            style: FilledButton.styleFrom(backgroundColor: Colors.red), 
            child: const Text('УДАЛИТЬ ВСЁ')),
        ],
      ),
    );

    if (confirmed != true) return;

    try {
      await _api.dio.post(
        '/auth/me/data/purge',
        data: {'marketplace': _purgeMarketplace},
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('База данных очищена')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Ошибка очистки: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }

  /// Запускает процесс Backfill (загрузку истории за год) в фоновом режиме на сервере.
  Future<void> _runInitialSync() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Синхронизация'),
        content: const Text('Запустить полную загрузку истории заказов (365 дней)? Это может занять время.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Отмена')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Запустить')),
        ],
      ),
    );

    if (confirmed != true) return;

    try {
      await _api.dio.post('/sync/initial/force');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Загрузка истории запущена')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Ошибка запуска: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final authProvider = context.watch<AuthProvider>();

    return Scaffold(
      appBar: AppBar(title: const Text('Настройки'), backgroundColor: Theme.of(context).colorScheme.inversePrimary),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_errorMessage != null)
                  Card(color: Colors.red.shade50, child: ListTile(leading: const Icon(Icons.error, color: Colors.red), title: Text(_errorMessage!))),
                
                // СЕКЦИЯ: Безопасность
                const Text('Безопасность', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                Card(
                  child: SwitchListTile(
                    title: const Text('Вход по отпечатку пальца'),
                    subtitle: const Text('Использовать биометрию вместо ввода пароля'),
                    secondary: const Icon(Icons.fingerprint),
                    value: authProvider.biometricEnabled,
                    onChanged: (bool value) {
                      authProvider.setBiometricEnabled(value);
                    },
                  ),
                ),
                const SizedBox(height: 16),

                // Карточка-инструкция
                Card(
                  color: Theme.of(context).primaryColor.withOpacity(0.05),
                  child: ListTile(
                    leading: Icon(Icons.help_outline, color: Theme.of(context).primaryColor),
                    title: const Text('Как подключить магазин?'),
                    subtitle: const Text('Создайте API-ключ в кабинете маркетплейса (для Ozon тип "Администратор") и скопируйте Client ID и Key сюда.'),
                  ),
                ),

                const SizedBox(height: 16),
                const Text('Управление данными', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                
                // Блок синхронизации и очистки
                Card(
                  child: Column(
                    children: [
                      ListTile(
                        leading: Icon(Icons.sync, color: Theme.of(context).secondaryHeaderColor),
                        title: const Text('Загрузить историю'),
                        subtitle: const Text('Скачать все заказы за последний год'),
                        trailing: ElevatedButton(onPressed: _runInitialSync, child: const Text('Старт')),
                      ),
                      const Divider(height: 1),
                      ListTile(
                        leading: const Icon(Icons.delete_sweep, color: Colors.red),
                        title: const Text('Очистить базу данных'),
                        subtitle: const Text('Удалить все локальные данные Ozon'),
                        trailing: OutlinedButton(onPressed: _purgeData, 
                          style: OutlinedButton.styleFrom(foregroundColor: Colors.red), 
                          child: const Text('Удалить')),
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 24),
                const Text('Ваши магазины', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),

                // Список ключей
                if (_credentials.isEmpty)
                  const Center(child: Padding(padding: EdgeInsets.all(32), child: Text('Магазины не добавлены')))
                else
                  ..._credentials.map((cred) {
                    final isActive = cred['is_active'] ?? false;
                    return Card(
                      color: isActive ? Colors.green.shade50 : null,
                      child: ListTile(
                        leading: Icon(isActive ? Icons.check_circle : Icons.vpn_key, 
                          color: isActive ? Colors.green : Colors.grey),
                        title: Text(cred['name'] ?? 'Магазин', 
                          style: TextStyle(fontWeight: isActive ? FontWeight.bold : null)),
                        subtitle: Text('Client ID: ${cred['client_id_preview']}'),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (!isActive) IconButton(icon: Icon(Icons.play_circle_outline, color: Theme.of(context).primaryColor),
                              onPressed: () => _activateCredential(cred['id'])),
                            IconButton(icon: const Icon(Icons.delete_outline, color: Colors.red), 
                              onPressed: () => _deleteCredential(cred['id'], cred['name'])),
                          ],
                        ),
                      ),
                    );
                  }).toList(),
              ],
            ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _addCredential,
        icon: const Icon(Icons.add),
        label: const Text('Подключить магазин'),
      ),
    );
  }
}

/**
 * Внутренний диалог для ввода данных нового API-ключа.
 */
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
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Подключение Ozon'),
      content: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(controller: _nameController, 
                decoration: const InputDecoration(labelText: 'Название магазина'), 
                validator: (v) => v!.isEmpty ? 'Обязательно' : null),
              const SizedBox(height: 12),
              TextFormField(controller: _clientIdController, 
                decoration: const InputDecoration(labelText: 'Client ID'), 
                validator: (v) => v!.isEmpty ? 'Обязательно' : null),
              const SizedBox(height: 12),
              TextFormField(controller: _apiKeyController, 
                decoration: const InputDecoration(labelText: 'API Key'), 
                obscureText: true, 
                validator: (v) => v!.isEmpty ? 'Обязательно' : null),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Отмена')),
        FilledButton(onPressed: () {
          if (_formKey.currentState!.validate()) {
            Navigator.pop(context, {
              'marketplace': 'ozon',
              'name': _nameController.text.trim(),
              'client_id': _clientIdController.text.trim(),
              'api_key': _apiKeyController.text.trim(),
            });
          }
        }, child: const Text('Добавить')),
      ],
    );
  }
}
