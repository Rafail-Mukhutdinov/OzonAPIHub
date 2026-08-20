import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import '../services/api.dart';

class AdminAnalyticsScreen extends StatefulWidget {
  const AdminAnalyticsScreen({super.key});

  @override
  State<AdminAnalyticsScreen> createState() => _AdminAnalyticsScreenState();
}

class _AdminAnalyticsScreenState extends State<AdminAnalyticsScreen> {
  late final OzonApiClient api;
  bool _loading = true;
  String? _error;

  Map<String, dynamic>? _topSellers;
  Map<String, dynamic>? _funnel;
  Map<String, dynamic>? _growth;

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
      final results = await Future.wait([
        api.dio.get('/admin/analytics/top-sellers', queryParameters: {'period_days': 30, 'limit': 20}),
        api.dio.get('/admin/analytics/onboarding-funnel', queryParameters: {'period_days': 30}),
        api.dio.get('/admin/analytics/growth'),
      ]);

      if (mounted) {
        setState(() {
          _topSellers = results[0].data as Map<String, dynamic>?;
          _funnel = results[1].data as Map<String, dynamic>?;
          _growth = results[2].data as Map<String, dynamic>?;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = 'Ошибка загрузки аналитики.';
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!kIsWeb) return const Scaffold(body: Center(child: Text('Web only')));

    return Scaffold(
      appBar: AppBar(
        title: const Text('Бизнес-аналитика платформы'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _loadData),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Text(_error!))
              : SingleChildScrollView(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _buildFunnelSection(),
                      const SizedBox(height: 32),
                      _buildTopSellersSection(),
                      const SizedBox(height: 32),
                      _buildChurnRiskSection(),
                    ],
                  ),
                ),
    );
  }

  Widget _buildFunnelSection() {
    final stages = (_funnel?['stages'] as List?) ?? [];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Воронка онбординга (30 дней)', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              children: stages.asMap().entries.map((entry) {
                final index = entry.key;
                final stage = entry.value as Map<String, dynamic>;
                return ListTile(
                  leading: CircleAvatar(child: Text('${index + 1}')),
                  title: Text(stage['name'] ?? ''),
                  subtitle: LinearProgressIndicator(
                    value: (stage['conversion'] ?? 0.0) / 100,
                    backgroundColor: Colors.grey.shade200,
                    color: Colors.blue,
                  ),
                  trailing: Text('${stage['count']} (${stage['conversion']}%)',
                      style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                );
              }).toList(),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildTopSellersSection() {
    final sellers = (_topSellers?['top_sellers'] as List?) ?? [];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Топ продавцов (30 дней)', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
        const SizedBox(height: 16),
        Card(
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              columns: const [
                DataColumn(label: Text('Ранг'), numeric: true),
                DataColumn(label: Text('Email')),
                DataColumn(label: Text('GMV (₽)'), numeric: true),
                DataColumn(label: Text('Товаров'), numeric: true),
              ],
              rows: sellers.map((s) {
                final seller = s as Map<String, dynamic>;
                return DataRow(cells: [
                  DataCell(Text('${seller['rank']}')),
                  DataCell(Text(seller['email'] ?? '')),
                  DataCell(Text('${seller['gmv']}')),
                  DataCell(Text('${seller['items']}')),
                ]);
              }).toList(),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildChurnRiskSection() {
    final churn = _growth?['churn_risk'] as Map<String, dynamic>? ?? {};
    final users = (churn['users'] as List?) ?? [];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Text('Риск оттока (Churn Risk)', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
            const SizedBox(width: 8),
            Chip(label: Text('${users.length}'), backgroundColor: Colors.red.shade100),
          ],
        ),
        const SizedBox(height: 16),
        if (users.isEmpty)
          const Card(child: ListTile(title: Text('Нет пользователей в зоне риска')))
        else
          Card(
            child: ListView.builder(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              itemCount: users.length,
              itemBuilder: (ctx, index) {
                final u = users[index] as Map<String, dynamic>;
                return ListTile(
                  leading: const Icon(Icons.warning, color: Colors.orange),
                  title: Text(u['email'] ?? ''),
                  subtitle: Text('Зарегистрирован: ${u['created_at']?.toString().substring(0, 10)}'),
                );
              },
            ),
          ),
      ],
    );
  }
}
