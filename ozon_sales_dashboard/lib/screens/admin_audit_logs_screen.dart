import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import '../services/api.dart';

class AdminAuditLogsScreen extends StatefulWidget {
  const AdminAuditLogsScreen({super.key});

  @override
  State<AdminAuditLogsScreen> createState() => _AdminAuditLogsScreenState();
}

class _AdminAuditLogsScreenState extends State<AdminAuditLogsScreen> {
  late final OzonApiClient api;
  bool _loading = true;
  String? _error;
  List<Map<String, dynamic>> _logs = [];
  int _page = 1;
  final int _limit = 50;
  int _total = 0;

  @override
  void initState() {
    super.initState();
    final auth = Provider.of<AuthProvider>(context, listen: false);
    api = OzonApiClient(authProvider: auth);
    _loadLogs();
  }

  Future<void> _loadLogs() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final response = await api.dio.get('/admin/audit-logs', queryParameters: {
        'offset': (_page - 1) * _limit,
        'limit': _limit,
      });
      setState(() {
        _logs = (response.data['items'] as List).cast<Map<String, dynamic>>();
        _total = response.data['total'] ?? 0;
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _error = 'Не удалось загрузить журнал аудита.';
        _loading = false;
      });
    }
  }

  int get _totalPages => (_total / _limit).ceil().clamp(1, 999);

  @override
  Widget build(BuildContext context) {
    if (!kIsWeb) return const Scaffold(body: Center(child: Text('Web only')));

    return Scaffold(
      appBar: AppBar(
        title: const Text('Журнал аудита действий'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _loadLogs),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Text(_error!))
              : Column(
                  children: [
                    Expanded(
                      child: SingleChildScrollView(
                        scrollDirection: Axis.vertical,
                        child: SingleChildScrollView(
                          scrollDirection: Axis.horizontal,
                          child: DataTable(
                            columns: const [
                              DataColumn(label: Text('Дата')),
                              DataColumn(label: Text('Админ')),
                              DataColumn(label: Text('Действие')),
                              DataColumn(label: Text('Цель (ID)')),
                              DataColumn(label: Text('Детали')),
                            ],
                            rows: _logs.map((l) {
                              return DataRow(cells: [
                                DataCell(Text(l['created_at']?.toString().substring(0, 16) ?? '')),
                                DataCell(Text(l['admin_email'] ?? '#${l['admin_user_id']}')),
                                DataCell(Chip(label: Text(l['action_type'] ?? ''), backgroundColor: _getActionColor(l['action_type']))),
                                DataCell(Text(l['target_user_email'] ?? (l['target_user_id'] != null ? '#${l['target_user_id']}' : '—'))),
                                DataCell(Text(l['details']?.toString() ?? '')),
                              ]);
                            }).toList(),
                          ),
                        ),
                      ),
                    ),
                    _buildPaginationControls(),
                  ],
                ),
    );
  }

  Widget _buildPaginationControls() {
    return Container(
      padding: const EdgeInsets.all(16),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          IconButton(
            icon: const Icon(Icons.chevron_left),
            onPressed: _page > 1 ? () { setState(() => _page--); _loadLogs(); } : null,
          ),
          Text('Страница $_page из $_totalPages (всего $_total)'),
          IconButton(
            icon: const Icon(Icons.chevron_right),
            onPressed: _page < _totalPages ? () { setState(() => _page++); _loadLogs(); } : null,
          ),
        ],
      ),
    );
  }

  Color _getActionColor(String? action) {
    switch (action) {
      case 'block_user': return Colors.red.shade100;
      case 'impersonate': return Colors.blue.shade100;
      case 'extend_subscription':
      case 'activate_paid': return Colors.green.shade100;
      case 'purge_data': return Colors.orange.shade100;
      default: return Colors.grey.shade100;
    }
  }
}
