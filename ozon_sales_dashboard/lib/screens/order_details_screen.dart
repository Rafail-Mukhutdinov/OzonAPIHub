import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../services/api.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';

class OrderDetailsScreen extends StatefulWidget {
  final String orderNumber;
  final Map<String, dynamic>? preloadedData;

  const OrderDetailsScreen({
    Key? key, 
    required this.orderNumber,
    this.preloadedData,
  }) : super(key: key);

  @override
  State<OrderDetailsScreen> createState() => _OrderDetailsScreenState();
}

class _OrderDetailsScreenState extends State<OrderDetailsScreen> {
  late OzonApiClient _apiClient;
  Map<String, dynamic>? _data;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    final auth = Provider.of<AuthProvider>(context, listen: false);
    _apiClient = OzonApiClient(authProvider: auth);
    
    if (widget.preloadedData != null) {
      _data = widget.preloadedData;
      _isLoading = false;
    } else {
      _loadData();
    }
  }

  Future<void> _loadData() async {
    setState(() => _isLoading = true);
    try {
      final res = await _apiClient.getOrderSummary(widget.orderNumber);
      setState(() {
        _data = res;
        _isLoading = false;
      });
    } catch (e) {
      setState(() => _isLoading = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Ошибка загрузки деталей заказа: $e')),
      );
    }
  }

  String _statusRu(String code) {
    switch (code) {
      case 'awaiting_assembly': return 'Ожидает сборки';
      case 'awaiting_packaging': return 'Упаковка';
      case 'awaiting_deliver': return 'Отгрузка';
      case 'delivering': return 'Доставляется';
      case 'delivered': return 'Доставлен';
      case 'cancelled': return 'Отменен';
      default: return code;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF5F7FA),
      appBar: AppBar(
        title: Text('Заказ №${widget.orderNumber}', style: const TextStyle(fontWeight: FontWeight.bold)),
        backgroundColor: Colors.white,
        elevation: 0,
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _data == null
              ? const Center(child: Text('Данные не найдены'))
              : SingleChildScrollView(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _buildHeader(),
                      const SizedBox(height: 24),
                      const Text('ОТПРАВЛЕНИЯ', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11, color: Colors.grey)),
                      const SizedBox(height: 12),
                      ...(_data!['postings'] as List).map((p) => _buildPostingCard(p)).toList(),
                    ],
                  ),
                ),
    );
  }

  Widget _buildHeader() {
    final header = _data!['header'] ?? {};
    final f = NumberFormat.decimalPattern('ru_RU');

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16)),
      child: Column(
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              _buildInfoColumn('Создан', _formatDate(header['first_created_at']) ?? '-'),
              _buildInfoColumn('Выплата', '${f.format(header['total_payout'] ?? 0)} ₽', isBold: true),
            ],
          ),
          const Divider(height: 32),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              _buildInfoColumn('Доставка', _formatDate(header['last_delivery_at']) ?? 'В пути'),
              _buildInfoColumn('Прибыль', '${f.format(header['profit'] ?? 0)} ₽', isBold: true, color: Colors.green),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildPostingCard(Map<String, dynamic> p) {
    final bool isFbs = p['scheme'] != 'fbo';
    final bool isExpress = p['is_express'] ?? false;

    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: ExpansionTile(
        title: Text(p['posting_number'], style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Row(
          children: [
            Text(_statusRu(p['status']), style: TextStyle(color: Theme.of(context).primaryColor, fontSize: 12, fontWeight: FontWeight.bold)),
            if (isExpress) ...[
              const SizedBox(width: 8),
              const Text('EXPRESS', style: TextStyle(color: Colors.orange, fontSize: 10, fontWeight: FontWeight.bold)),
            ],
          ],
        ),
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (isFbs) _buildFbsBlock(p),
                const SizedBox(height: 12),
                const Text('ТОВАРЫ', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 10, color: Colors.grey)),
                const SizedBox(height: 8),
                ...(p['products'] as List).map((prod) => _buildProductRow(prod)).toList(),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildFbsBlock(Map<String, dynamic> p) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: Colors.orange.withOpacity(0.05), borderRadius: BorderRadius.circular(8), border: Border.all(color: Colors.orange.withOpacity(0.2))),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(children: [Icon(Icons.local_shipping_outlined, size: 14, color: Colors.orange), SizedBox(width: 8), Text('ЛОГИСТИКА FBS', style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: Colors.orange))]),
          const SizedBox(height: 8),
          _buildDetailRow('Служба', p['tpl_provider'] ?? p['delivery_method_name'] ?? 'Ozon'),
          _buildDetailRow('Отгрузка до', _formatDate(p['shipment_date']) ?? '-'),
          if (p['tracking_number'] != null) _buildDetailRow('Трек-номер', p['tracking_number']),
        ],
      ),
    );
  }

  Widget _buildProductRow(Map<String, dynamic> prod) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(child: Text(prod['name'] ?? 'Товар', style: const TextStyle(fontSize: 12), maxLines: 1, overflow: TextOverflow.ellipsis)),
          const SizedBox(width: 8),
          Text('${prod['quantity']} шт.', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold)),
        ],
      ),
    );
  }

  Widget _buildDetailRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(fontSize: 11, color: Colors.grey)),
          Text(value, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }

  Widget _buildInfoColumn(String label, String value, {bool isBold = false, Color? color}) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 11, color: Colors.grey)),
        const SizedBox(height: 4),
        Text(value, style: TextStyle(fontSize: 15, fontWeight: isBold ? FontWeight.bold : FontWeight.normal, color: color)),
      ],
    );
  }

  String? _formatDate(String? iso) {
    if (iso == null) return null;
    try {
      final dt = DateTime.parse(iso).toLocal();
      return DateFormat('dd.MM.yyyy HH:mm').format(dt);
    } catch (_) {
      return iso;
    }
  }
}
