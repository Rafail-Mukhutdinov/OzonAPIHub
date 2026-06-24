import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../services/api.dart';

class ExpensesWidget extends StatefulWidget {
  final OzonApiClient api;
  final String since;
  final String to;

  const ExpensesWidget({
    super.key,
    required this.api,
    required this.since,
    required this.to,
  });

  @override
  State<ExpensesWidget> createState() => _ExpensesWidgetState();
}

class _ExpensesWidgetState extends State<ExpensesWidget> {
  bool _isExpanded = false;
  Map<String, dynamic>? _summary;
  bool _isLoading = false;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  @override
  void didUpdateWidget(ExpensesWidget oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.since != widget.since || oldWidget.to != widget.to) {
      _loadData();
    }
  }

  Future<void> _loadData() async {
    if (!mounted) return;
    setState(() => _isLoading = true);
    try {
      final res = await widget.api.getExpensesSummary(since: widget.since, to: widget.to);
      if (mounted) {
        setState(() {
          _summary = res;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Color _getCategoryColor(String name) {
    switch (name) {
      case 'Комиссия Ozon': return const Color(0xFF005BFF);
      case 'Логистика (FBO/FBS)': return const Color(0xFFFF9900);
      case 'Реклама': return const Color(0xFFF44336);
      case 'Хранение': return const Color(0xFF9C27B0);
      case 'Эквайринг': return const Color(0xFF009688);
      case 'Штрафы и пени': return const Color(0xFF795548);
      case 'Логистика (транзакции)': return const Color(0xFFFFB74D);
      default: return const Color(0xFF607D8B);
    }
  }

  @override
  Widget build(BuildContext context) {
    final f = NumberFormat.decimalPattern('ru_RU');
    final double total = (_summary?['total'] as num?)?.toDouble() ?? 0.0;
    final categories = (_summary?['categories'] as List?)?.cast<Map<String, dynamic>>() ?? [];

    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.04),
            blurRadius: 12,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: () => setState(() => _isExpanded = !_isExpanded),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.all(8),
                      decoration: BoxDecoration(
                        color: Theme.of(context).primaryColor.withOpacity(0.1),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Icon(Icons.analytics_outlined, size: 20, color: Theme.of(context).primaryColor),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Расходы подробно',
                            style: TextStyle(fontSize: 11, color: Colors.grey[600], fontWeight: FontWeight.w500),
                          ),
                          Text(
                            '${f.format(total.abs().toInt())} ₽',
                            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: Color(0xFF1A1C1E)),
                          ),
                        ],
                      ),
                    ),
                    Icon(
                      _isExpanded ? Icons.keyboard_arrow_up : Icons.keyboard_arrow_down,
                      color: Colors.grey,
                    ),
                  ],
                ),
                AnimatedSize(
                  duration: const Duration(milliseconds: 300),
                  curve: Curves.easeInOut,
                  child: _isExpanded
                      ? Column(
                          children: [
                            const SizedBox(height: 16),
                            if (_isLoading)
                              const Center(child: Padding(padding: EdgeInsets.all(16), child: CircularProgressIndicator()))
                            else if (categories.isEmpty)
                              const Center(child: Padding(padding: EdgeInsets.all(16), child: Text('Нет расходов за период', style: TextStyle(color: Colors.grey, fontSize: 13))))
                            else
                              ...categories.map((cat) {
                                final String name = cat['name'];
                                final double amount = (cat['amount'] as num).toDouble();
                                final double percent = (cat['percent'] as num).toDouble();
                                final color = _getCategoryColor(name);

                                return Padding(
                                  padding: const EdgeInsets.only(bottom: 14),
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Row(
                                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                        children: [
                                          Text(name, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                                          Text('${f.format(amount.abs().toInt())} ₽', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold)),
                                        ],
                                      ),
                                      const SizedBox(height: 8),
                                      Stack(
                                        children: [
                                          Container(
                                            height: 6,
                                            width: double.infinity,
                                            decoration: BoxDecoration(
                                              color: const Color(0xFFF1F3F5),
                                              borderRadius: BorderRadius.circular(3),
                                            ),
                                          ),
                                          FractionallySizedBox(
                                            widthFactor: (percent / 100).clamp(0.0, 1.0),
                                            child: Container(
                                              height: 6,
                                              decoration: BoxDecoration(
                                                color: color,
                                                borderRadius: BorderRadius.circular(3),
                                              ),
                                            ),
                                          ),
                                        ],
                                      ),
                                      const SizedBox(height: 4),
                                      Text('$percent%', style: TextStyle(fontSize: 10, color: Colors.grey[500], fontWeight: FontWeight.bold)),
                                    ],
                                  ),
                                );
                              }).toList(),
                          ],
                        )
                      : const SizedBox.shrink(),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
