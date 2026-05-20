import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import 'dart:async';
import '../services/api.dart';
import '../providers/auth_provider.dart';
import '../widgets/sales_table.dart';
import '../widgets/sales_chart.dart';
import 'login_screen.dart';
import 'settings_screen.dart';
import 'shipments_screen.dart'; // Добавляем импорт нового экрана

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});
  
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  late final OzonApiClient api;

  // Глобальный режим просмотра: 'delivered' (Финансы) или 'shipped' (Отгрузки)
  String viewMode = 'delivered';

  DateTime since = DateTime.now().subtract(const Duration(days: 2));
  DateTime to = DateTime.now();
  bool loading = false;
  List<Map<String, dynamic>> items = [];
  Map<String, dynamic>? totals;
  String? error;
  String? selectedStatus;
  int _loadSeq = 0;

  // Статус синхронизации (для отслеживания полной загрузки)
  bool syncInProgress = false;
  String syncMessage = "";
  Timer? syncStatusTimer;

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
    
    // Создаем API клиент с callback для обработки 401
    api = OzonApiClient(
      onUnauthorized: _handleUnauthorized,
    );
    
    // Загружаем данные безопасно
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _load();
      _startSyncStatusCheck();
    });
  }

  /// Запускает периодическую проверку статуса синхронизации (каждые 2 секунды)
  void _startSyncStatusCheck() {
    syncStatusTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      _checkSyncStatus();
    });
    // Первый раз сразу же
    _checkSyncStatus();
  }

  /// Проверяет статус синхронизации данных
  Future<void> _checkSyncStatus() async {
    if (!mounted) return;
    try {
      final status = await api.getSyncStatus();
      if (!mounted) return;
      
      setState(() {
        syncInProgress = status['is_syncing'] ?? false;
        syncMessage = status['status_message'] ?? '';
      });
    } catch (e) {
      // Ошибка при получении статуса - игнорируем
      if (kDebugMode) {
        print('Ошибка при проверке статуса синхронизации: $e');
      }
    }
  }

  @override
  void dispose() {
    syncStatusTimer?.cancel();
    super.dispose();
  }

  // Обработка разлогинивания при 401
  void _handleUnauthorized() {
    if (!mounted) return;
    
    // Показываем сообщение и перенаправляем на экран входа
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Сессия истекла. Пожалуйста, войдите снова.'),
        backgroundColor: Colors.red,
      ),
    );
    
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
    );
  }

  // Выход из системы
  Future<void> _handleLogout() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Выход'),
        content: const Text('Вы уверены, что хотите выйти?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Выйти'),
          ),
        ],
      ),
    );

    if (confirmed == true && mounted) {
      // Используем Provider для выхода
      final authProvider = Provider.of<AuthProvider>(context, listen: false);
      await authProvider.logout();
      
      if (mounted) {
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (_) => const LoginScreen()),
        );
      }
    }
  }

  // Загрузка таблицы и итогов
  Future<void> _load() async {
    if (!mounted) return;
    final int loadSeq = ++_loadSeq;
    final String modeAtCall = viewMode;
    final String? statusAtCall = selectedStatus;
    final DateTime sinceAtCall = since;
    final DateTime toAtCall = to;
    
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final qs = {'since': _fmtApi(since), 'to': _fmtApi(to)};
      
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
      if (!mounted || loadSeq != _loadSeq) return;
      if (modeAtCall != viewMode || statusAtCall != selectedStatus || sinceAtCall != since || toAtCall != to) return;
      if (mounted) {
        setState(() {
          items = list;
          totals = data;
        });
      }
    } catch (e) {
      if (mounted && loadSeq == _loadSeq) {
        setState(() {
          error = e.toString();
        });
      }
    } finally {
      if (mounted && loadSeq == _loadSeq) {
        setState(() {
          loading = false;
        });
      }
    }
  }

  // Загрузка графика
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
        mode: viewMode,
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

  // Переключение режима
  void _switchViewMode(String newMode) {
    if (viewMode == newMode) return;
    setState(() {
      viewMode = newMode;
      selectedStatus = null;
      items = [];
      totals = null;
    });
    
    _load();
    
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
          IconButton(
            icon: const Icon(Icons.inventory),
            onPressed: () {
              Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const ShipmentsScreen()),
              );
            },
            tooltip: 'Отгрузки',
          ),
          IconButton(
            icon: const Icon(Icons.settings),
            onPressed: () {
              Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const SettingsScreen()),
              );
            },
            tooltip: 'Настройки',
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _load,
            tooltip: 'Обновить',
          ),
          IconButton(
            icon: const Icon(Icons.logout),
            onPressed: _handleLogout,
            tooltip: 'Выход',
          ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Статус синхронизации (только если идет загрузка)
            if (syncInProgress)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Card(
                  color: Colors.blue.shade50,
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Row(
                      children: [
                        const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(
                            syncMessage,
                            style: const TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w500,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            
            // Если синхронизация завершена и было "Данные загружены" - показываем зеленое уведомление
            if (!syncInProgress && syncMessage == "Данные загружены")
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Card(
                  color: Colors.green.shade50,
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Row(
                      children: [
                        Icon(Icons.check_circle, color: Colors.green.shade700, size: 20),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(
                            'Данные загружены',
                            style: TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w500,
                              color: Colors.green.shade700,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            
            // Переключатель режимов
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
            
            // Фильтр статусов
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
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.red.shade50,
                  border: Border.all(color: Colors.red.shade200),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Ошибка загрузки данных',
                      style: TextStyle(
                        color: Colors.red.shade900,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      error!,
                      style: TextStyle(color: Colors.red.shade700),
                    ),
                    const SizedBox(height: 12),
                    if (error!.contains('connection') || error!.contains('No credentials'))
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            '💡 Совет:',
                            style: TextStyle(fontWeight: FontWeight.bold, color: Colors.orange),
                          ),
                          const SizedBox(height: 4),
                          const Text('1. Добавьте API ключ Ozon в Настройках (иконка ⚙️)'),
                          const SizedBox(height: 4),
                          const Text('2. Нажмите кнопку "Обновить" '),
                          const SizedBox(height: 12),
                          ElevatedButton.icon(
                            onPressed: () {
                              Navigator.of(context).push(
                                MaterialPageRoute(
                                  builder: (_) => const SettingsScreen(),
                                ),
                              );
                            },
                            icon: const Icon(Icons.settings),
                            label: const Text('Перейти в Настройки'),
                          ),
                        ],
                      ),
                  ],
                ),
              ),

            const SizedBox(height: 12),

            // Таблица и графики
            Expanded(
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SalesTable(
                      items: items,
                      delivered: viewMode == 'delivered',
                      totals: totals,
                    ),
                    
                    const SizedBox(height: 32),
                    
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
