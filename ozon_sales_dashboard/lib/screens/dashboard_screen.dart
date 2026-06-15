import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'dart:async';
import '../services/api.dart';
import '../widgets/mobile_dashboard_view.dart';
import '../widgets/sales_table.dart';
import 'login_screen.dart';
import 'settings_screen.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  late final OzonApiClient api;
  
  // ЕДИНОЕ СОСТОЯНИЕ ДЛЯ ВСЕХ ВЕРСИЙ
  String selectedPeriod = 'today'; 
  DateTime activeDate = DateTime.now(); 
  DateTime? drillDownDate; 

  List<Map<String, dynamic>> items = [];
  Map<String, dynamic>? totals;
  Map<String, dynamic>? yesterdayTotals;
  List<Map<String, dynamic>> weeklyStats = [];
  bool loading = false;
  Timer? _autoRefreshTimer;

  @override
  void initState() {
    super.initState();
    api = OzonApiClient(onUnauthorized: _handleUnauthorized);
    _loadAllData();
    _autoRefreshTimer = Timer.periodic(const Duration(minutes: 5), (_) => _loadAllData(isSilent: true));
  }

  @override
  void dispose() {
    _autoRefreshTimer?.cancel();
    super.dispose();
  }

  void _handleUnauthorized() {
    if (mounted) Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => const LoginScreen()));
  }

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
      DateTime reportStart;
      DateTime reportEnd;

      if (drillDownDate != null) {
        reportStart = drillDownDate!;
        reportEnd = drillDownDate!;
      } else {
        reportEnd = activeDate;
        if (selectedPeriod == 'today') reportStart = activeDate;
        else if (selectedPeriod == 'week') reportStart = activeDate.subtract(const Duration(days: 6));
        else reportStart = activeDate.subtract(const Duration(days: 29));
      }

      // ЕДИНЫЙ ЗАПРОС ДЛЯ ВСЕХ Layout
      final reportResponse = await api.dio.get('/analytics/sales_report', queryParameters: {
        'since': _getIso(reportStart, false),
        'to': _getIso(reportEnd, true),
      });

      final diff = reportEnd.difference(reportStart).inDays + 1;
      final prevResponse = await api.dio.get('/analytics/sales_report', queryParameters: {
        'since': _getIso(reportStart.subtract(Duration(days: diff)), false),
        'to': _getIso(reportEnd.subtract(Duration(days: diff)), true),
      });

      final statsResponse = await api.dio.get('/analytics/daily_stats', queryParameters: {
        'since': _getIso(DateTime.now().subtract(const Duration(days: 29)), false),
        'to': _getIso(DateTime.now(), true),
      });

      if (!mounted) return;
      setState(() {
        items = (reportResponse.data['items'] as List).cast<Map<String, dynamic>>();
        totals = reportResponse.data;
        yesterdayTotals = prevResponse.data;
        weeklyStats = (statsResponse.data['data'] as List).cast<Map<String, dynamic>>();
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

  Widget _buildMobileLayout() {
    return Scaffold(
      backgroundColor: const Color(0xFFF8F9FA),
      appBar: AppBar(
        title: const Text('Ozon Hub', style: TextStyle(fontWeight: FontWeight.bold)),
        backgroundColor: Colors.white, elevation: 0,
        actions: [
          IconButton(icon: const Icon(Icons.settings_outlined), onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SettingsScreen()))),
          IconButton(icon: const Icon(Icons.refresh), onPressed: () => _loadAllData()),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => _loadAllData(),
        child: MobileDashboardView(
          items: items, totals: totals, yesterdayTotals: yesterdayTotals, weeklyStats: weeklyStats,
          isLoading: loading, selectedPeriod: selectedPeriod, activeDate: activeDate, drillDownDate: drillDownDate,
          onPeriodChanged: (p) { setState(() { selectedPeriod = p; drillDownDate = null; activeDate = DateTime.now(); }); _loadAllData(); },
          onDateChanged: (d) { setState(() { activeDate = d; drillDownDate = null; }); _loadAllData(); },
          onDrillDown: (d) { setState(() => drillDownDate = d); _loadAllData(); },
          onResetDrillDown: () { setState(() => drillDownDate = null); _loadAllData(); },
        ),
      ),
    );
  }

  Widget _buildDesktopLayout() {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Ozon Hub - Desktop'),
        actions: [
          IconButton(icon: const Icon(Icons.settings), onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SettingsScreen()))),
          IconButton(icon: const Icon(Icons.refresh), onPressed: () => _loadAllData()),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            // Для десктопа просто выводим кнопки управления и таблицу
            if (loading) const LinearProgressIndicator(),
            const SizedBox(height: 20),
            Row(
              children: [
                ElevatedButton(onPressed: () { setState(() => selectedPeriod = 'today'); _loadAllData(); }, child: const Text('Сегодня')),
                const SizedBox(width: 8),
                ElevatedButton(onPressed: () { setState(() => selectedPeriod = 'week'); _loadAllData(); }, child: const Text('Неделя')),
                const SizedBox(width: 8),
                ElevatedButton(onPressed: () { setState(() => selectedPeriod = 'month'); _loadAllData(); }, child: const Text('Месяц')),
              ],
            ),
            const SizedBox(height: 20),
            SalesTable(items: items, delivered: true, totals: totals),
          ],
        ),
      ),
    );
  }
}
