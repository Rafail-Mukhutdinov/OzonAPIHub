import 'package:flutter/material.dart';
import '../services/api.dart';
import 'package:shared_preferences/shared_preferences.dart';

/**
 * SettingsScreen — экран настроек.
 * Позволяет управлять API-ключами Ozon (добавление, удаление, активация),
 * запускать полную синхронизацию данных и очищать базу.
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

<<<<<<< HEAD
  // Список поддерживаемых маркетплейсов (в будущем можно расширить)
=======
  // Используем наш централизованный API клиент
  late final OzonApiClient _api;

>>>>>>> 6e05b8426d8a23501811c28cb1ed9d6be020bf8b
  final List<Map<String, String>> _marketplaces = [
    {'value': 'ozon', 'label': 'Ozon'},
    {'value': 'wildberries', 'label': 'Wildberries'},
    {'value': 'yandex_market', 'label': 'Yandex Market'},
    {'value': 'aliexpress', 'label': 'AliExpress'},
  ];

  @override
  void initState() {
    super.initState();
<<<<<<< HEAD
    _loadCredentials(); // Загружаем список ключей при открытии экрана
=======
    _api = OzonApiClient(); // Инициализация клиента
    _loadCredentials();
>>>>>>> 6e05b8426d8a23501811c28cb1ed9d6be020bf8b
  }

  /// Получает список всех API-ключей пользователя с сервера.
  Future<void> _loadCredentials() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
<<<<<<< HEAD
      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString('jwt_token');
      
      if (token == null) throw Exception('Не авторизован');

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
=======
      final response = await _api.dio.get('/auth/me/ozon-credentials');
      setState(() {
        _credentials = List<Map<String, dynamic>>.from(
          response.data['credentials'] ?? []
        );
      });
>>>>>>> 6e05b8426d8a23501811c28cb1ed9d6be020bf8b
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
<<<<<<< HEAD
      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString('jwt_token');

      final dio = Dio(BaseOptions(baseUrl: OzonApiClient.getDefaultBaseUrl()));

      await dio.post(
        '/auth/me/ozon-credentials',
        data: result,
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Ключи добавлены'), backgroundColor: Colors.green));
        _loadCredentials(); // Обновляем список
=======
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
        _loadCredentials();
>>>>>>> 6e05b8426d8a23501811c28cb1ed9d6be020bf8b
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
<<<<<<< HEAD
      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString('jwt_token');

      final dio = Dio(BaseOptions(baseUrl: OzonApiClient.getDefaultBaseUrl()));

      await dio.put(
        '/auth/me/ozon-credentials/$id/activate',
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Магазин переключен')));
        _loadCredentials();
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Ошибка: $e'), backgroundColor: Colors.red));
=======
      await _api.dio.put('/auth/me/ozon-credentials/$id/activate');
      _loadCredentials();
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Ошибка: $e'), backgroundColor: Colors.red));
>>>>>>> 6e05b8426d8a23501811c28cb1ed9d6be020bf8b
    }
  }

  /// Удаляет API-ключи из системы.
  Future<void> _deleteCredential(int id, String name) async {
<<<<<<< HEAD
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Удаление'),
        content: Text('Удалить ключи для магазина "$name"?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Отмена')),
          FilledButton(onPressed: () => Navigator.pop(context, true), style: FilledButton.styleFrom(backgroundColor: Colors.red), child: const Text('Удалить')),
        ],
      ),
    );

    if (confirmed != true) return;

    try {
      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString('jwt_token');
      final dio = Dio(BaseOptions(baseUrl: OzonApiClient.getDefaultBaseUrl()));

      await dio.delete(
        '/auth/me/ozon-credentials/$id',
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Удалено')));
        _loadCredentials();
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Ошибка: $e'), backgroundColor: Colors.red));
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
          FilledButton(onPressed: () => Navigator.pop(context, true), style: FilledButton.styleFrom(backgroundColor: Colors.red), child: const Text('УДАЛИТЬ ВСЁ')),
        ],
      ),
    );

    if (confirmed != true) return;

    try {
      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString('jwt_token');
      final dio = Dio(BaseOptions(baseUrl: OzonApiClient.getDefaultBaseUrl()));

      await dio.post(
        '/auth/me/data/purge',
        data: {'marketplace': _purgeMarketplace},
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );

      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('База данных очищена')));
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Ошибка: $e'), backgroundColor: Colors.red));
=======
    try {
      await _api.dio.delete('/auth/me/ozon-credentials/$id');
      _loadCredentials();
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Ошибка: $e'), backgroundColor: Colors.red));
>>>>>>> 6e05b8426d8a23501811c28cb1ed9d6be020bf8b
    }
  }

  /// Запускает процесс Backfill (загрузку истории за год) в фоновом режиме на сервере.
  Future<void> _runInitialSync() async {
<<<<<<< HEAD
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
      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString('jwt_token');
      final dio = Dio(BaseOptions(baseUrl: OzonApiClient.getDefaultBaseUrl()));

      await dio.post(
        '/sync/initial/force',
        options: Options(headers: {'Authorization': 'Bearer $token'}),
      );

      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Загрузка истории запущена')));
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Ошибка: $e'), backgroundColor: Colors.red));
=======
    try {
      await _api.dio.post('/sync/initial/force');
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Загрузка запущена')));
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Ошибка: $e'), backgroundColor: Colors.red));
>>>>>>> 6e05b8426d8a23501811c28cb1ed9d6be020bf8b
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
<<<<<<< HEAD
      appBar: AppBar(title: const Text('Настройки'), backgroundColor: Theme.of(context).colorScheme.inversePrimary),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_errorMessage != null)
                  Card(color: Colors.red.shade50, child: ListTile(leading: const Icon(Icons.error, color: Colors.red), title: Text(_errorMessage!))),
                
                // Карточка-инструкция
                Card(
                  color: Colors.blue.shade50,
                  child: const ListTile(
                    leading: Icon(Icons.help_outline, color: Colors.blue),
                    title: Text('Как подключить магазин?'),
                    subtitle: Text('Создайте API-ключ в кабинете Ozon Seller (тип "Администратор") и скопируйте Client ID и Key сюда.'),
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
                        leading: const Icon(Icons.sync, color: Colors.blue),
                        title: const Text('Загрузить историю Ozon'),
                        subtitle: const Text('Скачать все заказы за последний год'),
                        trailing: ElevatedButton(onPressed: _runInitialSync, child: const Text('Старт')),
                      ),
                      const Divider(height: 1),
                      ListTile(
                        leading: const Icon(Icons.delete_sweep, color: Colors.red),
                        title: const Text('Очистить базу данных'),
                        subtitle: const Text('Удалить все локальные данные Ozon'),
                        trailing: OutlinedButton(onPressed: _purgeData, style: OutlinedButton.styleFrom(foregroundColor: Colors.red), child: const Text('Удалить')),
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
                        leading: Icon(isActive ? Icons.check_circle : Icons.vpn_key, color: isActive ? Colors.green : Colors.grey),
                        title: Text(cred['name'] ?? 'Магазин', style: TextStyle(fontWeight: isActive ? FontWeight.bold : null)),
                        subtitle: Text('Client ID: ${cred['client_id_preview']}'),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (!isActive) IconButton(icon: const Icon(Icons.play_circle_outline, color: Colors.blue), onPressed: () => _activateCredential(cred['id'])),
                            IconButton(icon: const Icon(Icons.delete_outline, color: Colors.red), onPressed: () => _deleteCredential(cred['id'], cred['name'])),
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
=======
      appBar: AppBar(title: const Text('Настройки API ключей')),
      body: _isLoading
        ? const Center(child: CircularProgressIndicator())
        : ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (_errorMessage != null) Text(_errorMessage!, style: const TextStyle(color: Colors.red)),
              ElevatedButton(onPressed: _runInitialSync, child: const Text('Запустить полную загрузку')),
              const Divider(),
              ..._credentials.map((c) => ListTile(
                title: Text(c['name']),
                subtitle: Text('ID: ${c['client_id_preview']}'),
                trailing: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (!(c['is_active'] ?? false)) IconButton(icon: const Icon(Icons.play_arrow), onPressed: () => _activateCredential(c['id'])),
                    IconButton(icon: const Icon(Icons.delete), onPressed: () => _deleteCredential(c['id'], c['name'])),
                  ],
                ),
              )),
            ],
          ),
      floatingActionButton: FloatingActionButton(onPressed: _addCredential, child: const Icon(Icons.add)),
>>>>>>> 6e05b8426d8a23501811c28cb1ed9d6be020bf8b
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
  final _nameController = TextEditingController();
  final _clientIdController = TextEditingController();
  final _apiKeyController = TextEditingController();
<<<<<<< HEAD
  
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
              TextFormField(controller: _nameController, decoration: const InputDecoration(labelText: 'Название магазина'), validator: (v) => v!.isEmpty ? 'Обязательно' : null),
              const SizedBox(height: 12),
              TextFormField(controller: _clientIdController, decoration: const InputDecoration(labelText: 'Client ID'), validator: (v) => v!.isEmpty ? 'Обязательно' : null),
              const SizedBox(height: 12),
              TextFormField(controller: _apiKeyController, decoration: const InputDecoration(labelText: 'API Key'), obscureText: true, validator: (v) => v!.isEmpty ? 'Обязательно' : null),
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
=======
  String _selectedMarketplace = 'ozon';

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Новый набор ключей'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(controller: _nameController, decoration: const InputDecoration(labelText: 'Название')),
          TextField(controller: _clientIdController, decoration: const InputDecoration(labelText: 'Client ID')),
          TextField(controller: _apiKeyController, decoration: const InputDecoration(labelText: 'API Key')),
        ],
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Отмена')),
        TextButton(
          onPressed: () => Navigator.pop(context, {
            'marketplace': _selectedMarketplace,
            'name': _nameController.text,
            'client_id': _clientIdController.text,
            'api_key': _apiKeyController.text,
          }),
          child: const Text('Добавить'),
        ),
>>>>>>> 6e05b8426d8a23501811c28cb1ed9d6be020bf8b
      ],
    );
  }
}
