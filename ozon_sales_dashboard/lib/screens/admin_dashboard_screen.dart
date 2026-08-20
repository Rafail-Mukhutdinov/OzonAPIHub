import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import 'package:fl_chart/fl_chart.dart';
import '../providers/auth_provider.dart';
import '../services/api.dart';
import 'admin_users_screen.dart';
import 'admin_health_screen.dart';
import 'admin_analytics_screen.dart';
import 'admin_audit_logs_screen.dart';
import 'admin_settings_screen.dart';

/// Главный экран админ-панели (Web-only).
/// Показывает обзорную статистику платформы и быстрые ссылки.
class AdminDashboardScreen extends StatefulWidget {
  const AdminDashboardScreen({super.key});

  @override
  State<AdminDashboardScreen> createState() => _AdminDashboardScreenState();
}

class _AdminDashboardScreenState extends State<AdminDashboardScreen> {
  late final OzonApiClient api;
  Map<String, dynamic>? _stats;
  Map<String, dynamic>? _gmvData;
  Map<String, dynamic>? _growth;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    final auth = Provider.of<AuthProvider>(context, listen: false);
    api = OzonApiClient(authProvider: auth);
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      // Загружаем 3 независимых запроса параллельно
      final now = DateTime.now();
      final monthAgo = now.subtract(const Duration(days: 30));

      final results = await Future.wait([
        api.dio.get('/admin/stats'),
        api.dio.get('/admin/analytics/gmv', queryParameters: {
          'since': monthAgo.toIso8601String(),
          'to': now.toIso8601String(),
          'group_by': 'day',
        }),
        api.dio.get('/admin/analytics/growth'),
      ]);

      if (mounted) {
        setState(() {
          _stats = results[0].data as Map<String, dynamic>?;
          _gmvData = results[1].data as Map<String, dynamic>?;
          _growth = results[2].data as Map<String, dynamic>?;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = 'Ошибка загрузки данных. Проверьте права администратора.';
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    // Guard: только для Web
    if (!kIsWeb) {
      return Scaffold(
        appBar: AppBar(title: const Text('Панель администратора')),
        body: const Center(
          child: Padding(
            padding: EdgeInsets.all(32),
            child: Text(
              'Админ-панель доступна только в веб-версии.\nОткройте приложение в браузере на компьютере.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 16),
            ),
          ),
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Admin Dashboard'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadData,
            tooltip: 'Обновить',
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Icon(Icons.error_outline, size: 64, color: Colors.red),
                      const SizedBox(height: 16),
                      Text(_error!, textAlign: TextAlign.center),
                      const SizedBox(height: 16),
                      ElevatedButton(onPressed: _loadData, child: const Text('Повторить')),
                    ],
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _loadData,
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _buildOverviewCards(),
                        const SizedBox(height: 32),
                        _buildGmvChart(),
                        const SizedBox(height: 32),
                        _buildGrowthSection(),
                        const SizedBox(height: 32),
                        _buildQuickActions(),
                      ],
                    ),
                  ),
                ),
    );
  }

  /// Обзорные карточки со статистикой
  Widget _buildOverviewCards() {
    final stats = _stats?['users'] as Map<String, dynamic>? ?? {};
    final data = _stats?['data'] as Map<String, dynamic>? ?? {};

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Обзор платформы', style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
        const SizedBox(height: 16),
        LayoutBuilder(
          builder: (context, constraints) {
            // Адаптивная сетка: 4 колонки на широких экранах, 2 на узких
            final crossAxisCount = constraints.maxWidth > 1000 ? 4 : 2;
            return GridView.count(
              crossAxisCount: crossAxisCount,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              crossAxisSpacing: 16,
              mainAxisSpacing: 16,
              childAspectRatio: 1.2,
              children: [
                _StatCard(
                  title: 'Всего пользователей',
                  value: '${stats['total'] ?? 0}',
                  icon: Icons.people,
                  color: Colors.blue,
                ),
                _StatCard(
                  title: 'Активных',
                  value: '${stats['active'] ?? 0}',
                  icon: Icons.people_outline,
                  color: Colors.green,
                ),
                _StatCard(
                  title: 'Всего заказов',
                  value: _formatNumber(data['orders'] ?? 0),
                  icon: Icons.shopping_cart,
                  color: Colors.orange,
                ),
                _StatCard(
                  title: 'Постингов',
                  value: _formatNumber(data['order_postings'] ?? 0),
                  icon: Icons.local_shipping,
                  color: Colors.purple,
                ),
              ],
            );
          },
        ),
      ],
    );
  }

  /// График GMV за последние 30 дней
  Widget _buildGmvChart() {
    final dynamicList = _gmvData?['dynamic'] as List? ?? [];
    final totalGmv = (_gmvData?['total_gmv'] ?? 0).toDouble();
    final sellersCount = _gmvData?['sellers_count'] ?? 0;

    if (dynamicList.isEmpty) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            children: [
              const Icon(Icons.bar_chart, size: 48, color: Colors.grey),
              const SizedBox(height: 16),
              Text('Platform GMV: ${_formatMoney(totalGmv)} ₽',
                  style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              const Text('Нет данных за последние 30 дней',
                  style: TextStyle(color: Colors.grey)),
            ],
          ),
        ),
      );
    }

    // Готовим данные для графика
    final spots = <BarChartGroupData>[];
    double maxGmv = 0;

    for (int i = 0; i < dynamicList.length; i++) {
      final item = dynamicList[i] as Map<String, dynamic>;
      final gmv = (item['gmv'] ?? 0).toDouble();
      if (gmv > maxGmv) maxGmv = gmv;

      spots.add(BarChartGroupData(
        x: i,
        barRods: [
          BarChartRodData(
            toY: gmv,
            color: Colors.blueAccent,
            width: 12,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(4)),
          ),
        ],
      ));
    }

    return Card(
      elevation: 3,
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('Platform GMV (30 дней)',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text('${_formatMoney(totalGmv)} ₽',
                        style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.blue)),
                    Text('$sellersCount продавцов', style: const TextStyle(color: Colors.grey)),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 24),
            SizedBox(
              height: 300,
              child: BarChart(
                BarChartData(
                  alignment: BarChartAlignment.spaceAround,
                  maxY: maxGmv > 0 ? maxGmv * 1.1 : 100,
                  barTouchData: BarTouchData(
                    enabled: true,
                    touchTooltipData: BarTouchTooltipData(
                      getTooltipColor: (_) => Colors.grey.shade800,
                      getTooltipItem: (group, groupIndex, rod, rodIndex) {
                        final item = dynamicList[groupIndex] as Map<String, dynamic>;
                        final gmv = item['gmv'] ?? 0;
                        return BarTooltipItem(
                          '${_formatMoney(gmv.toDouble())} ₽',
                          const TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
                        );
                      },
                    ),
                  ),
                  titlesData: FlTitlesData(
                    show: true,
                    rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                    topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                    bottomTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                    leftTitles: AxisTitles(
                      sideTitles: SideTitles(
                        showTitles: true,
                        reservedSize: 60,
                        interval: maxGmv > 0 ? maxGmv / 4 : null,
                        getTitlesWidget: (value, meta) {
                          return Padding(
                            padding: const EdgeInsets.only(right: 8),
                            child: Text(_formatMoney(value),
                                style: const TextStyle(fontSize: 10)),
                          );
                        },
                      ),
                    ),
                  ),
                  gridData: const FlGridData(show: true, drawVerticalLine: false),
                  borderData: FlBorderData(show: false),
                  barGroups: spots,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Секция роста (DAU/WAU/MAU)
  Widget _buildGrowthSection() {
    final activity = _growth?['activity'] as Map<String, dynamic>? ?? {};
    final churn = _growth?['churn_risk'] as Map<String, dynamic>? ?? {};

    return Card(
      elevation: 3,
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Активность и отток', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(child: _MiniStat(label: 'DAU', value: '${activity['dau'] ?? 0}', color: Colors.green)),
                const SizedBox(width: 16),
                Expanded(child: _MiniStat(label: 'WAU', value: '${activity['wau'] ?? 0}', color: Colors.blue)),
                const SizedBox(width: 16),
                Expanded(child: _MiniStat(label: 'MAU', value: '${activity['mau'] ?? 0}', color: Colors.purple)),
                const SizedBox(width: 16),
                Expanded(
                  child: _MiniStat(
                    label: 'Churn risk',
                    value: '${churn['count'] ?? 0}',
                    color: (churn['count'] ?? 0) > 0 ? Colors.red : Colors.green,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  /// Быстрые ссылки на другие разделы
  Widget _buildQuickActions() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Разделы', style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
        const SizedBox(height: 16),
        LayoutBuilder(
          builder: (context, constraints) {
            return GridView.count(
              crossAxisCount: constraints.maxWidth > 1000 ? 3 : 1,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              crossAxisSpacing: 16,
              mainAxisSpacing: 16,
              childAspectRatio: constraints.maxWidth > 1000 ? 2.2 : 4.0,
              children: [
                _ActionCard(
                  title: 'Пользователи',
                  subtitle: 'Список, блокировка, impersonation',
                  icon: Icons.manage_accounts,
                  color: Colors.blue,
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const AdminUsersScreen()),
                  ),
                ),
                _ActionCard(
                  title: 'Мониторинг',
                  subtitle: 'Ошибки синхронизации, БД, очереди',
                  icon: Icons.health_and_safety,
                  color: Colors.red,
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const AdminHealthScreen()),
                  ),
                ),
                _ActionCard(
                  title: 'Аналитика',
                  subtitle: 'GMV, Top Sellers, Воронка',
                  icon: Icons.analytics,
                  color: Colors.orange,
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const AdminAnalyticsScreen()),
                  ),
                ),
                _ActionCard(
                  title: 'Журнал аудита',
                  subtitle: 'Кто, когда и что сделал',
                  icon: Icons.assignment,
                  color: Colors.teal,
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const AdminAuditLogsScreen()),
                  ),
                ),
                _ActionCard(
                  title: 'Системные настройки',
                  subtitle: 'Maintenance mode и параметры',
                  icon: Icons.settings_suggest,
                  color: Colors.grey,
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const AdminSettingsScreen()),
                  ),
                ),
              ],
            );
          },
        ),
      ],
    );
  }

  String _formatNumber(dynamic value) {
    final num v = value is int ? value : (value as double).toInt();
    return NumberFormat.decimalPattern('ru_RU').format(v);
  }

  String _formatMoney(dynamic value) {
    final num v = value is int ? value : value;
    return NumberFormat.compactCurrency(
      locale: 'ru_RU',
      symbol: '',
      decimalDigits: 0,
    ).format(v);
  }
}

/// Карточка статистики для обзорной панели
class _StatCard extends StatelessWidget {
  final String title;
  final String value;
  final IconData icon;
  final Color color;

  const _StatCard({
    required this.title,
    required this.value,
    required this.icon,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 3,
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, size: 32, color: color),
            const SizedBox(height: 8),
            FittedBox(
              fit: BoxFit.scaleDown,
              child: Text(value,
                  style: const TextStyle(fontSize: 28, fontWeight: FontWeight.bold)),
            ),
            const SizedBox(height: 4),
            Text(title, style: TextStyle(fontSize: 13, color: Colors.grey.shade600), textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }
}

/// Мини-статистика для строк
class _MiniStat extends StatelessWidget {
  final String label;
  final String value;
  final Color color;

  const _MiniStat({required this.label, required this.value, required this.color});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(value, style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: color)),
        const SizedBox(height: 4),
        Text(label, style: TextStyle(fontSize: 12, color: Colors.grey.shade600)),
      ],
    );
  }
}

/// Карточка быстрого действия
class _ActionCard extends StatelessWidget {
  final String title;
  final String subtitle;
  final IconData icon;
  final Color color;
  final VoidCallback onTap;

  const _ActionCard({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 2,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              Icon(icon, size: 36, color: color),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    Text(
                      subtitle,
                      style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, color: Colors.grey),
            ],
          ),
        ),
      ),
    );
  }
}