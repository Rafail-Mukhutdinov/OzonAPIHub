import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'services/api.dart';
import 'widgets/sales_table.dart';
import 'widgets/sales_chart.dart';

void main() {
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
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      supportedLocales: const [
        Locale('en', 'US'),
        Locale('ru', 'RU'),
      ],
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

  // Глобальный режим просмотра: 'delivered' (Финансы) или 'shipped' (Отгрузки)
  // Заменяет собой и bool delivered, и chartMode
  String viewMode = 'delivered';

  DateTime since = DateTime.now().subtract(const Duration(days: 2));
  DateTime to = DateTime.now();
  bool loading = false;
  List<Map<String, dynamic>> items = [];
  Map<String, dynamic>? totals;
  String? error;
  String? selectedStatus;

  // Для графика
  List<String> selectedChartItems = []; // "offer_id|sku"
  Map<String, List<Map<String, dynamic>>> chartDataByItem = {};
  bool chartLoading = false;
  String? chartError;

  // Формат даты для API (UTC)
  String _fmtApi(DateTime dt) =>
      DateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'").format(dt.toUtc());

  // Формат даты для UI (Русский)
  String _fmtUi(DateTime dt) => DateFormat("d MMM y", "ru_RU").format(dt);

  @override
  void initState() {
    super.initState();
    _load();
  }

  // Загрузка таблицы и итогов (зависит от viewMode)
  Future<void> _load() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final qs = {'since': _fmtApi(since), 'to': _fmtApi(to)};
      
      // Единая логика:
      // delivered -> sales_range (финансы)
      // shipped   -> sales_today_raw (операционка)
      final data = (viewMode == 'delivered')
          ? await api.getSalesRange(
              since: qs['since']!,
              to: qs['to']!,
              status: selectedStatus)
          : await api.getSalesRaw(
              since: qs['since']!,
              to: qs['to']!,
              status: selectedStatus);

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

  // Загрузка одного графика (зависит от viewMode)
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
        mode: viewMode, // Передаем глобальный режим
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

  // Переключение глобального режима
  void _switchViewMode(String newMode) {
    if (viewMode == newMode) return;
    setState(() {
      viewMode = newMode;
    });
    
    // 1. Перезагружаем таблицу
    _load();
    
    // 2. Перезагружаем все открытые графики
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

  Future<void> _pickDate(BuildContext ctx, bool isSince) async {
    final init = isSince ? since : to;
    final picked = await showDatePicker(
      context: ctx,
      initialDate: init,
      firstDate: DateTime(2024, 1, 1),
      lastDate: DateTime.now().add(const Duration(days: 1)),
      locale: const Locale("ru", "RU"),
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

  String _statusRu(String code) {
    switch (code) {
      case 'awaiting_assembly': return 'Ожидает сборки';
      case 'awaiting_packaging': return 'Ожидает упаковки';
      case 'awaiting_deliver': return 'Ожидает отгрузки';
      case 'delivering': return 'Доставляется';
      case 'delivered': return 'Доставлен';
      case 'cancelled': return 'Отменён';
      default: return code;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Ozon Dashboard'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _load),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // ГЛОБАЛЬНЫЙ ПЕРЕКЛЮЧАТЕЛЬ РЕЖИМОВ
            Center(
              child: SegmentedButton<String>(
                segments: const [
                  ButtonSegment(
                    value: 'delivered',
                    label: Text('Финансы (Доставлено)'),
                    icon: Icon(Icons.paid),
                  ),
                  ButtonSegment(
                    value: 'shipped',
                    label: Text('Отгрузки (В работе)'),
                    icon: Icon(Icons.local_shipping),
                  ),
                ],
                selected: {viewMode},
                onSelectionChanged: (Set<String> newSelection) {
                  _switchViewMode(newSelection.first);
                },
                showSelectedIcon: false,
                style: ButtonStyle(
                  visualDensity: VisualDensity.compact,
                ),
              ),
            ),
            const SizedBox(height: 16),
            
            // Выбор дат
            Wrap(
              spacing: 12,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                OutlinedButton.icon(
                  onPressed: () => _pickDate(context, true),
                  icon: const Icon(Icons.calendar_today, size: 16),
                  label: Text('С: ${_fmtUi(since)}'),
                ),
                const Text('—'),
                OutlinedButton.icon(
                  onPressed: () => _pickDate(context, false),
                  icon: const Icon(Icons.calendar_today, size: 16),
                  label: Text('По: ${_fmtUi(to)}'),
                ),
                ElevatedButton(onPressed: _load, child: const Text('Обновить')),
              ],
            ),
            
            const SizedBox(height: 12),
            
            // Фильтр статусов (только если есть данные)
            if (totals != null && totals!['by_status'] is List)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    FilterChip(
                      label: const Text('Все статусы'),
                      selected: selectedStatus == null,
                      onSelected: (_) {
                        setState(() => selectedStatus = null);
                        _load();
                      },
                    ),
                    ...(totals!['by_status'] as List)
                        .cast<Map<String, dynamic>>()
                        .map(
                          (s) => FilterChip(
                            label: Text('${_statusRu('${s['status']}')}: ${s['count']}'),
                            selected: selectedStatus == '${s['status']}',
                            onSelected: (isSelected) {
                              setState(() {
                                selectedStatus = isSelected ? '${s['status']}' : null;
                              });
                              _load();
                            },
                          ),
                        ).toList(),
                  ],
                ),
              ),

            if (loading) const LinearProgressIndicator(),
            if (error != null)
              Text('Ошибка: $error', style: const TextStyle(color: Colors.red)),

            const SizedBox(height: 12),

            // Основной контент (Таблица + Графики)
            Expanded(
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SalesTable(
                      items: items,
                      // Таблица сама решит, какие колонки показывать, на основе этого флага
                      delivered: viewMode == 'delivered',
                      totals: totals,
                    ),
                    
                    const SizedBox(height: 32),
                    
                    // Блок графиков
                    if (items.isNotEmpty) ...[
                      const Text(
                        '📊 Динамика по месяцам',
                        style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        viewMode == 'delivered' 
                          ? 'Режим: Финансы (Дата доставки)' 
                          : 'Режим: Отгрузки (Дата обработки)',
                        style: TextStyle(fontSize: 12, color: Colors.grey[600]),
                      ),
                      const SizedBox(height: 12),
                      
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: items.take(15).map((item) {
                          final offerId = '${item['offer_id'] ?? ''}';
                          final sku = '${item['sku'] ?? ''}';
                          final itemKey = '$offerId|$sku';
                          // Показываем offer_id, если есть, иначе sku
                          final label = offerId.isNotEmpty ? offerId : sku;
                          final isSelected = selectedChartItems.contains(itemKey);
                          
                          return FilterChip(
                            label: Text(label),
                            selected: isSelected,
                            onSelected: (v) {
                              if (v) {
                                _loadChart(offerId, sku);
                              } else {
                                _removeChartItem(itemKey);
                              }
                            },
                          );
                        }).toList(),
                      ),
                      
                      if (chartLoading)
                        const Padding(
                          padding: EdgeInsets.only(top: 16),
                          child: Center(child: CircularProgressIndicator()),
                        ),
                        
                      if (chartError != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 16),
                          child: Text('Ошибка графика: $chartError', 
                            style: const TextStyle(color: Colors.red)),
                        ),
                        
                      if (selectedChartItems.isNotEmpty && chartDataByItem.isNotEmpty && !chartLoading)
                        Padding(
                          padding: const EdgeInsets.only(top: 16, bottom: 40),
                          child: SalesChart(
                            chartDataByItem: chartDataByItem,
                            selectedItems: selectedChartItems,
                            onRemoveItem: _removeChartItem,
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
