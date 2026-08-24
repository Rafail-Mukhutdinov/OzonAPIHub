import 'package:flutter/material.dart';

/**
 * SalesTable — виджет для отображения списка товаров в виде таблицы.
 * Поддерживает горизонтальную прокрутку (для мобильных устройств)
 * и автоматический расчет итогов в нижней строке.
 */
class SalesTable extends StatelessWidget {
  final List<Map<String, dynamic>> items; // Список товаров
  final bool delivered;                   // Флаг режима (Финансы или Отгрузки)
  final Map<String, dynamic>? totals;     // Общие итоги от сервера
  
  const SalesTable({
    super.key,
    required this.items,
    required this.delivered,
    this.totals,
  });

  // Вспомогательная функция для локализации статусов
  String _statusRu(String code) {
    switch (code) {
      case 'awaiting_assembly': return 'Ожидает сборки';
      case 'awaiting_packaging': return 'Ожидает упаковки';
      case 'awaiting_deliver': return 'Ожидает отгрузки';
      case 'delivering': return 'Доставляется';
      case 'delivered': return 'Доставлен';
      case 'cancelled': return 'Отменён';
      default: return code;
    }
  }

  @override
  Widget build(BuildContext context) {
    // SingleChildScrollView позволяет скроллить таблицу вбок, если она не влезает по ширине
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Отображение "чипсов" со статусами над таблицей (информационная панель)
          if (totals != null && totals?['by_status'] is List)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Wrap(
                spacing: 8, runSpacing: 8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: (totals?['by_status'] as List)
                    .cast<Map<String, dynamic>>()
                    .map((s) => Chip(
                        label: Text('${_statusRu('${s['status']}')}: ${s['count']}'),
                        visualDensity: VisualDensity.compact,
                      ))
                    .toList(),
              ),
            ),
          
          // Сама таблица данных
          DataTable(
            columns: const [
              DataColumn(label: Text('Артикул (Offer ID)')),
              DataColumn(label: Text('Наименование товара')),
              DataColumn(label: Text('Кол-во шт.')),
              DataColumn(label: Text('Заказов')),
              DataColumn(label: Text('Выплата (руб)')),
            ],
            rows: [
              // Генерация строк на основе списка товаров
              ...items.map((it) {
                // Обработка различий в именовании полей между разными эндпоинтами бэкенда
                final quantity = it['quantity'] ?? it['quantity_sold'] ?? 0;
                final orders = it['orders_count'] ?? 0;
                final payout = delivered
                    ? (it['total_payout'] ?? 0)
                    : (it['amount_raw'] ?? 0);
                
                return DataRow(
                  cells: [
                    DataCell(Text('${it['offer_id'] ?? ''}')),
                    DataCell(SizedBox(width: 360, child: Text('${it['name'] ?? ''}', maxLines: 2, overflow: TextOverflow.ellipsis))),
                    DataCell(Text('$quantity')),
                    DataCell(Text('$orders')),
                    DataCell(Text('$payout')),
                  ],
                );
              }),
              
              // Итоговая строка (выделена серым фоном)
              if (items.isNotEmpty)
                DataRow(
                  color: MaterialStateProperty.all(Colors.grey.shade200),
                  cells: [
                    const DataCell(Text('ИТОГО', style: TextStyle(fontWeight: FontWeight.bold))),
                    const DataCell(Text('')),
                    DataCell(Text(
                      items.fold<num>(0, (sum, it) => sum + (it['quantity'] ?? it['quantity_sold'] ?? 0)).toInt().toString(),
                      style: const TextStyle(fontWeight: FontWeight.bold),
                    )),
                    DataCell(Text(
                      items.fold<num>(0, (sum, it) => sum + (it['orders_count'] ?? 0)).toInt().toString(),
                      style: const TextStyle(fontWeight: FontWeight.bold),
                    )),
                    DataCell(Text(
                      items.fold<num>(0, (sum, it) => sum + (delivered ? (it['total_payout'] ?? 0) : (it['amount_raw'] ?? 0))).toInt().toString(),
                      style: const TextStyle(fontWeight: FontWeight.bold),
                    )),
                  ],
                ),
            ],
          ),
          
          // Футер таблицы с дополнительной статистикой от сервера
          if (totals != null)
            Padding(
              padding: const EdgeInsets.only(top: 8, left: 12, right: 12, bottom: 12),
              child: Wrap(
                spacing: 24, runSpacing: 8,
                children: [
                  Text('Уникальных: ${items.length}'),
                  Text('Всего штук: ${totals?['total_items'] ?? '-'}'),
                  Text('Всего заказов: ${totals?['total_orders'] ?? '-'}'),
                  Text(
                    delivered
                        ? 'К выплате: ${totals?['total_payout'] ?? '-'} ₽'
                        : 'Грязная сумма: ${totals?['total_amount_raw'] ?? '-'} ₽',
                    style: TextStyle(fontWeight: FontWeight.bold, color: Theme.of(context).primaryColor),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
