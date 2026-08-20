import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import '../services/api.dart';

/// Экремен мониторинга здоровья системы (Web-only).
/// Показывает: ошибки синхронизации, зависшие задачи, размеры БД, статусы очередей.
class AdminHealthScreen extends StatefulWidget {
  const AdminHealthScreen({super.key});

  @override
  State<AdminHealthScreen> createState() => _AdminHealthScreenState();
}

class _AdminHealthScreenState extends State<AdminHealthScreen>
    with SingleTickerProviderStateMixin {
  late final OzonApiClient api;
  late final TabController _tabController;

  Map<String, dynamic>? _syncFailures;
  Map<String, dynamic>? _dbStats;
  Map<String, dynamic>? _queueHealth;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    final auth = Provider.of<AuthProvider>(context, listen: false);
    api = OzonApiClient(authProvider: auth);
    _loadAll();
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  Future<void> _loadAll() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final results = await Future.wait([
        api.dio.get('/admin/health/sync-failures'),
        api.dio.get('/admin/health/db-stats'),
        api.dio.get('/admin/health/queue'),
      ]);

      if (mounted) {
        setState(() {
          _syncFailures = results[0].data as Map<String, dynamic>?;
          _dbStats = results[1].data as Map<String, dynamic>?;
          _queueHealth = results[2].data as Map<String, dynamic>?;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = 'Ошибка загрузки данных мониторинга.';
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!kIsWeb) {
      return Scaffold(
        appBar: AppBar(title: const Text('Мониторинг')),
        body: const Center(child: Text('Доступно только в веб-версии')),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Мониторинг системы'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _loadAll, tooltip: 'Обновить'),
        ],
        bottom: TabBar(
          controller: _tabController,
          tabs: const [
            Tab(icon: Icon(Icons.sync_problem), text: 'Синхронизация'),
            Tab(icon: Icon(Icons.storage), text: 'База данных'),
            Tab(icon: Icon(Icons.queue), text: 'Очереди'),
          ],
        ),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(_error!, style: const TextStyle(color: Colors.red)),
                      const SizedBox(height: 16),
                      ElevatedButton(onPressed: _loadAll, child: const Text('Повторить')),
                    ],
                  ),
                )
              : TabBarView(
                  controller: _tabController,
                  children: [
                    _buildSyncFailuresTab(),
                    _buildDbStatsTab(),
                    _buildQueueTab(),
                  ],
                ),
    );
  }

  // ==================== TAB 1: Sync Failures ====================

  Widget _buildSyncFailuresTab() {
    final errors = (_syncFailures?['errors'] as List?) ?? [];
    final stuck = (_syncFailures?['stuck'] as List?) ?? [];
    final total = _syncFailures?['total'] ?? 0;

    return RefreshIndicator(
      onRefresh: _loadAll,
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _SummaryRow(
              items: [
                _SummaryItem(label: 'Всего проблем', value: '$total', color: Colors.red),
                _SummaryItem(label: 'Ошибки', value: '${errors.length}', color: Colors.orange),
                _SummaryItem(label: 'Зависшие', value: '${stuck.length}', color: Colors.purple),
              ],
            ),
            const SizedBox(height: 24),
            if (errors.isNotEmpty) ...[
              _SectionTitle(title: 'Ошибки синхронизации', color: Colors.orange),
              const SizedBox(height: 8),
              ...errors.map((e) => _SyncIssueCard(data: e as Map<String, dynamic>)),
              const SizedBox(height: 24),
            ],
            if (stuck.isNotEmpty) ...[
              _SectionTitle(title: 'Зависшие задачи', color: Colors.purple),
              const SizedBox(height: 8),
              ...stuck.map((e) => _SyncIssueCard(data: e as Map<String, dynamic>, isStuck: true)),
            ],
            if (errors.isEmpty && stuck.isEmpty)
              const Card(
                child: ListTile(
                  leading: Icon(Icons.check_circle, color: Colors.green, size: 40),
                  title: Text('Проблем не обнаружено'),
                  subtitle: Text('Все синхронизации работают нормально'),
                ),
              ),
          ],
        ),
      ),
    );
  }

  // ==================== TAB 2: DB Stats ====================

  Widget _buildDbStatsTab() {
    final tables = (_dbStats?['tables'] as List?) ?? [];
    final totalSize = _dbStats?['total_db_size_bytes'] ?? 0;
    final heavyUsers = (_dbStats?['top_heavy_users'] as List?) ?? [];

    return RefreshIndicator(
      onRefresh: _loadAll,
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Card(
              color: Colors.blue.shade50,
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  children: [
                    const Icon(Icons.storage, size: 40, color: Colors.blue),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('Общий размер БД', style: TextStyle(color: Colors.grey)),
                          Text(_formatBytes(totalSize),
                              style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: Colors.blue)),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 24),
            const Text('Размеры таблиц', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Card(
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: DataTable(
                  columns: const [
                    DataColumn(label: Text('Таблица')),
                    DataColumn(label: Text('Размер'), numeric: true),
                    DataColumn(label: Text('Строк'), numeric: true),
                  ],
                  rows: tables.map((t) {
                    final table = t as Map<String, dynamic>;
                    return DataRow(
                      cells: [
                        DataCell(Text(table['table'] ?? '')),
                        DataCell(Text(table['size_pretty'] ?? 'N/A')),
                        DataCell(Text(_formatNumber(table['rows'] ?? 0))),
                      ],
                    );
                  }).toList(),
                ),
              ),
            ),
            const SizedBox(height: 24),
            if (heavyUsers.isNotEmpty) ...[
              const Text('Топ «тяжёлых» пользователей', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Card(
                child: ListView.builder(
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  itemCount: heavyUsers.length,
                  itemBuilder: (context, index) {
                    final u = heavyUsers[index] as Map<String, dynamic>;
                    return ListTile(
                      leading: CircleAvatar(child: Text('${index + 1}')),
                      title: Text(u['email'] ?? 'Unknown'),
                      subtitle: Text('${_formatNumber(u['order_postings_count'] ?? 0)} постингов'),
                    );
                  },
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  // ==================== TAB 3: Queue Health ====================

  Widget _buildQueueTab() {
    final arqAvailable = _queueHealth?['arq_available'] ?? false;
    final activeSyncs = _queueHealth?['active_syncs'] as Map<String, dynamic>? ?? {};
    final recentCompleted = _queueHealth?['recent_completed_24h'] ?? 0;
    final details = (_queueHealth?['active_details'] as List?) ?? [];

    return RefreshIndicator(
      onRefresh: _loadAll,
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Card(
              color: arqAvailable ? Colors.green.shade50 : Colors.red.shade50,
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  children: [
                    Icon(
                      arqAvailable ? Icons.check_circle : Icons.error,
                      size: 40,
                      color: arqAvailable ? Colors.green : Colors.red,
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('ARQ Queue Pool', style: TextStyle(color: Colors.grey)),
                          Text(
                            arqAvailable ? 'Доступен' : 'НЕДОСТУПЕН',
                            style: TextStyle(
                              fontSize: 20,
                              fontWeight: FontWeight.bold,
                              color: arqAvailable ? Colors.green : Colors.red,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 24),
            _SummaryRow(
              items: [
                _SummaryItem(
                  label: 'Активных синхр.',
                  value: '${activeSyncs['count'] ?? 0}',
                  color: Colors.blue,
                ),
                _SummaryItem(
                  label: 'Backfill в работе',
                  value: '${activeSyncs['backfill_in_progress'] ?? 0}',
                  color: Colors.orange,
                ),
                _SummaryItem(
                  label: 'Завершено (24ч)',
                  value: '$recentCompleted',
                  color: Colors.green,
                ),
              ],
            ),
            const SizedBox(height: 24),
            if (details.isNotEmpty) ...[
              const Text('Активные синхронизации', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              ...details.map((d) => _ActiveSyncCard(data: d as Map<String, dynamic>)),
            ] else
              const Card(
                child: ListTile(
                  leading: Icon(Icons.pause_circle, color: Colors.grey, size: 40),
                  title: Text('Нет активных синхронизаций'),
                ),
              ),
          ],
        ),
      ),
    );
  }

  String _formatNumber(dynamic value) {
    final num v = value is int ? value : value;
    return v.toInt().toString();
  }

  String _formatBytes(dynamic bytes) {
    final num b = bytes is int ? bytes : bytes;
    if (b == 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    int unitIndex = 0;
    double size = b.toDouble();
    while (size > 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex++;
    }
    return '${size.toStringAsFixed(1)} ${units[unitIndex]}';
  }
}

// ==================== Вспомогательные виджеты ====================

class _SummaryRow extends StatelessWidget {
  final List<_SummaryItem> items;
  const _SummaryRow({required this.items});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: items
              .map((item) => Expanded(child: item))
              .toList(),
        ),
      ),
    );
  }
}

class _SummaryItem extends StatelessWidget {
  final String label;
  final String value;
  final Color color;
  const _SummaryItem({required this.label, required this.value, required this.color});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(value, style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold, color: color)),
        const SizedBox(height: 4),
        Text(label, style: const TextStyle(fontSize: 12, color: Colors.grey), textAlign: TextAlign.center),
      ],
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String title;
  final Color color;
  const _SectionTitle({required this.title, required this.color});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(width: 4, height: 20, color: color),
        const SizedBox(width: 8),
        Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
      ],
    );
  }
}

class _SyncIssueCard extends StatelessWidget {
  final Map<String, dynamic> data;
  final bool isStuck;
  const _SyncIssueCard({required this.data, this.isStuck = false});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        leading: Icon(
          isStuck ? Icons.hourglass_empty : Icons.error_outline,
          color: isStuck ? Colors.purple : Colors.orange,
        ),
        title: Text(data['user_email'] ?? 'User #${data['user_id']}'),
        subtitle: Text(data['status_message'] ?? ''),
        trailing: Text(
          data['last_sync_attempt_at'] != null
              ? data['last_sync_attempt_at'].toString().substring(0, 16)
              : '',
          style: const TextStyle(fontSize: 12, color: Colors.grey),
        ),
      ),
    );
  }
}

class _ActiveSyncCard extends StatelessWidget {
  final Map<String, dynamic> data;
  const _ActiveSyncCard({required this.data});

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        leading: Icon(
          data['is_backfill'] == true ? Icons.cloud_download : Icons.sync,
          color: data['is_backfill'] == true ? Colors.orange : Colors.blue,
        ),
        title: Text(data['user_email'] ?? 'User #${data['user_id']}'),
        subtitle: Text('${data['status_message']} • ${data['duration_seconds']}с'),
      ),
    );
  }
}