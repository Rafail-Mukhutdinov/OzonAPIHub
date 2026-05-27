import 'package:flutter/material.dart';
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
  String _purgeMarketplace = 'ozon';

  // Используем наш централизованный API клиент
  late final OzonApiClient _api;

  final List<Map<String, String>> _marketplaces = [
    {'value': 'ozon', 'label': 'Ozon'},
    {'value': 'wildberries', 'label': 'Wildberries'},
    {'value': 'yandex_market', 'label': 'Yandex Market'},
    {'value': 'aliexpress', 'label': 'AliExpress'},
  ];

  @override
  void initState() {
    super.initState();
    _api = OzonApiClient(); // Инициализация клиента
    _loadCredentials();
  }

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
      await _api.dio.put('/auth/me/ozon-credentials/$id/activate');
      _loadCredentials();
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Ошибка: $e'), backgroundColor: Colors.red));
    }
  }

  Future<void> _deleteCredential(int id, String name) async {
    try {
      await _api.dio.delete('/auth/me/ozon-credentials/$id');
      _loadCredentials();
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Ошибка: $e'), backgroundColor: Colors.red));
    }
  }

  Future<void> _runInitialSync() async {
    try {
      await _api.dio.post('/sync/initial/force');
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Загрузка запущена')));
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Ошибка: $e'), backgroundColor: Colors.red));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
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
    );
  }
}

class _AddCredentialDialog extends StatefulWidget {
  @override
  State<_AddCredentialDialog> createState() => _AddCredentialDialogState();
}

class _AddCredentialDialogState extends State<_AddCredentialDialog> {
  final _nameController = TextEditingController();
  final _clientIdController = TextEditingController();
  final _apiKeyController = TextEditingController();
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
      ],
    );
  }
}
