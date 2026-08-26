import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import '../services/api.dart';

/// Экран для настройки соответствия между методами доставки Ozon (rFBS) 
/// и внутренними названиями курьеров.
class RfbsDeliveryMethodsScreen extends StatefulWidget {
  const RfbsDeliveryMethodsScreen({super.key});

  @override
  State<RfbsDeliveryMethodsScreen> createState() => _RfbsDeliveryMethodsScreenState();
}

class _RfbsDeliveryMethodsScreenState extends State<RfbsDeliveryMethodsScreen> {
  late OzonApiClient _apiClient; // Клиент для работы с бэкендом
  List<dynamic> _methods = []; // Список методов доставки
  bool _isLoading = true; // Состояние загрузки

  @override
  void initState() {
    super.initState();
    final auth = Provider.of<AuthProvider>(context, listen: false);
    _apiClient = OzonApiClient(authProvider: auth);
    _loadData();
  }

  /// Загрузка списка методов и их маппингов с сервера.
  Future<void> _loadData() async {
    if (!mounted) return;
    setState(() => _isLoading = true);
    try {
      final res = await _apiClient.getDeliveryMethods();
      if (mounted) {
        setState(() {
          _methods = res;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() => _isLoading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Ошибка загрузки методов доставки: $e')),
        );
      }
    }
  }

  /// Отображает диалог редактирования названия курьера.
  Future<void> _editMapping(Map<String, dynamic> method) async {
    final TextEditingController controller = TextEditingController(text: method['custom_name'] ?? '');
    
    try {
      final result = await showDialog<String>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text('Название для "${method['ozon_name']}"'),
          content: TextField(
            controller: controller,
            decoration: const InputDecoration(
              hintText: 'Например: Курьер Иван',
              labelText: 'Ваше название',
            ),
            autofocus: true,
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context), child: const Text('Отмена')),
            if (method['custom_name'] != null)
              TextButton(
                onPressed: () => Navigator.pop(context, '__DELETE__'), 
                child: const Text('Сбросить', style: TextStyle(color: Colors.red))
              ),
            ElevatedButton(onPressed: () => Navigator.pop(context, controller.text), child: const Text('Сохранить')),
          ],
        ),
      );

      if (result != null) {
        try {
          if (result == '__DELETE__') {
            await _apiClient.deleteDeliveryMethodMapping(method['id']);
          } else if (result.trim().isNotEmpty) {
            await _apiClient.setDeliveryMethodMapping(method['id'], result.trim());
          } else {
            return;
          }
          _loadData(); // Перегружаем список после сохранения
        } catch (e) {
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Ошибка: $e')));
          }
        }
      }
    } finally {
      controller.dispose();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF5F7FA),
      appBar: AppBar(
        title: const Text('Методы доставки rFBS', style: TextStyle(fontWeight: FontWeight.bold)),
        backgroundColor: Colors.white,
        elevation: 0,
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _methods.isEmpty
              ? const Center(child: Text('Методы доставки rFBS не найдены'))
              : ListView.builder(
                  padding: const EdgeInsets.all(16),
                  itemCount: _methods.length,
                  itemBuilder: (context, index) {
                    final m = _methods[index];
                    final bool hasMapping = m['custom_name'] != null;

                    return Card(
                      margin: const EdgeInsets.only(bottom: 12),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      child: ListTile(
                        leading: Container(
                          padding: const EdgeInsets.all(8),
                          decoration: BoxDecoration(
                            color: m['is_active'] ? Colors.green.withAlpha(25) : Colors.grey.withAlpha(25),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Icon(
                            Icons.local_shipping_outlined, 
                            color: m['is_active'] ? Colors.green : Colors.grey,
                            size: 20,
                          ),
                        ),
                        title: Text(
                          m['custom_name'] ?? m['ozon_name'],
                          style: const TextStyle(fontWeight: FontWeight.bold),
                        ),
                        subtitle: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (hasMapping) Text('Оригинал: ${m['ozon_name']}', style: const TextStyle(fontSize: 11)),
                            Text('Провайдер: ${m['provider_name']}', style: const TextStyle(fontSize: 11, color: Colors.grey)),
                          ],
                        ),
                        trailing: const Icon(Icons.edit_outlined, size: 18),
                        onTap: () => _editMapping(m),
                      ),
                    );
                  },
                ),
    );
  }
}
