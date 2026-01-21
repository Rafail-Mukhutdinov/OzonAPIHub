import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'services/api.dart';
import 'widgets/sales_table.dart';
import 'widgets/sales_chart.dart';

void main() {
  // Инициализировать русскую локаль для форматирования дат
  initializeDateFormatting('ru_RU', null).then((_) {
    runApp(const MyApp());
  });
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Ozon Sales Dashboard',
      theme: ThemeData(colorSchemeSeed: Colors.blue, useMaterial3: true),
      home: const SalesDashboard(),
    );
  }
}

class SalesDashboard extends StatefulWidget {
  const SalesDashboard({super.key});
  @override
  State<SalesDashboard> createState() => _SalesDashboardState();
}

class _SalesDashboardState extends State<SalesDashboard> {
  final api = OzonApiClient();
  bool delivered = false;
  DateTime since = DateTime.now().subtract(const Duration(days: 2));
  DateTime to = DateTime.now();
  bool loading = false;
  List<Map<String, dynamic>> items = [];
  Map<String, dynamic>? totals;
  String? error;
  String? selectedStatus;
  
  // Для графика - используем комбо offer_id|sku как идентификатор
  List<String> selectedChartItems = []; // "offer_id|sku"
  Map<String, List<Map<String, dynamic>>> chartDataByItem = {};
  bool chartLoading = false;
  String? chartError;
  
  // Режим отображения графика: 'delivered' (финансы) или 'shipped' (отгрузки)
  String chartMode = 'delivered';

  String _fmt(DateTime dt) =>
      DateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'").format(dt.toUtc());

  String _fmtUi(DateTime dt) => DateFormat("d MMM y", "ru_RU").format(dt);

  Future<void> _load() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final qs = {'since': _fmt(since), 'to': _fmt(to)};
      final data = delivered
          ? await api.getSalesRange(since: qs['since']!, to: qs['to']!, status: selectedStatus)
          : await api.getSalesRaw(since: qs['since']!, to: qs['to']!, status: selectedStatus);
      final list = (data['items'] as List).cast<Map<String, dynamic>>();
      setState(() {
        items = list;
        totals = data;
      });
    } catch (e) {
      setState(() {
        error = e.toString();
      });
    } finally {
      setState(() {
        loading = false;
      });
    }
  }

  Future<void> _pickDate(BuildContext ctx, bool isSince) async {
    final init = isSince ? since : to;
    final picked = await showDatePicker(
      context: ctx,
      initialDate: init,
      firstDate: DateTime(2024, 1, 1),
      lastDate: DateTime.now().add(const Duration(days: 1)),
    );
    if (picked != null) {
      setState(() {
        if (isSince) {
          since = DateTime(picked.year, picked.month, picked.day, 0, 0);
        } else {
          to = DateTime(picked.year, picked.month, picked.day, 23, 59, 59);
        }
      });
    }
  }

  Future<void> _loadChart(String offerId, String sku) async {
    final itemKey = '$offerId|$sku';
    setState(() {
      chartLoading = true;
      chartError = null;
      if (!selectedChartItems.contains(itemKey)) {
        selectedChartItems.add(itemKey);
      }
    });
    try {
      final data = await api.getSalesBySkuMonthly(
        offerId: offerId,
        sku: sku,
        monthsBack: 12,
        mode: chartMode,
      );
      final list = (data['data'] as List).cast<Map<String, dynamic>>();
      setState(() {
        chartDataByItem[itemKey] = list;
      });
    } catch (e) {
      setState(() {
        chartError = e.toString();
      });
    } finally {
      setState(() {
        chartLoading = false;
      });
    }
  }

  void _switchChartMode(String newMode) {
    if (chartMode == newMode) return;
    setState(() {
      chartMode = newMode;
    });
    // Перезагружаем данные для всех уже выбранных товаров
    for (var itemKey in selectedChartItems) {
      final parts = itemKey.split('|');
      if (parts.length == 2) {
        _loadChart(parts[0], parts[1]);
      }
    }
  }

  void _removeChartItem(String itemKey) {
    setState(() {
      selectedChartItems.remove(itemKey);
      chartDataByItem.remove(itemKey);
    });
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  String _statusRu(String code) {
    switch (code) {
      case 'awaiting_assembly':
        return 'Ожидает сборки';
      case 'awaiting_packaging':
        return 'Ожидает упаковки';
      case 'awaiting_deliver':
        return 'Ожидает отгрузки';
      case 'delivering':
        return 'Доставляется';
      case 'delivered':
        return 'Доставлен';
      case 'cancelled':
        return 'Отменён';
      default:
        return code;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Ozon Sales Dashboard'),
        actions: [
          Row(
            children: [
              const Text('Delivered'),
              Switch(
                value: delivered,
                onChanged: (v) => setState(() => delivered = v),
              ),
            ],
          ),
          IconButton(icon: const Icon(Icons.refresh), onPressed: _load),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 12,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text('С: ${_fmtUi(since)}'),
                ElevatedButton(
                  onPressed: () => _pickDate(context, true),
                  child: const Text('Изменить'),
                ),
                Text('По: ${_fmtUi(to)}'),
                ElevatedButton(
                  onPressed: () => _pickDate(context, false),
                  child: const Text('Изменить'),
                ),
                ElevatedButton(onPressed: _load, child: const Text('Обновить')),
              ],
            ),
            const SizedBox(height: 12),
            if (totals != null && totals!['by_status'] is List)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Wrap(
                  spacing: 4,
                  runSpacing: 8,
                  children: [
                    FilterChip(
                      label: const Text('Все статусы'),
                      selected: selectedStatus == null,
                      onSelected: (_) => setState(() => selectedStatus = null),
                    ),
                    ...(totals!['by_status'] as List)
                        .cast<Map<String, dynamic>>()
                        .map(
                          (s) => FilterChip(
                            label: Text(
                              '${_statusRu('${s['status']}')}: ${s['count']}',
                            ),
                            selected: selectedStatus == '${s['status']}',
                            onSelected: (isSelected) {
                              setState(() {
                                selectedStatus = isSelected ? '${s['status']}' : null;
                              });
                              _load();
                            },
                          ),
                        )
                        .toList(),
                  ],
                ),
              ),
            if (loading) const LinearProgressIndicator(),
            if (error != null)
              Text('Ошибка: $error', style: const TextStyle(color: Colors.red)),
            Expanded(
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SalesTable(
                      items: items,
                      delivered: delivered,
                      totals: totals,
                    ),
                    const SizedBox(height: 32),
                    if (items.isNotEmpty) ...[
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                const Text(
                                  '📊 Динамика по месяцам',
                                  style: TextStyle(
                                    fontSize: 18,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                                // Переключатель режимов
                                SegmentedButton<String>(
                                  segments: const [
                                    ButtonSegment(
                                      value: 'delivered',
                                      label: Text('Финансы'),
                                      icon: Icon(Icons.paid),
                                    ),
                                    ButtonSegment(
                                      value: 'shipped',
                                      label: Text('Отгрузки'),
                                      icon: Icon(Icons.local_shipping),
                                    ),
                                  ],
                                  selected: {chartMode},
                                  onSelectionChanged: (Set<String> newSelection) {
                                    _switchChartMode(newSelection.first);
                                  },
                                  showSelectedIcon: false,
                                ),
                              ],
                            ),
                            const SizedBox(height: 12),
                            Wrap(
                              spacing: 8,
                              runSpacing: 8,
                              children: [
                                ...items.take(10).map((item) {
                                  final offerId = '${item['offer_id'] ?? ''}';
                                  final sku = '${item['sku'] ?? ''}';
                                  final itemKey = '$offerId|$sku';
                                  final label = offerId.isNotEmpty ? offerId : sku;
                                  final isSelected = selectedChartItems.contains(itemKey);
                                  return FilterChip(
                                    label: Text(label),
                                    selected: isSelected,
                                    onSelected: (isSelected) {
                                      if (isSelected) {
                                        _loadChart(offerId, sku);
                                      } else {
                                        _removeChartItem(itemKey);
                                      }
                                    },
                                  );
                                }).toList(),
                              ],
                            ),
                            if (chartLoading)
                              const Padding(
                                padding: EdgeInsets.only(top: 16),
                                child: CircularProgressIndicator(),
                              ),
                            if (chartError != null)
                              Padding(
                                padding: const EdgeInsets.only(top: 16),
                                child: Text(
                                  'Ошибка графика: $chartError',
                                  style: const TextStyle(color: Colors.red),
                                ),
                              ),
                            if (selectedChartItems.isNotEmpty &&
                                chartDataByItem.isNotEmpty &&
                                !chartLoading)
                              Padding(
                                padding: const EdgeInsets.only(top: 16),
                                child: SalesChart(
                                  chartDataByItem: chartDataByItem,
                                  selectedItems: selectedChartItems,
                                  onRemoveItem: _removeChartItem,
                                ),
                              ),
                          ],
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
