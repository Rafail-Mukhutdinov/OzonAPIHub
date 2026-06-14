import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'dart:async';
import '../services/api.dart';
import '../widgets/mobile_dashboard_view.dart';
import 'login_screen.dart';
import 'settings_screen.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  late final OzonApiClient api;
  
  String selectedPeriod = 'today'; // 'today', 'week', 'month'
  DateTime activeDate = DateTime.now(); // Конечная точка периода
  DateTime? drillDownDate; // Конкретный день для деталей (если выбран на графике)

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
    // ЗАПУСКАЕМ АВТО-ОБНОВЛЕНИЕ каждые 5 минут
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
    final d = endOfDay 
      ? DateTime(date.year, date.month, date.day, 23, 59, 59).subtract(const Duration(hours: 3))
      : DateTime(date.year, date.month, date.day, 0, 0, 0).subtract(const Duration(hours: 3));
    return DateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'").format(d);
  }

  Future<void> _loadAllData({bool isSilent = false}) async {
    if (!mounted) return;
    if (!isSilent) setState(() => loading = true);

    try {
      // 1. ОПРЕДЕЛЯЕМ ПЕРИОД ДЛЯ ОТЧЕТА (КАРТОЧКИ И ТОВАРЫ)
      DateTime reportStart;
      DateTime reportEnd;

      if (drillDownDate != null) {
        // Если выбран конкретный день на графике - смотрим только его
        reportStart = drillDownDate!;
        reportEnd = drillDownDate!;
      } else {
        // Иначе смотрим весь выбранный период (день/неделя/месяц)
        reportEnd = activeDate;
        if (selectedPeriod == 'today') reportStart = activeDate;
        else if (selectedPeriod == 'week') reportStart = activeDate.subtract(const Duration(days: 6));
        else reportStart = activeDate.subtract(const Duration(days: 29));
      }

      // Запрос основного отчета
      final reportResponse = await api.dio.get('/analytics/sales_report', queryParameters: {
        'since': _getIso(reportStart, false),
        'to': _getIso(reportEnd, true),
      });

      // 2. СРАВНЕНИЕ (всегда сравниваем с таким же периодом в прошлом)
      final diff = reportEnd.difference(reportStart).inDays + 1;
      final prevStart = reportStart.subtract(Duration(days: diff));
      final prevEnd = reportEnd.subtract(Duration(days: diff));
      
      final prevResponse = await api.dio.get('/analytics/sales_report', queryParameters: {
        'since': _getIso(prevStart, false),
        'to': _getIso(prevEnd, true),
      });

      // 3. ГРАФИК (всегда 30 дней от реального сегодня, чтобы не прыгал)
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
          items: items,
          totals: totals,
          yesterdayTotals: yesterdayTotals,
          weeklyStats: weeklyStats,
          isLoading: loading,
          selectedPeriod: selectedPeriod,
          activeDate: activeDate,
          drillDownDate: drillDownDate,
          onPeriodChanged: (period) {
            setState(() {
              selectedPeriod = period;
              drillDownDate = null; // Сбрасываем детали при смене периода
              activeDate = DateTime.now();
            });
            _loadAllData();
          },
          onDateChanged: (newDate) {
            setState(() {
              activeDate = newDate;
              drillDownDate = null;
            });
            _loadAllData();
          },
          onDrillDown: (date) {
            setState(() => drillDownDate = date);
            _loadAllData();
          },
          onResetDrillDown: () {
            setState(() => drillDownDate = null);
            _loadAllData();
          },
        ),
      ),
      bottomNavigationBar: BottomNavigationBar(
        selectedItemColor: Colors.black, unselectedItemColor: Colors.grey,
        type: BottomNavigationBarType.fixed,
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.home_filled), label: 'Главная'),
          BottomNavigationBarItem(icon: Icon(Icons.grid_view), label: 'Товары'),
          BottomNavigationBarItem(icon: Icon(Icons.warehouse_outlined), label: 'Склад'),
          BottomNavigationBarItem(icon: Icon(Icons.person_outline), label: 'Профиль'),
        ],
      ),
    );
  }
}
