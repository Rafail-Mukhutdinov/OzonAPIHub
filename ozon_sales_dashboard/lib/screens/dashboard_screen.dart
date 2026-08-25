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

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  late final OzonApiClient api;
  String _appVersion = '...';
  
  // ЕДИНОЕ СОСТОЯНИЕ ДЛЯ ВСЕХ ВЕРСИЙ
  String selectedPeriod = 'today'; 
  String selectedScheme = 'fbo'; // 'fbo', 'fbs', 'all'
  bool isFbsBackfillComplete = true; // Для индикатора загрузки
  DateTime activeDate = DateTime.now(); 
  DateTime? drillDownDate; 

  // РЕЖИМЫ ПЕРИОДОВ (сохраняются во время сессии)
  String weekMode = 'rolling'; // 'rolling' или 'calendar'
  String monthMode = 'calendar'; // 'calendar' (с 1-го числа) или 'rolling'
  DateTimeRange? customRange; 

  List<Map<String, dynamic>> items = [];
  Map<String, dynamic>? totals;
  Map<String, dynamic>? yesterdayTotals;
  List<Map<String, dynamic>> weeklyStats = [];
  bool loading = false;
  Timer? _autoRefreshTimer;

  @override
  void initState() {
    super.initState();
    // Передаем authProvider напрямую для централизованной обработки 401
    final auth = Provider.of<AuthProvider>(context, listen: false);
    api = OzonApiClient(authProvider: auth);
    _loadSettings().then((_) => _loadAllData());
    _refreshProfile(); // Добавляем обновление профиля при входе
    _initPackageInfo();
    _autoRefreshTimer = Timer.periodic(const Duration(minutes: 5), (_) => _loadAllData(isSilent: true));
  }

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

  Future<void> _saveScheme(String scheme) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      // Не сохраняем 'all', сбрасываем на 'fbo'
      if (scheme == 'all') {
        await prefs.remove('selected_scheme');
      } else {
        await prefs.setString('selected_scheme', scheme);
      }
    } catch (e) {
      debugPrint('Error saving scheme: $e');
    }
  }

  Future<void> _refreshProfile() async {
    try {
      final profileData = await api.getProfile();
      
      // Проверяем статус синхронизации для FBS
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

  // МЕТОД _handleUnauthorized больше не нужен, удаляем его

  String _getIso(DateTime date, bool endOfDay) {
    // ВАЖНО: Приводим к UTC+3 (Москва) перед отправкой
    final d = endOfDay 
      ? DateTime(date.year, date.month, date.day, 23, 59, 59).subtract(const Duration(hours: 3))
      : DateTime(date.year, date.month, date.day, 0, 0, 0).subtract(const Duration(hours: 3));
    return DateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'").format(d);
  }

  Future<void> _loadAllData({bool isSilent = false}) async {
    if (!mounted) return;
    if (!isSilent) setState(() => loading = true);

    try {
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
      // Если есть drillDownDate, берем его. Если нет - весь период.
      DateTime reportStart = drillDownDate ?? periodStart;
      DateTime reportEnd = drillDownDate ?? periodEnd;

      final sinceStr = _getIso(reportStart, false);
      final toStr = _getIso(reportEnd, true);

      // ЕДИНЫЙ ЗАПРОС ДЛЯ ОТЧЕТА (Товары и итоги)
      final reportResponse = await api.getSalesRange(
        since: sinceStr,
        to: toStr,
        scheme: selectedScheme,
      );

      final diff = reportEnd.difference(reportStart).inDays + 1;
      final prevResponse = await api.getSalesRange(
        since: _getIso(reportStart.subtract(Duration(days: diff)), false),
        to: _getIso(reportEnd.subtract(Duration(days: diff)), true),
        scheme: selectedScheme,
      );

      // 3. ЗАПРОС ДЛЯ ГРАФИКА (Всегда за весь период)
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
        // Сохраняем ISO строки для виджетов (безопасно)
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
        // РЕШАЕМ: КАКОЙ LAYOUT ПОКАЗАТЬ, НО ДАННЫЕ ОДНИ И ТЕ ЖЕ
        if (constraints.maxWidth < 800) {
          return _buildMobileLayout();
        }
        return _buildDesktopLayout();
      },
    );
  }

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
      // 1. Блокируем приложение локально
      final auth = Provider.of<AuthProvider>(context, listen: false);
      auth.logout();
      
      // 2. Сбрасываем всю навигацию до корня (AuthGate)
      // Это гарантирует, что мы выйдем из всех открытых экранов
      Navigator.of(context).popUntil((route) => route.isFirst);
    }
  }

  Widget _buildDrawer(AuthProvider auth) {
    return Drawer(
      child: SafeArea(
        top: false, // DrawerHeader сам обрабатывает отступ статус-бара
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
            // Admin-панель доступна только в Web-версии (см. ADMIN_IMPLEMENTATION_PLAN.md, Phase 1).
            // На мобильных устройствах админка скрыта из-за ограничений экрана.
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
            const SizedBox(height: 8), // Небольшой отступ внутри SafeArea
          ],
        ),
      ),
    );
  }

  void _handleDateStep(int step) {
    setState(() {
      drillDownDate = null;
      if (selectedPeriod == 'custom' && customRange != null) {
        // Сдвигаем ВЕСЬ произвольный период
        final range = customRange!;
        customRange = DateTimeRange(
          start: range.start.add(Duration(days: step)),
          end: range.end.add(Duration(days: step)),
        );
        // Синхронизируем activeDate для корректной работы других механизмов
        activeDate = customRange!.end;
      } else if (selectedPeriod == 'month' && monthMode == 'calendar') {
        if (step < 0) {
          // Прыгаем в последний день ПРЕДЫДУЩЕГО месяца
          activeDate = DateTime(activeDate.year, activeDate.month, 1).subtract(const Duration(days: 1));
        } else {
          // Прыгаем в следующий месяц
          DateTime nextMonth = DateTime(activeDate.year, activeDate.month + 1, 1);
          // Если следующий месяц — это текущий реальный месяц, ставим "сегодня"
          DateTime now = DateTime.now();
          if (nextMonth.year == now.year && nextMonth.month == now.month) {
            activeDate = now;
          } else {
            // Иначе ставим последний день того месяца
            activeDate = DateTime(nextMonth.year, nextMonth.month + 1, 0);
          }
        }
      } else if (selectedPeriod == 'week' && weekMode == 'calendar') {
        if (step < 0) {
          // Находим воскресенье ПРЕДЫДУЩЕЙ недели
          // DateTime.weekday: 1 (Пн) ... 7 (Вс)
          // Если сегодня Вт(2), отнимаем 2 дня -> получаем Вс(21-е)
          activeDate = activeDate.subtract(Duration(days: activeDate.weekday));
        } else {
          // Прыгаем на следующее воскресенье
          activeDate = activeDate.add(Duration(days: 7 - activeDate.weekday + 7));
          // Если улетели в будущее — обрезаем до сегодня
          DateTime now = DateTime.now();
          DateTime today = DateTime(now.year, now.month, now.day);
          if (activeDate.isAfter(today)) activeDate = today;
        }
      } else {
        // Обычный сдвиг на 1 день
        activeDate = activeDate.add(Duration(days: step));
      }
    });
    _loadAllData();
  }

  Future<void> _handleManualSync() async {
    if (loading) return;
    
    // Показываем индикатор в AppBar (через loading)
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
        _loadAllData();
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
            onPressed: _handleManualSync,
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
                      _loadAllData();
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
              onRefresh: () => _loadAllData(),
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
                  // Определяем, в какую сторону был сдвиг, чтобы вызвать нашу новую логику
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

  Widget _buildDesktopLayout() {
    // Десктоп: тот же полноценный дашборд (карточки, график, периоды, детализация),
    // отцентрованный колонкой до 1100px на всю высоту окна — стандартный веб-паттерн.
    // Полноценный широкополосный десктоп-UI (в несколько колонок) можно сделать позже.
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
              _loadAllData();
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
