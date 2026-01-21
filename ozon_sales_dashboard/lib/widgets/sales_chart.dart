import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';

class SalesChart extends StatefulWidget {
  final List<Map<String, dynamic>> monthlyData;
  final String selectedSku;
  
  const SalesChart({
    super.key,
    required this.monthlyData,
    required this.selectedSku,
  });

  @override
  State<SalesChart> createState() => _SalesChartState();
}

class _SalesChartState extends State<SalesChart> {
  String selectedMetric = 'quantity'; // 'quantity' или 'payout'

  @override
  Widget build(BuildContext context) {
    if (widget.monthlyData.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Text(
            'Нет данных для артикула ${widget.selectedSku}',
            textAlign: TextAlign.center,
          ),
        ),
      );
    }

    final isQuantity = selectedMetric == 'quantity';
    final maxValue = widget.monthlyData
        .fold<num>(0, (max, item) {
          final val = isQuantity 
              ? (item['quantity_sold'] ?? 0) 
              : (item['total_payout'] ?? 0);
          return val > max ? val : max;
        })
        .toDouble();

    final barGroups = widget.monthlyData.asMap().entries.map((entry) {
      final index = entry.key;
      final item = entry.value;
      final value = isQuantity
          ? (item['quantity_sold'] ?? 0).toDouble()
          : (item['total_payout'] ?? 0).toDouble();

      return BarChartGroupData(
        x: index,
        barRods: [
          BarChartRodData(
            toY: value,
            color: Colors.blueAccent,
            width: 12,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(4)),
          ),
        ],
      );
    }).toList();

    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
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
                      getTooltipText: (group, groupIndex, rod, rodIndex) {
                        final item = widget.monthlyData[groupIndex];
                        final month = item['month'] ?? '';
                        final qty = item['quantity_sold'] ?? 0;
                        final sum = item['total_payout'] ?? 0;
                        final orders = item['orders_count'] ?? 0;
                        return TextSpan(
                          children: [
                            TextSpan(
                              text: '$month\n',
                              style: const TextStyle(
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                            TextSpan(
                              text: 'Кол-во: $qty\n',
                            ),
                            TextSpan(
                              text: 'Сумма: $sum ₽\n',
                            ),
                            TextSpan(
                              text: 'Заказов: $orders',
                            ),
                          ],
                        );
                      },
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
                          if (index >= 0 && index < widget.monthlyData.length) {
                            final month =
                                widget.monthlyData[index]['month'] ?? '';
                            return Padding(
                              padding: const EdgeInsets.only(top: 8),
                              child: Text(
                                month,
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
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Артикул: ${widget.selectedSku}',
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  'Период: ${widget.monthlyData.first['month'] ?? ''} - ${widget.monthlyData.last['month'] ?? ''}',
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
