import 'package:flutter/material.dart';

class SalesTable extends StatelessWidget {
  final List<Map<String, dynamic>> items;
  final bool delivered;
  final Map<String, dynamic>? totals;
  const SalesTable({
    super.key,
    required this.items,
    required this.delivered,
    this.totals,
  });

  String _statusRu(String code) {
    switch (code) {
      case 'awaiting_assembly':
        return 'Ожидает сборки';
      case 'awaiting_packaging':
        return 'Ожидает упаковки';
      case 'awaiting_deliver':
        return 'Ожидает отгрузки';
      case 'delivering':
        return 'Доставляется';
      case 'delivered':
        return 'Доставлен';
      case 'canceled':
        return 'Отменён';
      default:
        return code;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        if (totals != null && totals!['by_status'] is List)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: (totals!['by_status'] as List)
                  .cast<Map<String, dynamic>>()
                  .map(
                    (s) => Chip(
                      label: Text(
                        '${_statusRu('${s['status']}')}: ${s['count']}',
                      ),
                      visualDensity: VisualDensity.compact,
                    ),
                  )
                  .toList(),
            ),
          ),
        Expanded(
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              columns: const [
                DataColumn(label: Text('offer_id')),
                DataColumn(label: Text('name')),
                DataColumn(label: Text('quantity')),
                DataColumn(label: Text('orders_count')),
                DataColumn(label: Text('payout/amount')),
              ],
              rows: items.map((it) {
                final quantity = it['quantity'] ?? it['quantity_sold'] ?? 0;
                final orders = it['orders_count'] ?? 0;
                final payout = delivered
                    ? (it['total_payout'] ?? 0)
                    : (it['amount_raw'] ?? 0);
                return DataRow(
                  cells: [
                    DataCell(Text('${it['offer_id'] ?? ''}')),
                    DataCell(
                      SizedBox(width: 360, child: Text('${it['name'] ?? ''}')),
                    ),
                    DataCell(Text('$quantity')),
                    DataCell(Text('$orders')),
                    DataCell(Text('$payout')),
                  ],
                );
              }).toList(),
            ),
          ),
        ),
        if (totals != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Row(
              children: [
                Text('Всего: items=${totals!['total_items'] ?? '-'}'),
                const SizedBox(width: 16),
                Text('orders=${totals!['total_orders'] ?? '-'}'),
                const SizedBox(width: 16),
                Text(
                  delivered
                      ? 'payout=${totals!['total_payout'] ?? '-'}'
                      : 'amount=${totals!['total_amount_raw'] ?? '-'}',
                ),
              ],
            ),
          ),
      ],
    );
  }
}
