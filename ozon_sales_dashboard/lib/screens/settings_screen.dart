import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:intl/intl.dart';
import 'package:dio/dio.dart';
import 'package:provider/provider.dart';
import '../services/api.dart';
import '../providers/auth_provider.dart';

/// SettingsScreen — экран настроек приложения.
/// Позволяет пользователю управлять подключенными магазинами Ozon (API-ключами),
/// настраивать безопасность (биометрия), просматривать статус подписки и управлять локальными данными.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _isLoading = false;                   // Состояние загрузки данных с сервера
  List<Map<String, dynamic>> _credentials = []; // Список API-ключей (магазинов) пользователя
  String? _errorMessage;                     // Текст ошибки для отображения в UI
  String _purgeMarketplace = 'ozon';         // Идентификатор маркетплейса для очистки данных

  // Централизованный клиент для выполнения API-запросов
  late final OzonApiClient _api;

  @override
  void initState() {
    super.initState();
    // Инициализация API клиента с передачей текущего провайдера авторизации
    final auth = Provider.of<AuthProvider>(context, listen: false);
    _api = OzonApiClient(authProvider: auth);
    _loadCredentials();
  }

  /// Загрузка списка всех подключенных API-ключей пользователя.
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

  /// Открытие диалога и добавление нового набора API-ключей (Client ID и API Key).
  Future<void> _addCredential() async {
    final result = await showDialog<Map<String, String>>(
      context: context,
      builder: (context) => _AddCredentialDialog(),
    );

    if (result == null) return;

    setState(() => _isLoading = true);

    try {
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
        _loadCredentials();
      }
    } catch (e) {
      setState(() => _errorMessage = 'Ошибка добавления: $e');
    } finally {
      setState(() => _isLoading = false);
    }
  }

  /// Переключение активного магазина (того, по которому будет строиться аналитика в дашборде).
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

  /// Удаление API-ключей магазина из системы пользователя.
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

  /// ОПАСНОЕ ДЕЙСТВИЕ: Полная очистка накопленной статистики и заказов в базе данных.
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

  /// Запуск принудительной синхронизации истории заказов за последние 365 дней.
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
    // Получаем доступ к провайдеру для проверки настроек безопасности и имитации
    final authProvider = context.watch<AuthProvider>();
    final isImpersonating = authProvider.isImpersonating;

    return Scaffold(
      appBar: AppBar(title: const Text('Настройки'), backgroundColor: Theme.of(context).colorScheme.inversePrimary),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                // Предупреждение, если админ зашел под пользователем
                if (isImpersonating)
                  Card(
                    color: Colors.orange.shade100,
                    child: const ListTile(
                      leading: Icon(Icons.warning_amber, color: Colors.orange),
                      title: Text('Режим поддержки активен'),
                      subtitle: Text('Внесение изменений в настройки магазина ограничено.'),
                    ),
                  ),

                if (_errorMessage != null)
                  Card(color: Colors.red.shade50, child: ListTile(leading: const Icon(Icons.error, color: Colors.red), title: Text(_errorMessage!))),
                
                // Настройки биометрии (только для мобильных приложений)
                if (!kIsWeb) ...[
                  const Text('Безопасность', style: TextStyle(fontWeight: FontWeight.bold)),
                  const SizedBox(height: 8),
                  Card(
                    child: SwitchListTile(
                      title: const Text('Вход по отпечатку пальца'),
                      subtitle: const Text('Использовать биометрию вместо ввода ПИН-кода'),
                      secondary: const Icon(Icons.fingerprint),
                      value: authProvider.biometricEnabled,
                      onChanged: isImpersonating ? null : (bool value) {
                        authProvider.setBiometricEnabled(value);
                      },
                    ),
                  ),
                  const SizedBox(height: 16),
                ],

                // Обучающая карточка
                Card(
                  color: Theme.of(context).primaryColor.withOpacity(0.05),
                  child: ListTile(
                    leading: Icon(Icons.help_outline, color: Theme.of(context).primaryColor),
                    title: const Text('Как подключить магазин?'),
                    subtitle: const Text('Создайте API-ключ в кабинете Ozon Seller (тип "Администратор") и скопируйте Client ID и Key сюда.'),
                  ),
                ),

                const SizedBox(height: 16),
                const Text('Ваша подписка', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                Card(
                  child: ListTile(
                    leading: Icon(
                      authProvider.isDemo ? Icons.timer_outlined : Icons.verified_user,
                      color: authProvider.isDemo ? Colors.orange : Colors.blue,
                    ),
                    title: Text(authProvider.isDemo ? 'Демо-период' : 'Премиум подписка'),
                    subtitle: Text(
                      authProvider.subscriptionEndDate != null
                          ? 'Активна до: ${DateFormat('dd.MM.yyyy HH:mm').format(authProvider.subscriptionEndDate!.toLocal())}'
                          : 'Срок не ограничен',
                    ),
                    trailing: authProvider.isDemo
                        ? const Chip(label: Text('DEMO'))
                        : const Chip(label: Text('PREMIUM'), backgroundColor: Colors.blue, labelStyle: TextStyle(color: Colors.white)),
                  ),
                ),

                const SizedBox(height: 16),
                const Text('Управление данными', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                
                Card(
                  child: Column(
                    children: [
                      ListTile(
                        leading: Icon(Icons.sync, color: Theme.of(context).secondaryHeaderColor),
                        title: const Text('Загрузить историю'),
                        subtitle: const Text('Скачать все заказы за последний год'),
                        trailing: ElevatedButton(
                          onPressed: isImpersonating ? null : _runInitialSync, 
                          child: const Text('Старт')
                        ),
                      ),
                      const Divider(height: 1),
                      ListTile(
                        leading: const Icon(Icons.delete_sweep, color: Colors.red),
                        title: const Text('Очистить базу данных'),
                        subtitle: const Text('Удалить все локальные данные Ozon'),
                        trailing: OutlinedButton(
                          onPressed: isImpersonating ? null : _purgeData, 
                          style: OutlinedButton.styleFrom(foregroundColor: Colors.red), 
                          child: const Text('Удалить')
                        ),
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 24),
                const Text('Ваши магазины', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),

                // Динамический список магазинов пользователя
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
                            if (!isActive) IconButton(
                              icon: Icon(Icons.play_circle_outline, color: Theme.of(context).primaryColor),
                              onPressed: isImpersonating ? null : () => _activateCredential(cred['id'])
                            ),
                            IconButton(
                              icon: const Icon(Icons.delete_outline, color: Colors.red), 
                              onPressed: isImpersonating ? null : () => _deleteCredential(cred['id'], cred['name'])
                            ),
                          ],
                        ),
                      ),
                    );
                  }).toList(),
              ],
            ),
      floatingActionButton: isImpersonating ? null : FloatingActionButton.extended(
        onPressed: _addCredential,
        icon: const Icon(Icons.add),
        label: const Text('Подключить магазин'),
      ),
    );
  }
}

/// Внутренний вспомогательный виджет для ввода данных нового магазина.
class _AddCredentialDialog extends StatefulWidget {
  @override
  State<_AddCredentialDialog> createState() => _AddCredentialDialogState();
}

class _AddCredentialDialogState extends State<_AddCredentialDialog> {
  // Ключ для управления валидацией формы
  final _formKey = GlobalKey<FormState>();
  
  // Контроллеры полей ввода для добавления нового ключа
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
              // Поле Название
              TextFormField(
                controller: _nameController, 
                decoration: const InputDecoration(labelText: 'Название магазина (напр. "Мой Озон")'), 
                validator: (v) => v!.isEmpty ? 'Обязательно' : null
              ),
              const SizedBox(height: 12),
              // Поле Client ID
              TextFormField(
                controller: _clientIdController, 
                decoration: const InputDecoration(labelText: 'Client ID'), 
                validator: (v) => v!.isEmpty ? 'Обязательно' : null
              ),
              const SizedBox(height: 12),
              // Поле API Key (скрытое)
              TextFormField(
                controller: _apiKeyController, 
                decoration: const InputDecoration(labelText: 'API Key'), 
                obscureText: true, 
                validator: (v) => v!.isEmpty ? 'Обязательно' : null
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Отмена')),
        FilledButton(onPressed: () {
          // Валидация перед возвратом результата
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
