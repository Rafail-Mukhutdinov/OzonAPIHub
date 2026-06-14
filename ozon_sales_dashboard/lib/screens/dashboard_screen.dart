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
import 'shipments_screen.dart';

/**
 * DashboardScreen — главный экран приложения.
 * Здесь отображается аналитика продаж, таблицы с товарами и графики динамики.
 */
class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});
  
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  late final OzonApiClient api;

  // Режим просмотра: 
  // 'delivered' — Финансы (анализ только доставленных и оплаченных заказов)
  // 'shipped' — Отгрузки (анализ всех заказов в работе)
  String viewMode = 'delivered';

  // Временной диапазон фильтрации (по умолчанию — последние 2 дня)
  DateTime since = DateTime.now().subtract(const Duration(days: 2));
  DateTime to = DateTime.now();
  
  bool loading = false;
  List<Map<String, dynamic>> items = []; // Список товаров из отчета
  Map<String, dynamic>? totals;        // Итоговые суммы (выручка, заказы)
  String? error;
  String? selectedStatus;              // Выбранный фильтр по статусу (Чипы)
  int _loadSeq = 0;                    // Счетчик запросов для предотвращения Race Condition

  // Состояние синхронизации истории (Backfill)
  bool syncInProgress = false;
  bool userDismissedSync = false;
  String syncMessage = "";
  Timer? syncStatusTimer;
  bool _wasSyncing = false; 
  bool _isFirstCheck = true; 
  bool _showSuccessBanner = false; 

  // Состояние графиков
  List<String> selectedChartItems = []; // Список выбранных SKU для сравнения на графике
  Map<String, List<Map<String, dynamic>>> chartDataByItem = {}; // Данные графиков по SKU
  bool chartLoading = false;
  String? chartError;

  // Форматирование даты для бэкенда (ISO 8601 UTC)
  String _fmtApi(DateTime dt) =>
      DateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'").format(dt.toUtc());

  // Форматирование даты для пользователя
  String _fmtUi(DateTime dt) => DateFormat("d MMM y", "ru_RU").format(dt);

  @override
  void initState() {
    super.initState();
    
    // Инициализация API-клиента с привязкой к AuthProvider для разлогина
    api = OzonApiClient(
      onUnauthorized: _handleUnauthorized,
    );
    
    // Запускаем загрузку данных сразу после отрисовки экрана
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _load();
      _startSyncStatusCheck();
    });
  }

  /// Циклическая проверка прогресса загрузки истории заказов.
  void _startSyncStatusCheck() {
    syncStatusTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      _checkSyncStatus();
    });
    _checkSyncStatus();
  }

  /// Опрашивает бэкенд о статусе фоновой задачи синхронизации.
  Future<void> _checkSyncStatus() async {
    if (!mounted) return;
    try {
      final status = await api.getSyncStatus();
      if (!mounted) return;
      
      setState(() {
        final isSyncing = status['is_syncing'] ?? false;
        syncMessage = status['status_message'] ?? '';
        
        // Управление логикой показа уведомлений о синхронизации
        if (_isFirstCheck) {
          _isFirstCheck = false;
          if (isSyncing) {
            userDismissedSync = false;
            _wasSyncing = true;
          } else {
            userDismissedSync = true;
          }
        }

        if (isSyncing) {
          if (!_wasSyncing) {
            _wasSyncing = true;
            userDismissedSync = false; 
          }
          syncInProgress = !userDismissedSync;
          _showSuccessBanner = false;
        } else {
          syncInProgress = false;
          if (_wasSyncing) {
            _wasSyncing = false; 
            // Если загрузка успешно завершилась — обновляем таблицу и показываем успех
            if (!syncMessage.toLowerCase().contains('error')) {
              _showSuccessBanner = true;
              userDismissedSync = false; 
              _load(); // Авто-рефреш данных после синхронизации

              // Скрываем плашку успеха через 6 секунд
              Future.delayed(const Duration(seconds: 6), () {
                if (mounted) setState(() => _showSuccessBanner = false);
              });
            }
          }
        }
      });
    } catch (e) {
      if (kDebugMode) print('Sync check error: $e');
    }
  }

  @override
  void dispose() {
    syncStatusTimer?.cancel(); // Останавливаем таймер при закрытии экрана
    super.dispose();
  }

  /// Обработка ситуации, когда токен протух.
  void _handleUnauthorized() {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Сессия истекла'), backgroundColor: Colors.red),
    );
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
    );
  }

  /// Логика выхода из аккаунта.
  Future<void> _handleLogout() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Выход'),
        content: const Text('Выйти из системы?'),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('Отмена')),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: const Text('Выйти')),
        ],
      ),
    );

    if (confirmed == true && mounted) {
      await Provider.of<AuthProvider>(context, listen: false).logout();
      if (mounted) Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const LoginScreen()));
    }
  }

  /// Загрузка данных аналитики (таблица и итоги).
  Future<void> _load() async {
    if (!mounted) return;
    final int loadSeq = ++_loadSeq; // Метка текущего запроса
    
    setState(() {
      loading = true;
      error = null;
    });

    try {
      // Вызываем соответствующий эндпоинт бэкенда
      final data = (viewMode == 'delivered')
          ? await api.getSalesRange(since: _fmtApi(since), to: _fmtApi(to), status: selectedStatus)
          : await api.getSalesRaw(since: _fmtApi(since), to: _fmtApi(to), status: selectedStatus);

      final list = (data['items'] as List).cast<Map<String, dynamic>>();
      
      // Если пришел ответ от "старого" запроса (пользователь уже нажал что-то другое) — игнорируем
      if (!mounted || loadSeq != _loadSeq) return;

      setState(() {
        items = list;
        totals = data;
      });
    } catch (e) {
      if (mounted && loadSeq == _loadSeq) setState(() => error = e.toString());
    } finally {
      if (mounted && loadSeq == _loadSeq) setState(() => loading = false);
    }
  }

  /// Загрузка данных для линейного графика конкретного SKU.
  Future<void> _loadChart(String offerId, String sku) async {
    final itemKey = '$offerId|$sku';
    setState(() {
      chartLoading = true;
      if (!selectedChartItems.contains(itemKey)) selectedChartItems.add(itemKey);
    });
    try {
      final data = await api.getSalesBySkuMonthly(offerId: offerId, sku: sku, mode: viewMode);
      final list = (data['data'] as List).cast<Map<String, dynamic>>();
      setState(() => chartDataByItem[itemKey] = list);
    } catch (e) {
      setState(() => chartError = e.toString());
    } finally {
      setState(() => chartLoading = false);
    }
  }

  /// Переключение вкладок "Финансы" / "Отгрузки".
  void _switchViewMode(String newMode) {
    if (viewMode == newMode) return;
    setState(() {
      viewMode = newMode;
      selectedStatus = null; // Сбрасываем фильтр статуса при смене режима
      items = [];
      totals = null;
    });
    _load();
    
    // Обновляем графики для нового режима (delivered/shipped)
    for (var itemKey in selectedChartItems) {
      final parts = itemKey.split('|');
      if (parts.length == 2) _loadChart(parts[0], parts[1]);
    }
  }

  void _removeChartItem(String itemKey) {
    setState(() {
      selectedChartItems.remove(itemKey);
      chartDataByItem.remove(itemKey);
    });
  }

  /// Выбор даты через стандартный DatePicker.
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
      _load(); // Авто-обновление после смены даты
    }
  }

  // Перевод статусов Ozon на русский
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
          IconButton(icon: const Icon(Icons.inventory), onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ShipmentsScreen())), tooltip: 'Отгрузки'),
          IconButton(icon: const Icon(Icons.settings), onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SettingsScreen())), tooltip: 'Настройки'),
          IconButton(icon: const Icon(Icons.refresh), onPressed: _load, tooltip: 'Обновить'),
          IconButton(icon: const Icon(Icons.logout), onPressed: _handleLogout, tooltip: 'Выход'),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Синий баннер: идет синхронизация истории
            if (syncInProgress)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Card(
                  color: Colors.blue.shade50,
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Row(
                      children: [
                        const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)),
                        const SizedBox(width: 12),
                        Expanded(child: Text(syncMessage, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500))),
                        IconButton(icon: const Icon(Icons.close, size: 20), onPressed: () => setState(() { userDismissedSync = true; syncInProgress = false; })),
                      ],
                    ),
                  ),
                ),
              ),
            
            // Зеленый баннер: синхронизация завершена
            if (_showSuccessBanner && !userDismissedSync)
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
                        Expanded(child: Text('Данные синхронизированы', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w500, color: Colors.green.shade700))),
                        IconButton(icon: Icon(Icons.close, color: Colors.green.shade700, size: 20), onPressed: () => setState(() { _showSuccessBanner = false; userDismissedSync = true; })),
                      ],
                    ),
                  ),
                ),
              ),
            
            // Переключатель режимов Финансы/Склад
            Center(
              child: SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'delivered', label: Text('Финансы'), icon: Icon(Icons.paid)),
                  ButtonSegment(value: 'shipped', label: Text('Склад'), icon: Icon(Icons.local_shipping)),
                ],
                selected: {viewMode},
                onSelectionChanged: (newSelection) => _switchViewMode(newSelection.first),
                showSelectedIcon: false,
              ),
            ),
            const SizedBox(height: 16),
            
            // Фильтры по датам
            Wrap(
              spacing: 12, runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                OutlinedButton.icon(onPressed: () => _pickDate(context, true), icon: const Icon(Icons.calendar_today, size: 16), label: Text('С: ${_fmtUi(since)}')),
                const Text('—'),
                OutlinedButton.icon(onPressed: () => _pickDate(context, false), icon: const Icon(Icons.calendar_today, size: 16), label: Text('По: ${_fmtUi(to)}')),
                ElevatedButton(onPressed: _load, child: const Text('Обновить')),
              ],
            ),
            
            const SizedBox(height: 12),
            
            // Статус-фильтры (Chips)
            if (totals != null && totals!['by_status'] is List)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Wrap(
                  spacing: 6, runSpacing: 6,
                  children: [
                    FilterChip(label: const Text('Все'), selected: selectedStatus == null, onSelected: (_) { setState(() => selectedStatus = null); _load(); }),
                    ...(totals!['by_status'] as List).cast<Map<String, dynamic>>().map((s) => FilterChip(
                      label: Text('${_statusRu('${s['status']}')}: ${s['count']}'),
                      selected: selectedStatus == '${s['status']}',
                      onSelected: (isSelected) { setState(() => selectedStatus = isSelected ? '${s['status']}' : null); _load(); },
                    )).toList(),
                  ],
                ),
              ),

            if (loading) const LinearProgressIndicator(),
            
            // Сообщения об ошибках
            if (error != null)
              Container(
                margin: const EdgeInsets.symmetric(vertical: 8),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: Colors.red.shade50, borderRadius: BorderRadius.circular(8), border: Border.all(color: Colors.red.shade200)),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Ошибка загрузки данных', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.red)),
                    const SizedBox(height: 4),
                    Text(error!, style: const TextStyle(fontSize: 13)),
                    if (error!.contains('credentials')) ...[
                      const SizedBox(height: 8),
                      TextButton.icon(onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SettingsScreen())), icon: const Icon(Icons.settings), label: const Text('Перейти в настройки'))
                    ]
                  ],
                ),
              ),

            const SizedBox(height: 12),

            // Основной контент: Таблица товаров и Графики
            Expanded(
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SalesTable(items: items, delivered: viewMode == 'delivered', totals: totals),
                    
                    const SizedBox(height: 32),
                    
                    if (items.isNotEmpty) ...[
                      const Text('📊 Динамика продаж (12 мес)', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 12),
                      
                      // Выбор SKU для отображения на графике
                      Wrap(
                        spacing: 8, runSpacing: 8,
                        children: items.take(15).map((item) {
                          final offerId = '${item['offer_id'] ?? ''}';
                          final sku = '${item['sku'] ?? ''}';
                          final itemKey = '$offerId|$sku';
                          return FilterChip(
                            label: Text(offerId.isNotEmpty ? offerId : sku),
                            selected: selectedChartItems.contains(itemKey),
                            onSelected: (v) => v ? _loadChart(offerId, sku) : _removeChartItem(itemKey),
                          );
                        }).toList(),
                      ),
                      
                      if (chartLoading) const Padding(padding: EdgeInsets.only(top: 16), child: Center(child: CircularProgressIndicator())),
                        
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
