import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';

/**
 * SalesChart — сложный виджет для визуализации динамики продаж.
 * Использует библиотеку fl_chart для построения столбчатых диаграмм (BarChart).
 * Позволяет сравнивать несколько товаров по количеству или сумме выплат.
 */
class SalesChart extends StatefulWidget {
  final Map<String, List<Map<String, dynamic>>> chartDataByItem; // Данные от API
  final List<String> selectedItems;                              // ID выбранных SKU
  final Function(String) onRemoveItem;                           // Удаление товара из графика
  
  const SalesChart({
    super.key,
    required this.chartDataByItem,
    required this.selectedItems,
    required this.onRemoveItem,
  });

  @override
  State<SalesChart> createState() => _SalesChartState();
}

class _SalesChartState extends State<SalesChart> {
  // Выбранная метрика для отображения: 'quantity' (штуки) или 'payout' (деньги)
  String selectedMetric = 'quantity'; 
  
  // Палитра цветов для различения разных товаров на графике
  static const List<Color> chartColors = [
    Colors.blueAccent,
    Colors.redAccent,
    Colors.greenAccent,
    Colors.orangeAccent,
    Colors.purpleAccent,
    Colors.tealAccent,
    Colors.indigoAccent,
    Colors.pinkAccent,
  ];

  @override
  Widget build(BuildContext context) {
    if (widget.chartDataByItem.isEmpty) {
      return const Center(child: Text('Нет данных для выбранных товаров'));
    }

    // 1. Формируем список всех уникальных месяцев (ось X)
    final allMonths = <String>[];
    for (final data in widget.chartDataByItem.values) {
      for (final item in data) {
        final month = item['month'] as String?;
        if (month != null && !allMonths.contains(month)) {
          allMonths.add(month);
        }
      }
    }
    allMonths.sort(); // Сортируем месяцы по порядку (YYYY-MM)

    if (allMonths.isEmpty) {
      return const Center(child: Text('Нет данных'));
    }

    // 2. Определяем максимальное значение для масштабирования оси Y
    final isQuantity = selectedMetric == 'quantity';
    double maxValue = 0;
    for (final data in widget.chartDataByItem.values) {
      for (final item in data) {
        final val = isQuantity 
            ? (item['quantity_sold'] ?? 0).toDouble()
            : (item['total_payout'] ?? 0).toDouble();
        if (val > maxValue) maxValue = val;
      }
    }

    // 3. Формируем группы столбцов (BarChartGroupData)
    // Каждая группа — это один месяц, внутри которого несколько столбцов (по числу выбранных SKU)
    final barGroups = allMonths.asMap().entries.map((entry) {
      final monthIndex = entry.key;
      final month = entry.value;

      final barRods = <BarChartRodData>[];
      
      for (int itemIndex = 0; itemIndex < widget.selectedItems.length; itemIndex++) {
        final itemKey = widget.selectedItems[itemIndex];
        final data = widget.chartDataByItem[itemKey] ?? [];
        
        // Ищем значение для конкретного месяца в данных товара
        final itemForMonth = data.firstWhere(
          (item) => item['month'] == month,
          orElse: () => {'quantity_sold': 0, 'total_payout': 0},
        );
        
        final value = isQuantity
            ? (itemForMonth['quantity_sold'] ?? 0).toDouble()
            : (itemForMonth['total_payout'] ?? 0).toDouble();

        barRods.add(
          BarChartRodData(
            toY: value,
            color: chartColors[itemIndex % chartColors.length],
            width: 12, // Ширина одного столбика
            borderRadius: const BorderRadius.vertical(top: Radius.circular(4)),
          ),
        );
      }

      return BarChartGroupData(
        x: monthIndex,
        barRods: barRods,
      );
    }).toList();

    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Блок со списком выбранных товаров (Chips)
          Padding(
            padding: const EdgeInsets.all(16),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                ...widget.selectedItems.asMap().entries.map((entry) {
                  final colorIndex = entry.key;
                  final itemKey = entry.value;
                  final parts = itemKey.split('|');
                  final displayLabel = parts[0].isNotEmpty ? parts[0] : parts[1];
                  return Chip(
                    label: Text(displayLabel),
                    backgroundColor: chartColors[colorIndex % chartColors.length].withOpacity(0.3),
                    deleteIcon: const Icon(Icons.close),
                    onDeleted: () => widget.onRemoveItem(itemKey),
                  );
                }).toList(),
              ],
            ),
          ),

          // Переключатель метрики (Кол-во / Сумма)
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                const Text('Метрика: ', style: TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(width: 12),
                SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(value: 'quantity', label: Text('Кол-во шт.')),
                    ButtonSegment(value: 'payout', label: Text('Сумма ₽')),
                  ],
                  selected: <String>{selectedMetric},
                  onSelectionChanged: (newSelection) => setState(() => selectedMetric = newSelection.first),
                ),
              ],
            ),
          ),

          // Виджет графика FL Chart
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: SizedBox(
              height: 400,
              child: BarChart(
                BarChartData(
                  alignment: BarChartAlignment.spaceAround,
                  maxY: maxValue > 0 ? maxValue * 1.1 : 10, // Запас 10% сверху
                  barTouchData: BarTouchData(
                    enabled: true,
                    touchTooltipData: BarTouchTooltipData(
                      getTooltipColor: (_) => Colors.grey.shade800,
                      tooltipPadding: const EdgeInsets.all(8),
                    ),
                  ),
                  titlesData: FlTitlesData(
                    show: true,
                    rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                    topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                    // Настройка меток по оси X (Месяцы)
                    bottomTitles: AxisTitles(
                      sideTitles: SideTitles(
                        showTitles: true,
                        getTitlesWidget: (double value, TitleMeta meta) {
                          final index = value.toInt();
                          if (index >= 0 && index < allMonths.length) {
                            return Padding(
                              padding: const EdgeInsets.only(top: 8),
                              child: Text(allMonths[index], style: const TextStyle(fontSize: 10)),
                            );
                          }
                          return const Text('');
                        },
                        reservedSize: 28,
                      ),
                    ),
                    // Настройка меток по оси Y (Значения)
                    leftTitles: AxisTitles(
                      sideTitles: SideTitles(
                        showTitles: true,
                        reservedSize: 40,
                        getTitlesWidget: (value, meta) => Text('${value.toInt()}', style: const TextStyle(fontSize: 10)),
                      ),
                    ),
                  ),
                  gridData: const FlGridData(show: true, drawVerticalLine: false),
                  borderData: FlBorderData(show: true),
                  barGroups: barGroups,
                ),
              ),
            ),
          ),

          // Легенда графика (список соответствий цветов и товаров)
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Легенда:', style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 16, runSpacing: 8,
                  children: [
                    ...widget.selectedItems.asMap().entries.map((entry) {
                      final colorIndex = entry.key;
                      final itemKey = entry.value;
                      final parts = itemKey.split('|');
                      final displayLabel = parts[0].isNotEmpty ? parts[0] : parts[1];
                      return Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Container(width: 16, height: 16, decoration: BoxDecoration(color: chartColors[colorIndex % chartColors.length], borderRadius: BorderRadius.circular(2))),
                          const SizedBox(width: 8),
                          Text(displayLabel),
                        ],
                      );
                    }).toList(),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
