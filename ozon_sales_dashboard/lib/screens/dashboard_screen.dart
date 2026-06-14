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
  
  String selectedPeriod = 'today'; 
  DateTime activeDate = DateTime.now(); 

  List<Map<String, dynamic>> items = [];
  Map<String, dynamic>? totals;
  Map<String, dynamic>? yesterdayTotals;
  List<Map<String, dynamic>> weeklyStats = [];
  bool loading = false;

  @override
  void initState() {
    super.initState();
    api = OzonApiClient(onUnauthorized: () => Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => const LoginScreen())));
    _loadAllData();
  }

  String _getIso(DateTime date, bool endOfDay) {
    final d = endOfDay 
      ? DateTime(date.year, date.month, date.day, 23, 59, 59).subtract(const Duration(hours: 3))
      : DateTime(date.year, date.month, date.day, 0, 0, 0).subtract(const Duration(hours: 3));
    return DateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'").format(d);
  }

  Future<void> _loadAllData() async {
    if (!mounted) return;
    setState(() => loading = true);

    try {
      DateTime start;
      DateTime end = activeDate;

      if (selectedPeriod == 'today') {
        start = activeDate;
      } else if (selectedPeriod == 'week') {
        start = activeDate.subtract(const Duration(days: 6));
      } else {
        start = activeDate.subtract(const Duration(days: 29));
      }

      // ВЫЗЫВАЕМ НОВЫЙ ЭНДПОИНТ /sales_report
      final reportResponse = await api.dio.get('/analytics/sales_report', queryParameters: {
        'since': _getIso(start, false),
        'to': _getIso(end, true),
      });

      final prevStart = start.subtract(Duration(days: selectedPeriod == 'today' ? 1 : (selectedPeriod == 'week' ? 7 : 30)));
      final prevEnd = end.subtract(Duration(days: selectedPeriod == 'today' ? 1 : (selectedPeriod == 'week' ? 7 : 30)));
      
      final prevResponse = await api.dio.get('/analytics/sales_report', queryParameters: {
        'since': _getIso(prevStart, false),
        'to': _getIso(prevEnd, true),
      });

      final statsResponse = await api.dio.get('/analytics/daily_stats', queryParameters: {
        'since': _getIso(activeDate.subtract(const Duration(days: 29)), false),
        'to': _getIso(activeDate, true),
      });

      setState(() {
        items = (reportResponse.data['items'] as List).cast<Map<String, dynamic>>();
        totals = reportResponse.data;
        yesterdayTotals = prevResponse.data;
        weeklyStats = (statsResponse.data['data'] as List).cast<Map<String, dynamic>>();
        loading = false;
      });
    } catch (e) {
      setState(() => loading = false);
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
          IconButton(icon: const Icon(Icons.refresh), onPressed: _loadAllData),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _loadAllData,
        child: MobileDashboardView(
          items: items,
          totals: totals,
          yesterdayTotals: yesterdayTotals,
          weeklyStats: weeklyStats,
          isLoading: loading,
          selectedPeriod: selectedPeriod,
          activeDate: activeDate,
          onPeriodChanged: (period) {
            setState(() => selectedPeriod = period);
            _loadAllData();
          },
          onDateChanged: (newDate) {
            setState(() => activeDate = newDate);
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
