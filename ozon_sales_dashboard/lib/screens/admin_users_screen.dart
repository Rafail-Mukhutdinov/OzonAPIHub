import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import '../services/api.dart';

/// Экран управления пользователями (Web-only).
/// DataTable с поиском, фильтрами, пагинацией и действиями.
class AdminUsersScreen extends StatefulWidget {
  const AdminUsersScreen({super.key});

  @override
  State<AdminUsersScreen> createState() => _AdminUsersScreenState();
}

class _AdminUsersScreenState extends State<AdminUsersScreen> {
  late final OzonApiClient api;

  List<Map<String, dynamic>> _users = [];
  int _total = 0;
  int _page = 1;
  final int _limit = 20;
  bool _loading = true;
  String? _error;

  // Фильтры
  final _searchController = TextEditingController();
  String? _filterActive;
  String? _filterDemo;

  @override
  void initState() {
    super.initState();
    final auth = Provider.of<AuthProvider>(context, listen: false);
    api = OzonApiClient(authProvider: auth);
    _loadUsers();
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _loadUsers() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final response = await api.dio.get('/admin/users', queryParameters: {
        'page': _page,
        'limit': _limit,
        if (_searchController.text.isNotEmpty) 'search': _searchController.text,
        if (_filterActive != null) 'is_active': _filterActive == 'true',
        if (_filterDemo != null) 'is_demo': _filterDemo == 'true',
      });

      final data = response.data as Map<String, dynamic>?;
      if (mounted) {
        setState(() {
          _users = (data?['items'] as List?)?.cast<Map<String, dynamic>>() ?? [];
          _total = data?['total'] ?? 0;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = 'Не удалось загрузить пользователей.';
          _loading = false;
        });
      }
    }
  }

  int get _totalPages => (_total / _limit).ceil().clamp(1, 9999);

  @override
  Widget build(BuildContext context) {
    if (!kIsWeb) {
      return Scaffold(
        appBar: AppBar(title: const Text('Пользователи')),
        body: const Center(child: Text('Доступно только в веб-версии')),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Управление пользователями'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _loadUsers, tooltip: 'Обновить'),
        ],
      ),
      body: Column(
        children: [
          // Панель фильтров
          _buildFilterBar(),
          // Информация о пагинации
          _buildPaginationInfo(),
          // Таблица
          Expanded(child: _buildTable()),
          // Панель пагинации
          _buildPaginationControls(),
        ],
      ),
    );
  }

  Widget _buildFilterBar() {
    return Container(
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Expanded(
            flex: 3,
            child: TextField(
              controller: _searchController,
              decoration: const InputDecoration(
                labelText: 'Поиск (email или ID)',
                prefixIcon: Icon(Icons.search),
                border: OutlineInputBorder(),
              ),
              onSubmitted: (_) => _applyFilters(),
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: DropdownButtonFormField<String>(
              initialValue: _filterActive,
              decoration: const InputDecoration(
                labelText: 'Статус',
                border: OutlineInputBorder(),
              ),
              items: const [
                DropdownMenuItem(value: null, child: Text('Все')),
                DropdownMenuItem(value: 'true', child: Text('Активные')),
                DropdownMenuItem(value: 'false', child: Text('Заблокированные')),
              ],
              onChanged: (v) => setState(() => _filterActive = v),
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: DropdownButtonFormField<String>(
              initialValue: _filterDemo,
              decoration: const InputDecoration(
                labelText: 'Тип',
                border: OutlineInputBorder(),
              ),
              items: const [
                DropdownMenuItem(value: null, child: Text('Все')),
                DropdownMenuItem(value: 'true', child: Text('Demo')),
                DropdownMenuItem(value: 'false', child: Text('Paid')),
              ],
              onChanged: (v) => setState(() => _filterDemo = v),
            ),
          ),
          const SizedBox(width: 16),
          ElevatedButton.icon(
            onPressed: _applyFilters,
            icon: const Icon(Icons.filter_list),
            label: const Text('Применить'),
          ),
        ],
      ),
    );
  }

  void _applyFilters() {
    _page = 1;
    _loadUsers();
  }

  Widget _buildPaginationInfo() {
    final from = _total == 0 ? 0 : ((_page - 1) * _limit) + 1;
    final to = (_page * _limit).clamp(0, _total);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Align(
        alignment: Alignment.centerLeft,
        child: Text('Показано $from–$to из $_total', style: TextStyle(color: Colors.grey.shade600)),
      ),
    );
  }

  Widget _buildTable() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(_error!, style: const TextStyle(color: Colors.red)),
            const SizedBox(height: 16),
            ElevatedButton(onPressed: _loadUsers, child: const Text('Повторить')),
          ],
        ),
      );
    }
    if (_users.isEmpty) {
      return const Center(child: Text('Пользователи не найдены'));
    }

    return SingleChildScrollView(
      scrollDirection: Axis.vertical,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: DataTable(
          columns: const [
            DataColumn(label: Text('ID'), numeric: true),
            DataColumn(label: Text('Email')),
            DataColumn(label: Text('Статус')),
            DataColumn(label: Text('Тип')),
            DataColumn(label: Text('Ключи')),
            DataColumn(label: Text('Подписка до')),
            DataColumn(label: Text('Действия')),
          ],
          rows: _users.map((u) {
            return DataRow(
              cells: [
                DataCell(Text('${u['id'] ?? ''}')),
                DataCell(
                  Row(
                    children: [
                      if (u['is_admin'] == true)
                        const Padding(
                          padding: EdgeInsets.only(right: 4),
                          child: Icon(Icons.admin_panel_settings, size: 16, color: Colors.amber),
                        ),
                      Text(u['email'] ?? ''),
                    ],
                  ),
                ),
                DataCell(
                  u['is_active'] == true
                      ? const Chip(label: Text('Active'), backgroundColor: Colors.green)
                      : const Chip(label: Text('Blocked'), backgroundColor: Colors.red),
                ),
                DataCell(
                  u['is_demo'] == true
                      ? const Chip(label: Text('Demo'))
                      : const Chip(label: Text('Paid'), backgroundColor: Colors.blue),
                ),
                DataCell(
                  u['has_credentials'] == true
                      ? const Icon(Icons.check, color: Colors.green)
                      : const Icon(Icons.close, color: Colors.red),
                ),
                DataCell(Text(u['subscription_end_date']?.toString().substring(0, 10) ?? '—')),
                DataCell(_buildActionButtons(u)),
              ],
            );
          }).toList(),
        ),
      ),
    );
  }

  Widget _buildActionButtons(Map<String, dynamic> user) {
    final userId = user['id'] as int;
    final isActive = user['is_active'] == true;

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        IconButton(
          icon: Icon(isActive ? Icons.block : Icons.check_circle, color: isActive ? Colors.orange : Colors.green),
          tooltip: isActive ? 'Заблокировать' : 'Разблокировать',
          onPressed: () => _toggleBlock(userId, isActive),
        ),
        IconButton(
          icon: const Icon(Icons.person_search, color: Colors.blue),
          tooltip: 'Impersonate',
          onPressed: () => _impersonate(userId, user['email']),
        ),
        IconButton(
          icon: const Icon(Icons.sync, color: Colors.purple),
          tooltip: 'Запустить синхр.',
          onPressed: () => _triggerSync(userId),
        ),
        IconButton(
          icon: const Icon(Icons.card_membership, color: Colors.teal),
          tooltip: 'Подписка',
          onPressed: () => _manageSubscription(user),
        ),
      ],
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
            onPressed: _page > 1 ? () => _goToPage(_page - 1) : null,
          ),
          Text('Страница $_page из $_totalPages'),
          IconButton(
            icon: const Icon(Icons.chevron_right),
            onPressed: _page < _totalPages ? () => _goToPage(_page + 1) : null,
          ),
        ],
      ),
    );
  }

  void _goToPage(int p) {
    setState(() => _page = p);
    _loadUsers();
  }

  // ==================== Actions ====================

  Future<void> _toggleBlock(int userId, bool isActive) async {
    final action = isActive ? 'Заблокировать' : 'Разблокировать';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('$action пользователя?'),
        content: Text('Вы уверены, что хотите $action этого пользователя?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Отмена')),
          ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: Text(action)),
        ],
      ),
    );

    if (confirmed != true) return;

    try {
      await api.dio.post('/admin/users/$userId/${isActive ? 'block' : 'unblock'}');
      _showSnack('Пользователь ${isActive ? 'заблокирован' : 'разблокирован'}', Colors.green);
      _loadUsers();
    } catch (e) {
      _showSnack('Ошибка операции', Colors.red);
    }
  }

  Future<void> _impersonate(int userId, String? email) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Войти под пользователем?'),
        content: Text('Вы войдёте в аккаунт "$email" на 10 минут.\nВсе действия будут записаны в журнал аудита.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Отмена')),
          ElevatedButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Войти')),
        ],
      ),
    );

    if (confirmed != true) return;

    try {
      final resp = await api.dio.post('/admin/users/$userId/impersonate');
      final data = resp.data as Map<String, dynamic>?;
      final token = data?['access_token'] as String?;

      if (token != null && mounted) {
        final auth = Provider.of<AuthProvider>(context, listen: false);
        await auth.enterImpersonation(token, email ?? 'User #$userId');
        
        if (mounted) {
          Navigator.of(context).popUntil((route) => route.isFirst);
          _showSnack('Вы вошли под пользователем $email', Colors.blue);
        }
      }
    } catch (e) {
      _showSnack('Ошибка impersonation', Colors.red);
    }
  }

  Future<void> _triggerSync(int userId) async {
    try {
      await api.dio.post('/admin/users/$userId/sync/trigger');
      _showSnack('Синхронизация запущена', Colors.green);
    } on Exception catch (e) {
      String msg = 'Ошибка запуска синхронизации';
      // DioException содержит response
      try {
        final dioErr = e as dynamic;
        if (dioErr.response?.statusCode == 409) {
          msg = dioErr.response?.data?['detail'] ?? msg;
        }
      } catch (_) {}
      _showSnack(msg, Colors.orange);
    }
  }

  Future<void> _manageSubscription(Map<String, dynamic> user) async {
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (ctx) => _SubscriptionDialog(user: user),
    );

    if (result == null) return;

    try {
      if (result['action'] == 'extend') {
        await api.dio.post('/admin/users/${user['id']}/subscription/extend', data: {
          'days': result['days'],
          'reason': result['reason'],
          'keep_demo': result['keep_demo'],
        });
      } else if (result['action'] == 'activate') {
        await api.dio.post('/admin/users/${user['id']}/subscription/activate-paid', data: {
          'days': result['days'],
          'reason': result['reason'],
          'make_demo': result['make_demo'],
        });
      }
      _showSnack('Подписка обновлена', Colors.green);
      _loadUsers();
    } catch (e) {
      _showSnack('Ошибка обновления подписки', Colors.red);
    }
  }

  void _showSnack(String msg, Color color) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), backgroundColor: color, behavior: SnackBarBehavior.floating),
    );
  }
}

class _SubscriptionDialog extends StatefulWidget {
  final Map<String, dynamic> user;
  const _SubscriptionDialog({required this.user});

  @override
  State<_SubscriptionDialog> createState() => _SubscriptionDialogState();
}

class _SubscriptionDialogState extends State<_SubscriptionDialog> {
  final _reasonController = TextEditingController();
  int _days = 30;
  String _mode = 'premium'; // 'premium' или 'demo'

  @override
  void initState() {
    super.initState();
    // Инициализируем режим текущим статусом пользователя
    _mode = widget.user['is_demo'] == true ? 'demo' : 'premium';
  }

  @override
  void dispose() {
    _reasonController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('Подписка: ${widget.user['email']}'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Выберите режим доступа:', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'demo', label: Text('Demo'), icon: Icon(Icons.timer_outlined)),
                ButtonSegment(value: 'premium', label: Text('Premium'), icon: Icon(Icons.verified_user)),
              ],
              selected: {_mode},
              onSelectionChanged: (Set<String> newSelection) {
                setState(() => _mode = newSelection.first);
              },
            ),
            const SizedBox(height: 24),
            Row(
              children: [
                const Text('Добавить дней: '),
                Expanded(
                  child: Slider(
                    value: _days.toDouble(),
                    min: -90,
                    max: 365,
                    divisions: 455,
                    label: '$_days',
                    onChanged: (v) => setState(() => _days = v.round()),
                  ),
                ),
                Text('$_days', style: const TextStyle(fontWeight: FontWeight.bold)),
              ],
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _reasonController,
              decoration: const InputDecoration(
                labelText: 'Причина изменения',
                border: OutlineInputBorder(),
                hintText: 'Напр: компенсация за сбой или покупка тарифа',
              ),
              maxLines: 2,
            ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Отмена')),
        ElevatedButton(
          onPressed: () {
            if (_reasonController.text.trim().isEmpty) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Укажите причину')),
              );
              return;
            }

            final bool currentIsDemo = widget.user['is_demo'] == true;
            final bool targetIsDemo = _mode == 'demo';

            // Если режим меняется (напр с Premium на Demo) - используем activate (полная перезапись)
            // Если режим НЕ меняется - используем extend (продление)
            if (currentIsDemo == targetIsDemo) {
              Navigator.pop(context, {
                'action': 'extend',
                'days': _days,
                'keep_demo': targetIsDemo,
                'reason': _reasonController.text.trim(),
              });
            } else {
              Navigator.pop(context, {
                'action': 'activate',
                'days': _days,
                'make_demo': targetIsDemo,
                'reason': _reasonController.text.trim(),
              });
            }
          },
          child: const Text('Сохранить'),
        ),
      ],
    );
  }
}