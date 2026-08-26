import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'dart:async';
import 'package:dio/dio.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../services/api.dart';
import '../widgets/mobile_dashboard_view.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import 'shipments_screen.dart';
import 'settings_screen.dart';
import 'admin_dashboard_screen.dart';
import 'product_costs_screen.dart';

/// Основной экран дашборда приложения.
/// Отображает аналитику продаж, графики и список популярных товаров.
class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  late final OzonApiClient api; // Клиент для работы с API
  String _appVersion = '...'; // Версия приложения для отображения в Drawer
  
  // ЕДИНОЕ СОСТОЯНИЕ ДЛЯ ВСЕХ ВЕРСИЙ
  String selectedPeriod = 'today'; // Выбранный период: today, week, month, custom
  String selectedScheme = 'fbo'; // Схема работы: fbo, fbs, all
  bool isFbsBackfillComplete = true; // Флаг завершения загрузки исторических данных FBS
  DateTime activeDate = DateTime.now(); // Текущая активная дата для отчетов
  DateTime? drillDownDate; // Дата для детального просмотра (если выбрана на графике)
  DateTime? _lastStatusUpdate; // Время последнего успешного обновления статуса

  // РЕЖИМЫ ПЕРИОДОВ (сохраняются во время сессии)
  String weekMode = 'rolling'; // Режим недели: 'rolling' (последние 7 дней) или 'calendar' (с Пн)
  String monthMode = 'calendar'; // Режим месяца: 'calendar' (с 1-го числа) или 'rolling' (последние 30 дней)
  DateTimeRange? customRange; // Произвольный диапазон дат

  List<Map<String, dynamic>> items = []; // Список товаров за выбранный период
  Map<String, dynamic>? totals; // Итоговые показатели за текущий период
  Map<String, dynamic>? yesterdayTotals; // Итоговые показатели за предыдущий аналогичный период
  List<Map<String, dynamic>> weeklyStats = []; // Данные для построения графика динамики
  bool loading = false; // Флаг процесса загрузки данных
  Timer? _autoRefreshTimer; // Таймер для автоматического обновления данных

  @override
  void initState() {
    super.initState();
    // Инициализация API клиента и загрузка начальных данных
    final auth = Provider.of<AuthProvider>(context, listen: false);
    api = OzonApiClient(authProvider: auth);
    _loadSettings().then((_) => _loadAllData(forceRefreshStatus: true));
    _initPackageInfo();
    // Настройка периодического обновления данных каждые 5 минут.
    // Троттлинг в 30 сек позволит таймеру обновить статус, даже без force.
    _autoRefreshTimer = Timer.periodic(const Duration(minutes: 5), (_) => _loadAllData(isSilent: true));
  }

  /// Загрузка настроек пользователя (выбранная схема) из SharedPreferences.
  Future<void> _loadSettings() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final scheme = prefs.getString('selected_scheme');
      if (scheme != null && (scheme == 'fbo' || scheme == 'fbs')) {
        setState(() {
          selectedScheme = scheme;
        });
      }
    } catch (e) {
      debugPrint('Error loading settings: $e');
    }
  }

  /// Сохранение выбранной схемы в локальное хранилище.
  Future<void> _saveScheme(String scheme) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      if (scheme == 'all') {
        await prefs.remove('selected_scheme');
      } else {
        await prefs.setString('selected_scheme', scheme);
      }
    } catch (e) {
      debugPrint('Error saving scheme: $e');
    }
  }

  /// Обновление данных профиля и статуса синхронизации.
  Future<void> _refreshProfile({bool force = false}) async {
    // 🟡 Троттлинг: обновляем статус не чаще раза в 30 секунд, 
    // если баннер уже скрыт и это не принудительное обновление.
    final now = DateTime.now();
    if (!force && isFbsBackfillComplete && _lastStatusUpdate != null) {
      if (now.difference(_lastStatusUpdate!) < const Duration(seconds: 30)) {
        return;
      }
    }

    try {
      final profileData = await api.getProfile();
      final syncStatus = await api.getSyncStatus();
      final fbsComplete = syncStatus['fbs_backfill_is_complete'] ?? true;

      if (mounted) {
        final auth = Provider.of<AuthProvider>(context, listen: false);
        final bool isAdmin = profileData['is_admin'] ?? false;
        final bool isDemo = profileData['is_demo'] ?? false;
        final String? subEndStr = profileData['subscription_end_date'];
        DateTime? subEndDate;
        if (subEndStr != null) {
          subEndDate = DateTime.tryParse(subEndStr);
        }

        setState(() {
          isFbsBackfillComplete = fbsComplete;
          _lastStatusUpdate = now;
        });

        await auth.updateProfile(
          isAdmin: isAdmin,
          isDemo: isDemo,
          subscriptionEndDate: subEndDate,
        );
      }
    } catch (e) {
      debugPrint('Dashboard: profile refresh error: $e');
    }
  }

  /// Получение версии приложения.
  Future<void> _initPackageInfo() async {
    final info = await PackageInfo.fromPlatform();
    if (mounted) {
      setState(() {
        _appVersion = 'Версия ${info.version}+${info.buildNumber}';
      });
    }
  }

  @override
  void dispose() {
    _autoRefreshTimer?.cancel();
    super.dispose();
  }

  /// Форматирование даты в ISO строку для отправки в API (с учетом МСК времени).
  String _getIso(DateTime date, bool endOfDay) {
    final d = endOfDay 
      ? DateTime(date.year, date.month, date.day, 23, 59, 59).subtract(const Duration(hours: 3))
      : DateTime(date.year, date.month, date.day, 0, 0, 0).subtract(const Duration(hours: 3));
    return DateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'").format(d);
  }

  /// Основной метод загрузки всех данных для дашборда (отчеты, графики, итоги).
  Future<void> _loadAllData({bool isSilent = false, bool forceRefreshStatus = false}) async {
    if (!mounted) return;
    if (!isSilent) setState(() => loading = true);

    try {
      // Обновляем статус синхронизации и профиль. 
      // Применяем принудительное обновление только если передан флаг forceRefreshStatus.
      // В остальных случаях (навигация) запрос попадет под 30-секундный троттлинг.
      await _refreshProfile(force: forceRefreshStatus);
      
      DateTime periodStart;
      DateTime periodEnd;

      // 1. ОПРЕДЕЛЯЕМ ГРАНИЦЫ ОСНОВНОГО ПЕРИОДА
      if (selectedPeriod == 'custom' && customRange != null) {
        periodStart = customRange!.start;
        periodEnd = customRange!.end;
      } else {
        periodEnd = activeDate;
        if (selectedPeriod == 'today') {
          periodStart = activeDate;
        } else if (selectedPeriod == 'week') {
          if (weekMode == 'calendar') {
            int daysToSubtract = activeDate.weekday - 1;
            periodStart = activeDate.subtract(Duration(days: daysToSubtract));
          } else {
            periodStart = activeDate.subtract(const Duration(days: 6));
          }
        } else {
          if (monthMode == 'calendar') {
            periodStart = DateTime(activeDate.year, activeDate.month, 1);
          } else {
            periodStart = activeDate.subtract(const Duration(days: 29));
          }
        }
      }

      // 2. ОПРЕДЕЛЯЕМ ДАТЫ ДЛЯ ОТЧЕТА (Цифры и Товары)
      DateTime reportStart = drillDownDate ?? periodStart;
      DateTime reportEnd = drillDownDate ?? periodEnd;

      final sinceStr = _getIso(reportStart, false);
      final toStr = _getIso(reportEnd, true);

      // Запрос данных за текущий период
      final reportResponse = await api.getSalesRange(
        since: sinceStr,
        to: toStr,
        scheme: selectedScheme,
      );

      // Запрос данных за предыдущий аналогичный период (для сравнения)
      final diff = reportEnd.difference(reportStart).inDays + 1;
      final prevResponse = await api.getSalesRange(
        since: _getIso(reportStart.subtract(Duration(days: diff)), false),
        to: _getIso(reportEnd.subtract(Duration(days: diff)), true),
        scheme: selectedScheme,
      );

      // 3. ЗАПРОС ДЛЯ ГРАФИКА
      DateTime statsStart = periodStart;
      DateTime statsEnd = periodEnd;
      if (selectedPeriod == 'today') {
        statsStart = activeDate.subtract(const Duration(days: 6));
        statsEnd = activeDate;
      }

      final statsResponse = await api.getDailyStats(
        since: _getIso(statsStart, false),
        to: _getIso(statsEnd, true),
        scheme: selectedScheme,
      );

      if (!mounted) return;
      setState(() {
        items = (reportResponse['items'] as List?)?.cast<Map<String, dynamic>>() ?? [];
        totals = reportResponse;
        if (totals != null) {
          totals!['current_since'] = sinceStr;
          totals!['current_to'] = toStr;
        }

        yesterdayTotals = prevResponse;
        weeklyStats = (statsResponse['data'] as List?)?.cast<Map<String, dynamic>>() ?? [];
        loading = false;
      });
    } catch (e) {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        // Переключение между мобильной и десктопной версией в зависимости от ширины экрана
        if (constraints.maxWidth < 800) {
          return _buildMobileLayout();
        }
        return _buildDesktopLayout();
      },
    );
  }

  /// Обработка выхода из аккаунта.
  void _handleLogout() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Выход'),
        content: const Text('Вы уверены, что хотите выйти из аккаунта?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Отмена')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Выйти', style: TextStyle(color: Colors.red))),
        ],
      ),
    );

    if (confirmed == true && mounted) {
      final auth = Provider.of<AuthProvider>(context, listen: false);
      auth.logout();
      Navigator.of(context).popUntil((route) => route.isFirst);
    }
  }

  /// Построение бокового меню (Drawer).
  Widget _buildDrawer(AuthProvider auth) {
    return Drawer(
      child: SafeArea(
        top: false, 
        child: Column(
          children: [
            DrawerHeader(
              decoration: BoxDecoration(color: Theme.of(context).primaryColor),
              child: Center(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    const Icon(Icons.hub_outlined, size: 48, color: Colors.white),
                    const SizedBox(height: 12),
                    Text(
                      auth.userEmail ?? 'Sales Hub',
                      style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
                    ),
                    if (!auth.isDemo)
                      Container(
                        margin: const EdgeInsets.only(top: 4),
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                          color: Colors.amber,
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: const Text(
                          'PREMIUM',
                          style: TextStyle(color: Colors.black, fontSize: 10, fontWeight: FontWeight.bold),
                        ),
                      ),
                  ],
                ),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.dashboard_outlined),
              title: const Text('Дашборд'),
              selected: true,
              onTap: () => Navigator.pop(context),
            ),
            ListTile(
              leading: const Icon(Icons.local_shipping_outlined),
              title: const Text('Отгрузки'),
              onTap: () {
                Navigator.pop(context);
                Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ShipmentsScreen()));
              },
            ),
            ListTile(
              leading: const Icon(Icons.attach_money_outlined),
              title: const Text('Себестоимость'),
              onTap: () {
                Navigator.pop(context);
                Navigator.of(context).push(MaterialPageRoute(builder: (_) => const ProductCostsScreen()));
              },
            ),
            ListTile(
              leading: const Icon(Icons.settings_outlined),
              title: const Text('Настройки магазина'),
              onTap: () {
                Navigator.pop(context);
                Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SettingsScreen()));
              },
            ),
            if (Provider.of<AuthProvider>(context, listen: false).isAdmin && kIsWeb) ...[
              const Divider(),
              ListTile(
                leading: const Icon(Icons.admin_panel_settings_outlined, color: Colors.amber),
                title: const Text('Панель администратора'),
                onTap: () {
                  Navigator.pop(context);
                  Navigator.of(context).push(MaterialPageRoute(builder: (_) => const AdminDashboardScreen()));
                },
              ),
            ],
            const Divider(),
            const Spacer(),
            ListTile(
              leading: const Icon(Icons.logout, color: Colors.redAccent),
              title: const Text('Выйти', style: TextStyle(color: Colors.redAccent)),
              onTap: _handleLogout,
            ),
            const Divider(),
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(
                _appVersion,
                style: const TextStyle(color: Colors.grey, fontSize: 12),
              ),
            ),
            const SizedBox(height: 8), 
          ],
        ),
      ),
    );
  }

  /// Переключение даты вперед/назад на один шаг (день, неделя или месяц).
  void _handleDateStep(int step) {
    setState(() {
      drillDownDate = null;
      if (selectedPeriod == 'custom' && customRange != null) {
        final range = customRange!;
        customRange = DateTimeRange(
          start: range.start.add(Duration(days: step)),
          end: range.end.add(Duration(days: step)),
        );
        activeDate = customRange!.end;
      } else if (selectedPeriod == 'month' && monthMode == 'calendar') {
        if (step < 0) {
          activeDate = DateTime(activeDate.year, activeDate.month, 1).subtract(const Duration(days: 1));
        } else {
          DateTime nextMonth = DateTime(activeDate.year, activeDate.month + 1, 1);
          DateTime now = DateTime.now();
          if (nextMonth.year == now.year && nextMonth.month == now.month) {
            activeDate = now;
          } else {
            activeDate = DateTime(nextMonth.year, nextMonth.month + 1, 0);
          }
        }
      } else if (selectedPeriod == 'week' && weekMode == 'calendar') {
        if (step < 0) {
          activeDate = activeDate.subtract(Duration(days: activeDate.weekday));
        } else {
          activeDate = activeDate.add(Duration(days: 7 - activeDate.weekday + 7));
          DateTime now = DateTime.now();
          DateTime today = DateTime(now.year, now.month, now.day);
          if (activeDate.isAfter(today)) activeDate = today;
        }
      } else {
        activeDate = activeDate.add(Duration(days: step));
      }
    });
    _loadAllData();
  }

  /// Запуск ручной синхронизации данных с сервером Ozon.
  Future<void> _handleManualSync() async {
    if (loading) return;
    
    setState(() => loading = true);
    
    try {
      final res = await api.triggerManualSync();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Синхронизация завершена! Найдено заказов: ${res['new_orders_found']}'),
            backgroundColor: Colors.green,
            behavior: SnackBarBehavior.floating,
          ),
        );
        _loadAllData(forceRefreshStatus: true);
      }
    } catch (e) {
      if (mounted) {
        setState(() => loading = false);
        String msg = 'Ошибка синхронизации';
        if (e is DioException && e.response?.statusCode == 429) {
          msg = e.response?.data['detail'] ?? msg;
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(msg),
            backgroundColor: Colors.orange,
            behavior: SnackBarBehavior.floating,
            duration: const Duration(seconds: 4),
          ),
        );
      }
    }
  }

  /// Построение мобильной версии интерфейса.
  Widget _buildMobileLayout() {
    final auth = Provider.of<AuthProvider>(context);
    return Scaffold(
      backgroundColor: const Color(0xFFF5F7FA),
      appBar: AppBar(
        title: const Text('Sales Hub', style: TextStyle(fontWeight: FontWeight.bold)),
        backgroundColor: Colors.white,
        elevation: 0,
        actions: [
          IconButton(
            icon: Icon(Icons.add_business_outlined, color: Theme.of(context).primaryColor),
            tooltip: 'Добавить магазин',
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SettingsScreen())),
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _handleManualSync, // Внутри вызывается _loadAllData(forceRefreshStatus: true)
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(50),
          child: Padding(
            padding: const EdgeInsets.only(bottom: 8.0, left: 16, right: 16),
            child: Row(
              children: [
                Expanded(
                  child: SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(value: 'fbo', label: Text('FBO'), icon: Icon(Icons.inventory_2, size: 16)),
                      ButtonSegment(value: 'fbs', label: Text('FBS'), icon: Icon(Icons.local_shipping, size: 16)),
                      ButtonSegment(value: 'all', label: Text('Все')),
                    ],
                    selected: {selectedScheme},
                    onSelectionChanged: (Set<String> newSelection) {
                      setState(() {
                        selectedScheme = newSelection.first;
                      });
                      _saveScheme(selectedScheme);
                      _loadAllData(); // Смена схемы — навигационное действие, троттлим статус
                    },
                    style: SegmentedButton.styleFrom(
                      visualDensity: VisualDensity.compact,
                      padding: EdgeInsets.zero,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
      drawer: _buildDrawer(auth),
      body: Column(
        children: [
          if (auth.isImpersonating) _buildSupportBanner(auth),
          if (!isFbsBackfillComplete && (selectedScheme == 'fbs' || selectedScheme == 'all'))
            _buildBackfillBanner(),
          Expanded(
            child: RefreshIndicator(
              onRefresh: () => _loadAllData(forceRefreshStatus: true),
              child: MobileDashboardView(
                api: api,
                getIso: _getIso,
                scheme: selectedScheme,
                sinceStr: (totals?['current_since'] as String?) ?? _getIso(DateTime.now(), false),
                toStr: (totals?['current_to'] as String?) ?? _getIso(DateTime.now(), true),
                items: items, totals: totals, yesterdayTotals: yesterdayTotals, weeklyStats: weeklyStats,
                isLoading: loading, selectedPeriod: selectedPeriod, activeDate: activeDate, drillDownDate: drillDownDate,
                weekMode: weekMode, monthMode: monthMode, customRange: customRange,
                onPeriodChanged: (p) { setState(() { selectedPeriod = p; drillDownDate = null; activeDate = DateTime.now(); customRange = null; }); _loadAllData(); },
                onDateChanged: (d) { 
                  int step = d.isBefore(activeDate) ? -1 : 1;
                  _handleDateStep(step);
                },
                onDrillDown: (d) { setState(() => drillDownDate = d); _loadAllData(); },
                onResetDrillDown: () { setState(() => drillDownDate = null); _loadAllData(); },
                onSettingsChanged: (wMode, mMode) {
                  setState(() {
                    weekMode = wMode;
                    monthMode = mMode;
                  });
                  _loadAllData();
                },
                onCustomRangeSelected: (range) {
                  setState(() {
                    selectedPeriod = 'custom';
                    customRange = range;
                    activeDate = range.end;
                    drillDownDate = null;
                  });
                  _loadAllData();
                },
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// Баннер, информирующий о процессе загрузки истории FBS.
  Widget _buildBackfillBanner() {
    return Container(
      width: double.infinity,
      color: Colors.amber[100],
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: const Row(
        children: [
          Icon(Icons.info_outline, color: Colors.amber, size: 18),
          SizedBox(width: 8),
          Expanded(
            child: Text(
              'Идёт загрузка истории FBS, данные могут быть неполными.',
              style: TextStyle(fontSize: 12, color: Colors.brown, fontWeight: FontWeight.bold),
            ),
          ),
        ],
      ),
    );
  }

  /// Построение десктопной версии интерфейса (центрирование контента).
  Widget _buildDesktopLayout() {
    return Container(
      color: const Color(0xFFF5F7FA),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1100),
          child: _buildMobileLayout(),
        ),
      ),
    );
  }

  /// Баннер режима поддержки (имперсонация администратора).
  Widget _buildSupportBanner(AuthProvider auth) {
    return Container(
      width: double.infinity,
      color: Colors.redAccent,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          const Icon(Icons.support_agent, color: Colors.white),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              'РЕЖИМ ПОДДЕРЖКИ: Вы вошли как ${auth.userEmail}',
              style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
            ),
          ),
          ElevatedButton.icon(
            onPressed: () async {
              await auth.stopImpersonating();
              _loadAllData(forceRefreshStatus: true);
            },
            icon: const Icon(Icons.exit_to_app, size: 18),
            label: const Text('ВЕРНУТЬСЯ'),
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.white,
              foregroundColor: Colors.redAccent,
              padding: const EdgeInsets.symmetric(horizontal: 12),
            ),
          ),
        ],
      ),
    );
  }
}
