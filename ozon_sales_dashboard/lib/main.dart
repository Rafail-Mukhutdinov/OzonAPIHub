import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'services/api.dart';
import 'widgets/sales_table.dart';

void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Ozon Sales Dashboard',
      theme: ThemeData(colorSchemeSeed: Colors.blue, useMaterial3: true),
      home: const SalesDashboard(),
    );
  }
}

class SalesDashboard extends StatefulWidget {
  const SalesDashboard({super.key});
  @override
  State<SalesDashboard> createState() => _SalesDashboardState();
}

class _SalesDashboardState extends State<SalesDashboard> {
  final api = OzonApiClient();
  bool delivered = false;
  DateTime since = DateTime.now().subtract(const Duration(days: 2));
  DateTime to = DateTime.now();
  bool loading = false;
  List<Map<String, dynamic>> items = [];
  Map<String, dynamic>? totals;
  String? error;

  String _fmt(DateTime dt) =>
      DateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'").format(dt.toUtc());

  Future<void> _load() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final qs = {'since': _fmt(since), 'to': _fmt(to)};
      final data = delivered
          ? await api.getSalesRange(since: qs['since']!, to: qs['to']!)
          : await api.getSalesRaw(since: qs['since']!, to: qs['to']!);
      final list = (data['items'] as List).cast<Map<String, dynamic>>();
      setState(() {
        items = list;
        totals = data;
      });
    } catch (e) {
      setState(() {
        error = e.toString();
      });
    } finally {
      setState(() {
        loading = false;
      });
    }
  }

  Future<void> _pickDate(BuildContext ctx, bool isSince) async {
    final init = isSince ? since : to;
    final picked = await showDatePicker(
      context: ctx,
      initialDate: init,
      firstDate: DateTime(2024, 1, 1),
      lastDate: DateTime.now().add(const Duration(days: 1)),
    );
    if (picked != null) {
      setState(() {
        if (isSince) {
          since = DateTime(picked.year, picked.month, picked.day, 0, 0);
        } else {
          to = DateTime(picked.year, picked.month, picked.day, 23, 59, 59);
        }
      });
    }
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final df = DateFormat('yyyy-MM-dd');
    return Scaffold(
      appBar: AppBar(
        title: const Text('Ozon Sales Dashboard'),
        actions: [
          Row(
            children: [
              const Text('Delivered'),
              Switch(
                value: delivered,
                onChanged: (v) => setState(() => delivered = v),
              ),
            ],
          ),
          IconButton(icon: const Icon(Icons.refresh), onPressed: _load),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 12,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text('С: ${df.format(since)}'),
                ElevatedButton(
                  onPressed: () => _pickDate(context, true),
                  child: const Text('Изменить'),
                ),
                Text('По: ${df.format(to)}'),
                ElevatedButton(
                  onPressed: () => _pickDate(context, false),
                  child: const Text('Изменить'),
                ),
                ElevatedButton(onPressed: _load, child: const Text('Обновить')),
              ],
            ),
            const SizedBox(height: 12),
            if (loading) const LinearProgressIndicator(),
            if (error != null)
              Text('Ошибка: $error', style: const TextStyle(color: Colors.red)),
            Expanded(
              child: SalesTable(
                items: items,
                delivered: delivered,
                totals: totals,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
