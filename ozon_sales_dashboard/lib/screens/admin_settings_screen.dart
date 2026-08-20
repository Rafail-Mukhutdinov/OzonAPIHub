import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import '../services/api.dart';

class AdminSettingsScreen extends StatefulWidget {
  const AdminSettingsScreen({super.key});

  @override
  State<AdminSettingsScreen> createState() => _AdminSettingsScreenState();
}

class _AdminSettingsScreenState extends State<AdminSettingsScreen> {
  late final OzonApiClient api;
  final bool _loading = false;

  @override
  void initState() {
    super.initState();
    final auth = Provider.of<AuthProvider>(context, listen: false);
    api = OzonApiClient(authProvider: auth);
  }

  @override
  Widget build(BuildContext context) {
    if (!kIsWeb) return const Scaffold(body: Center(child: Text('Web only')));

    return Scaffold(
      appBar: AppBar(title: const Text('Системные настройки')),
      body: _loading 
        ? const Center(child: CircularProgressIndicator())
        : ListView(
            padding: const EdgeInsets.all(24),
            children: [
              const Text('Глобальные параметры платформы', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
              const SizedBox(height: 24),
              Card(
                child: Column(
                  children: [
                    SwitchListTile(
                      title: const Text('Режим обслуживания (Maintenance Mode)'),
                      subtitle: const Text('Запрещает синхронизацию и вход для всех пользователей кроме админов'),
                      value: false,
                      secondary: const Chip(label: Text('SOON'), backgroundColor: Colors.amber),
                      onChanged: (v) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(content: Text('Эта функция находится в разработке')),
                        );
                      },
                    ),
                    const Divider(),
                    ListTile(
                      title: const Text('Версия API Ozon'),
                      subtitle: const Text('Текущая стабильная: v1/v2/v3'),
                      trailing: const Chip(label: Text('AUTO')),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 32),
              const Text('Инфраструктура', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              Card(
                child: ListTile(
                  leading: const Icon(Icons.cleaning_services, color: Colors.orange),
                  title: const Text('Очистка временных файлов'),
                  subtitle: const Text('Удаляет старые логи и кэш (старше 30 дней)'),
                  trailing: const Chip(label: Text('COMING SOON')),
                  onTap: () {
                       ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('Функция будет доступна в следующем обновлении')),
                      );
                  },
                ),
              ),
            ],
          ),
    );
  }
}
