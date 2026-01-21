import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';

class SalesChart extends StatefulWidget {
  final Map<String, List<Map<String, dynamic>>> chartDataBySku;
  final List<String> selectedSkus;
  final Function(String) onRemoveSku;
  
  const SalesChart({
    super.key,
    required this.chartDataBySku,
    required this.selectedSkus,
    required this.onRemoveSku,
  });

  @override
  State<SalesChart> createState() => _SalesChartState();
}

class _SalesChartState extends State<SalesChart> {
  String selectedMetric = 'quantity'; // 'quantity' или 'payout'
  
  // Цвета для разных артикулов
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
    if (widget.chartDataBySku.isEmpty) {
      return const Center(child: Text('Нет данных для выбранных артикулов'));
    }

    // Получаем все месяцы из всех наборов данных
    final allMonths = <String>[];
    for (final data in widget.chartDataBySku.values) {
      for (final item in data) {
        final month = item['month'] as String?;
        if (month != null && !allMonths.contains(month)) {
          allMonths.add(month);
        }
      }
    }
    allMonths.sort();

    if (allMonths.isEmpty) {
      return const Center(child: Text('Нет данных'));
    }

    // Построение графика
    final isQuantity = selectedMetric == 'quantity';
    
    // Максимальное значение для оси Y
    double maxValue = 0;
    for (final data in widget.chartDataBySku.values) {
      for (final item in data) {
        final val = isQuantity 
            ? (item['quantity_sold'] ?? 0).toDouble()
            : (item['total_payout'] ?? 0).toDouble();
        if (val > maxValue) maxValue = val;
      }
    }

    // Группы столбцов для каждого месяца
    final barGroups = allMonths.asMap().entries.map((entry) {
      final monthIndex = entry.key;
      final month = entry.value;

      final barRods = <BarChartRodData>[];
      
      for (int skuIndex = 0; skuIndex < widget.selectedSkus.length; skuIndex++) {
        final sku = widget.selectedSkus[skuIndex];
        final data = widget.chartDataBySku[sku] ?? [];
        
        // Найдём значение для этого месяца
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
            color: chartColors[skuIndex % chartColors.length],
            width: 12,
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
          // Выбранные артикулы с кнопками удаления
          Padding(
            padding: const EdgeInsets.all(16),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                ...widget.selectedSkus.asMap().entries.map((entry) {
                  final colorIndex = entry.key;
                  final sku = entry.value;
                  return Chip(
                    label: Text(sku),
                    backgroundColor: chartColors[colorIndex % chartColors.length].withOpacity(0.3),
                    deleteIcon: const Icon(Icons.close),
                    onDeleted: () => widget.onRemoveSku(sku),
                  );
                }).toList(),
              ],
            ),
          ),

          // Выбор метрики
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                const Text(
                  'Метрика: ',
                  style: TextStyle(fontWeight: FontWeight.bold),
                ),
                const SizedBox(width: 12),
                SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(
                      value: 'quantity',
                      label: Text('Кол-во'),
                    ),
                    ButtonSegment(
                      value: 'payout',
                      label: Text('Сумма (₽)'),
                    ),
                  ],
                  selected: <String>{selectedMetric},
                  onSelectionChanged: (newSelection) {
                    setState(() {
                      selectedMetric = newSelection.first;
                    });
                  },
                ),
              ],
            ),
          ),

          // График
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: SizedBox(
              height: 400,
              child: BarChart(
                BarChartData(
                  alignment: BarChartAlignment.spaceAround,
                  maxY: maxValue > 0 ? maxValue * 1.1 : 10,
                  barTouchData: BarTouchData(
                    enabled: true,
                    touchTooltipData: BarTouchTooltipData(
                      getTooltipColor: (_) => Colors.grey.shade800,
                      tooltipPadding: const EdgeInsets.all(8),
                      tooltipMargin: 8,
                    ),
                  ),
                  titlesData: FlTitlesData(
                    show: true,
                    rightTitles: const AxisTitles(
                      sideTitles: SideTitles(showTitles: false),
                    ),
                    topTitles: const AxisTitles(
                      sideTitles: SideTitles(showTitles: false),
                    ),
                    bottomTitles: AxisTitles(
                      sideTitles: SideTitles(
                        showTitles: true,
                        getTitlesWidget: (double value, TitleMeta meta) {
                          final index = value.toInt();
                          if (index >= 0 && index < allMonths.length) {
                            return Padding(
                              padding: const EdgeInsets.only(top: 8),
                              child: Text(
                                allMonths[index],
                                style: const TextStyle(fontSize: 10),
                              ),
                            );
                          }
                          return const Text('');
                        },
                        reservedSize: 28,
                      ),
                    ),
                    leftTitles: AxisTitles(
                      sideTitles: SideTitles(
                        showTitles: true,
                        getTitlesWidget: (double value, TitleMeta meta) {
                          if (value == meta.max) {
                            return const Text('');
                          }
                          return Text(
                            '${value.toInt()}',
                            style: const TextStyle(fontSize: 10),
                          );
                        },
                        reservedSize: 40,
                      ),
                    ),
                  ),
                  gridData: const FlGridData(show: true),
                  borderData: FlBorderData(show: true),
                  barGroups: barGroups,
                ),
              ),
            ),
          ),

          // Легенда
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Легенда:',
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 16,
                  runSpacing: 8,
                  children: [
                    ...widget.selectedSkus.asMap().entries.map((entry) {
                      final colorIndex = entry.key;
                      final sku = entry.value;
                      return Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Container(
                            width: 16,
                            height: 16,
                            decoration: BoxDecoration(
                              color: chartColors[colorIndex % chartColors.length],
                              borderRadius: BorderRadius.circular(2),
                            ),
                          ),
                          const SizedBox(width: 8),
                          Text(sku),
                        ],
                      );
                    }).toList(),
                  ],
                ),
                const SizedBox(height: 16),
                Text(
                  'Период: ${allMonths.first} - ${allMonths.last}',
                  style: const TextStyle(fontSize: 12, color: Colors.grey),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
