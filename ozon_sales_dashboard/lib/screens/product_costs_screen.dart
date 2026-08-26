import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api.dart';
import '../providers/auth_provider.dart';
import 'package:intl/intl.dart';

/// ProductCostsScreen — экран справочника себестоимости товаров.
/// Позволяет просматривать список товаров Ozon, искать их и задавать историю себестоимости.
class ProductCostsScreen extends StatefulWidget {
  const ProductCostsScreen({super.key});

  @override
  State<ProductCostsScreen> createState() => _ProductCostsScreenState();
}

class _ProductCostsScreenState extends State<ProductCostsScreen> {
  List<dynamic> _products = []; // Полный список товаров, полученный от API
  bool _isLoading = true;       // Состояние первоначальной загрузки списка
  String _searchQuery = '';     // Текст текущего поискового запроса

  @override
  void initState() {
    super.initState();
    _fetchProducts();
  }

  /// Загрузка списка товаров активного магазина через OzonApiClient.
  Future<void> _fetchProducts() async {
    setState(() => _isLoading = true);
    try {
      final api = OzonApiClient(authProvider: context.read<AuthProvider>());
      final data = await api.getProductsList();
      setState(() {
        _products = data['items'] ?? [];
        _isLoading = false;
      });
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Ошибка загрузки товаров: $e')),
        );
      }
      setState(() => _isLoading = false);
    }
  }

  /// Геттер для получения отфильтрованного списка товаров на основе поискового запроса.
  List<dynamic> get _filteredProducts {
    if (_searchQuery.isEmpty) return _products;
    return _products.where((p) {
      final name = (p['name'] ?? '').toString().toLowerCase();
      final sku = (p['sku'] ?? '').toString();
      final offerId = (p['offer_id'] ?? '').toString().toLowerCase();
      return name.contains(_searchQuery.toLowerCase()) || 
             sku.contains(_searchQuery) ||
             offerId.contains(_searchQuery.toLowerCase());
    }).toList();
  }

  /// Показ модального окна с историей изменения цен для конкретного товара.
  void _showCostHistory(Map<String, dynamic> product) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (context) => CostHistoryWidget(product: product),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Справочник себестоимости'),
        actions: [
          IconButton(onPressed: _fetchProducts, icon: const Icon(Icons.refresh)),
        ],
      ),
      body: Column(
        children: [
          // Поле поиска товаров
          Padding(
            padding: const EdgeInsets.all(8.0),
            child: TextField(
              decoration: const InputDecoration(
                labelText: 'Поиск по названию, SKU или Offer ID',
                prefixIcon: Icon(Icons.search),
                border: OutlineInputBorder(),
              ),
              onChanged: (val) => setState(() => _searchQuery = val),
            ),
          ),
          Expanded(
            child: _isLoading
                ? const Center(child: CircularProgressIndicator())
                : _filteredProducts.isEmpty
                    ? const Center(child: Text('Товары не найдены'))
                    : ListView.builder(
                        itemCount: _filteredProducts.length,
                        itemBuilder: (context, index) {
                          final p = _filteredProducts[index];
                          final cost = p['current_cost'] ?? 0.0;
                          final hasCost = cost > 0;
                          
                          return ListTile(
                            leading: Container(
                              width: 50,
                              height: 50,
                              decoration: BoxDecoration(
                                color: Colors.grey[200],
                                borderRadius: BorderRadius.circular(8),
                              ),
                              child: p['image_url'] != null && p['image_url'].toString().isNotEmpty
                                  ? ClipRRect(
                                      borderRadius: BorderRadius.circular(8),
                                      child: Image.network(
                                        p['image_url'],
                                        fit: BoxFit.cover,
                                        errorBuilder: (_, __, ___) => const Icon(Icons.image_not_supported),
                                      ),
                                    )
                                  : const Icon(Icons.inventory_2_outlined),
                            ),
                            title: Text(
                              p['name'] ?? 'Без названия',
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold),
                            ),
                            subtitle: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('SKU: ${p['sku']} | Art: ${p['offer_id'] ?? '-'}'),
                                Text(
                                  'Себестоимость: ${cost.toStringAsFixed(2)} руб',
                                  style: TextStyle(
                                    color: hasCost ? Colors.green[700] : Colors.red[700],
                                    fontWeight: hasCost ? FontWeight.bold : FontWeight.normal,
                                  ),
                                ),
                              ],
                            ),
                            trailing: const Icon(Icons.chevron_right),
                            isThreeLine: true,
                            onTap: () => _showCostHistory(p),
                          );
                        },
                      ),
          ),
        ],
      ),
    );
  }
}

/// Виджет для отображения и редактирования истории себестоимости конкретного товара.
class CostHistoryWidget extends StatefulWidget {
  final Map<String, dynamic> product; // Данные о выбранном товаре
  const CostHistoryWidget({super.key, required this.product});

  @override
  State<CostHistoryWidget> createState() => _CostHistoryWidgetState();
}

class _CostHistoryWidgetState extends State<CostHistoryWidget> {
  List<dynamic> _history = []; // Записи об изменении цены во времени
  bool _isLoading = true;      // Состояние загрузки истории

  @override
  void initState() {
    super.initState();
    _fetchHistory();
  }

  /// Получение истории цен с сервера по SKU товара.
  Future<void> _fetchHistory() async {
    setState(() => _isLoading = true);
    try {
      final api = OzonApiClient(authProvider: context.read<AuthProvider>());
      final data = await api.getProductCostHistory(widget.product['sku']);
      setState(() {
        _history = data['items'] ?? [];
        _isLoading = false;
      });
    } catch (e) {
      setState(() => _isLoading = false);
    }
  }

  /// Добавление новой записи о себестоимости с указанием даты начала действия.
  void _addCostEntry() async {
    final TextEditingController priceController = TextEditingController();
    DateTime selectedDate = DateTime.now();

    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Добавить себестоимость'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Ввод цены (себестоимости)
              TextField(
                controller: priceController,
                decoration: const InputDecoration(labelText: 'Цена (руб)'),
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
              ),
              const SizedBox(height: 16),
              // Выбор даты начала действия цены
              ListTile(
                title: const Text('Действует с:'),
                subtitle: Text(DateFormat('yyyy-MM-dd').format(selectedDate)),
                trailing: const Icon(Icons.calendar_today),
                onTap: () async {
                  final picked = await showDatePicker(
                    context: context,
                    initialDate: selectedDate,
                    firstDate: DateTime(2020),
                    lastDate: DateTime(2030),
                  );
                  if (picked != null) {
                    setDialogState(() => selectedDate = picked);
                  }
                },
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Отмена')),
            ElevatedButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Сохранить'),
            ),
          ],
        ),
      ),
    );

    if (confirmed == true && priceController.text.isNotEmpty) {
      try {
        final price = double.parse(priceController.text.replaceAll(',', '.'));
        final api = OzonApiClient(authProvider: context.read<AuthProvider>());
        await api.setProductCost(
          sku: widget.product['sku'],
          offerId: widget.product['offer_id'],
          costPrice: price,
          effectiveFrom: selectedDate,
        );
        _fetchHistory();
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Ошибка: $e')));
        }
      }
    }
  }

  /// Удаление записи из истории себестоимости.
  void _deleteEntry(int id) async {
    final api = OzonApiClient(authProvider: context.read<AuthProvider>());
    await api.deleteProductCost(id);
    _fetchHistory();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      height: MediaQuery.of(context).size.height * 0.7,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Expanded(
                child: Text(
                  widget.product['name'] ?? 'История себестоимости',
                  style: Theme.of(context).textTheme.titleLarge,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              IconButton(onPressed: _addCostEntry, icon: const Icon(Icons.add_circle, color: Colors.green, size: 30)),
            ],
          ),
          Text('SKU: ${widget.product['sku']}', style: const TextStyle(color: Colors.grey)),
          const Divider(),
          Expanded(
            child: _isLoading
                ? const Center(child: CircularProgressIndicator())
                : _history.isEmpty
                    ? const Center(child: Text('История пуста. Добавьте первую цену.'))
                    : ListView.builder(
                        itemCount: _history.length,
                        itemBuilder: (context, index) {
                          final h = _history[index];
                          final date = DateTime.parse(h['effective_from']);
                          return ListTile(
                            leading: const Icon(Icons.attach_money),
                            title: Text('${h['cost_price']} руб'),
                            subtitle: Text('Действует с: ${DateFormat('dd.MM.yyyy').format(date)}'),
                            trailing: IconButton(
                              icon: const Icon(Icons.delete_outline, color: Colors.red),
                              onPressed: () => _deleteEntry(h['id']),
                            ),
                          );
                        },
                      ),
          ),
        ],
      ),
    );
  }
}
