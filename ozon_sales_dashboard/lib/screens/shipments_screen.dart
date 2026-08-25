import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import 'dart:async';
import '../providers/auth_provider.dart';
import '../services/api.dart';

import 'order_details_screen.dart';

class ShipmentsScreen extends StatefulWidget {
  const ShipmentsScreen({Key? key}) : super(key: key);

  @override
  State<ShipmentsScreen> createState() => _ShipmentsScreenState();
}

class _ShipmentsScreenState extends State<ShipmentsScreen> {
  late OzonApiClient _apiClient;
  List<dynamic> _orders = [];
  bool _isLoading = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    final auth = Provider.of<AuthProvider>(context, listen: false);
    _apiClient = OzonApiClient(authProvider: auth);
    _loadData();
    // Обновляем таймеры каждую минуту
    _timer = Timer.periodic(const Duration(minutes: 1), (timer) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _loadData() async {
    setState(() => _isLoading = true);
    try {
      final res = await _apiClient.getUnfulfilledOrders();
      setState(() {
        _orders = res;
        _isLoading = false;
      });
    } catch (e) {
      setState(() => _isLoading = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Ошибка загрузки: $e')),
      );
    }
  }

  String _getTimeLeft(String? shipmentDate) {
    if (shipmentDate == null) return '-';
    try {
      final dt = DateTime.parse(shipmentDate).toLocal();
      final now = DateTime.now();
      final diff = dt.difference(now);

      if (diff.isNegative) return 'Просрочено';
      
      final hours = diff.inHours;
      final minutes = diff.inMinutes % 60;
      return '${hours}ч ${minutes}м';
    } catch (_) {
      return '-';
    }
  }

  Color _getSlaColor(String? shipmentDate) {
    if (shipmentDate == null) return Colors.grey;
    try {
      final dt = DateTime.parse(shipmentDate).toLocal();
      final now = DateTime.now();
      final diff = dt.difference(now);

      if (diff.isNegative) return Colors.red;
      if (diff.inHours < 2) return Colors.orange;
      return Colors.green;
    } catch (_) {
      return Colors.grey;
    }
  }

  String _statusRu(String code) {
    switch (code) {
      case 'awaiting_assembly': return 'Сборка';
      case 'awaiting_packaging': return 'Упаковка';
      case 'awaiting_deliver': return 'Отгрузка';
      default: return code;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF5F7FA),
      appBar: AppBar(
        title: const Text('Горящие заказы FBS', style: TextStyle(fontWeight: FontWeight.bold)),
        backgroundColor: Colors.white,
        elevation: 0,
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadData,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _loadData,
        child: _isLoading && _orders.isEmpty
            ? const Center(child: CircularProgressIndicator())
            : _orders.isEmpty
                ? const Center(child: Text('Нет активных заказов для сборки'))
                : ListView.builder(
                    padding: const EdgeInsets.all(16),
                    itemCount: _orders.length,
                    itemBuilder: (context, index) {
                      final order = _orders[index];
                      final slaText = _getTimeLeft(order['shipment_date']);
                      final slaColor = _getSlaColor(order['shipment_date']);
                      final isExpress = order['is_express'] ?? false;

                      return InkWell(
                        onTap: () {
                          // Чтобы не зависеть от задержки синхронизации БД, передаем данные напрямую из API Ozon
                          final Map<String, dynamic> preloaded = {
                            "order_number": order['posting_number'],
                            "header": {
                              "first_created_at": order['in_process_at'],
                              "total_payout": 0, // Неизвестно до сборки
                              "profit": 0,
                            },
                            "postings": [
                              {
                                "posting_number": order['posting_number'],
                                "status": order['status'],
                                "scheme": "fbs",
                                "is_express": order['is_express'],
                                "shipment_date": order['shipment_date'],
                                "tpl_provider": order['tpl_provider'],
                                "delivery_method_name": order['delivery_method_name'],
                                "products": order['products'] ?? [],
                              }
                            ]
                          };

                          Navigator.of(context).push(MaterialPageRoute(
                            builder: (_) => OrderDetailsScreen(
                              orderNumber: order['posting_number'],
                              preloadedData: preloaded,
                            ),
                          ));
                        },
                        child: Card(
                          margin: const EdgeInsets.only(bottom: 16),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                          child: Padding(
                            padding: const EdgeInsets.all(16),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                  children: [
                                    Column(
                                      crossAxisAlignment: CrossAxisAlignment.start,
                                      children: [
                                        Text(
                                          '№ ${order['posting_number']}',
                                          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                                        ),
                                        const SizedBox(height: 4),
                                        Row(
                                          children: [
                                            Container(
                                              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                                              decoration: BoxDecoration(
                                                color: Colors.blue.withOpacity(0.1),
                                                borderRadius: BorderRadius.circular(4),
                                              ),
                                              child: Text(
                                                _statusRu(order['status']),
                                                style: const TextStyle(fontSize: 12, color: Colors.blue, fontWeight: FontWeight.bold),
                                              ),
                                            ),
                                            if (isExpress) ...[
                                              const SizedBox(width: 8),
                                              Container(
                                                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                                                decoration: BoxDecoration(
                                                  color: Colors.orange.withOpacity(0.1),
                                                  borderRadius: BorderRadius.circular(4),
                                                ),
                                                child: const Text(
                                                  'EXPRESS',
                                                  style: TextStyle(fontSize: 12, color: Colors.orange, fontWeight: FontWeight.bold),
                                                ),
                                              ),
                                            ],
                                          ],
                                        ),
                                      ],
                                    ),
                                    Column(
                                      crossAxisAlignment: CrossAxisAlignment.end,
                                      children: [
                                        const Text('Осталось:', style: TextStyle(fontSize: 11, color: Colors.grey)),
                                        Text(
                                          slaText,
                                          style: TextStyle(
                                            fontWeight: FontWeight.bold,
                                            fontSize: 18,
                                            color: slaColor,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ],
                                ),
                                const Divider(height: 24),
                                Row(
                                  children: [
                                    const Icon(Icons.inventory_2_outlined, size: 16, color: Colors.grey),
                                    const SizedBox(width: 8),
                                    Text('${order['products_count']} тов.', style: const TextStyle(fontSize: 13)),
                                    const Spacer(),
                                    const Icon(Icons.local_shipping_outlined, size: 16, color: Colors.grey),
                                    const SizedBox(width: 8),
                                    Text(
                                      '${order['tpl_provider'] ?? order['delivery_method_name'] ?? 'Ozon'}',
                                      style: const TextStyle(fontSize: 13),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 12),
                                Text(
                                  'Отгрузка: ${order['shipment_date'] != null ? DateFormat('dd.MM HH:mm').format(DateTime.parse(order['shipment_date']).toLocal()) : '-'}',
                                  style: TextStyle(fontSize: 12, color: Colors.grey[600]),
                                ),
                              ],
                            ),
                          ),
                        ),
                      );
                    },
                  ),
      ),
    );
  }
}
