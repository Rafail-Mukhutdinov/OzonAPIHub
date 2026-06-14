import 'package:flutter/material.dart';
import 'package:flutter/gestures.dart';
import 'package:intl/intl.dart';
import 'mobile_stat_card.dart';

class MobileDashboardView extends StatefulWidget {
  final List<Map<String, dynamic>> items;
  final Map<String, dynamic>? totals;
  final Map<String, dynamic>? yesterdayTotals;
  final List<Map<String, dynamic>> weeklyStats;
  final bool isLoading;
  final String selectedPeriod;
  final DateTime activeDate;
  final Function(String) onPeriodChanged;
  final Function(DateTime) onDateChanged;

  const MobileDashboardView({
    super.key,
    required this.items,
    this.totals,
    this.yesterdayTotals,
    required this.weeklyStats,
    required this.isLoading,
    required this.selectedPeriod,
    required this.activeDate,
    required this.onPeriodChanged,
    required this.onDateChanged,
  });

  @override
  State<MobileDashboardView> createState() => _MobileDashboardViewState();
}

class _MobileDashboardViewState extends State<MobileDashboardView> {
  bool _isMoneyMode = true;

  String _calcChange(num current, num previous) {
    if (previous <= 0) return current > 0 ? "+100%" : "0%";
    final diff = ((current - previous) / previous) * 100;
    return "${diff >= 0 ? "+" : ""}${diff.toStringAsFixed(0)}%";
  }

  @override
  Widget build(BuildContext context) {
    final f = NumberFormat.decimalPattern('ru_RU');
    final dateStr = DateFormat("EEEE, d MMMM", "ru_RU").format(widget.activeDate);

    final revenueCurrent = widget.items.fold<num>(0, (sum, item) => sum + (item['amount_raw'] ?? 0));
    final itemsCurrent = widget.items.fold<num>(0, (sum, item) => sum + (item['quantity'] ?? 0));
    
    final revenuePrev = widget.yesterdayTotals?['total_amount_raw'] ?? 0;
    final itemsPrev = widget.yesterdayTotals?['total_items'] ?? 0;

    return ScrollConfiguration(
      // Включаем поддержку скроллинга мышкой для браузера
      behavior: ScrollConfiguration.of(context).copyWith(
        dragDevices: {
          PointerDeviceKind.touch,
          PointerDeviceKind.mouse,
          PointerDeviceKind.trackpad,
        },
      ),
      child: SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 1. ПЕРИОДЫ (ВВЕРХУ)
            Container(
              padding: const EdgeInsets.all(4),
              decoration: BoxDecoration(color: Colors.grey[200], borderRadius: BorderRadius.circular(12)),
              child: Row(
                children: [
                  _buildPeriodBtn('Сегодня', 'today'),
                  _buildPeriodBtn('Неделя', 'week'),
                  _buildPeriodBtn('Месяц', 'month'),
                ],
              ),
            ),
            const SizedBox(height: 20),

            // 2. ДАТЫ
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(widget.selectedPeriod == 'today' ? 'Выбранный день:' : 'Итоги периода:', 
                      style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                    Text(widget.selectedPeriod == 'today' ? dateStr : 'За ${widget.selectedPeriod == 'week' ? "7" : "30"} дней', 
                      style: TextStyle(color: Colors.grey[600], fontSize: 14)),
                  ],
                ),
                if (widget.selectedPeriod == 'today')
                  Row(
                    children: [
                      IconButton(icon: const Icon(Icons.chevron_left), onPressed: () => widget.onDateChanged(widget.activeDate.subtract(const Duration(days: 1)))),
                      IconButton(
                        icon: const Icon(Icons.chevron_right),
                        onPressed: widget.activeDate.day == DateTime.now().day && widget.activeDate.month == DateTime.now().month ? null : 
                          () => widget.onDateChanged(widget.activeDate.add(const Duration(days: 1))),
                      ),
                    ],
                  ),
              ],
            ),
            const SizedBox(height: 24),

            // 3. ПОКАЗАТЕЛИ
            const Text('ПОКАЗАТЕЛИ', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11, letterSpacing: 0.8, color: Colors.grey)),
            const SizedBox(height: 12),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                MobileStatCard(title: 'Выручка', value: '${f.format(revenueCurrent)} ₽', change: _calcChange(revenueCurrent, revenuePrev), isPositive: revenueCurrent >= revenuePrev, icon: Icons.paid),
                MobileStatCard(title: 'Продано', value: '${f.format(itemsCurrent)} шт', change: _calcChange(itemsCurrent, itemsPrev), isPositive: itemsCurrent >= itemsPrev, icon: Icons.shopping_bag),
              ],
            ),

            const SizedBox(height: 32),

            // 4. ГРАФИК
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('ДИНАМИКА', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11, letterSpacing: 0.8, color: Colors.grey)),
                Container(
                  decoration: BoxDecoration(color: Colors.grey[200], borderRadius: BorderRadius.circular(8)),
                  child: Row(children: [
                    _buildMetricBtn('₽', true),
                    _buildMetricBtn('шт', false),
                  ]),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 8),
              width: double.infinity,
              decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16), boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.02), blurRadius: 10)]),
              child: _buildChart(f),
            ),

            const SizedBox(height: 32),

            // 5. ТОВАРЫ
            const Text('ПОПУЛЯРНЫЕ ТОВАРЫ', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11, letterSpacing: 0.8, color: Colors.grey)),
            const SizedBox(height: 12),
            if (widget.isLoading) const Center(child: Padding(padding: EdgeInsets.all(40), child: CircularProgressIndicator()))
            else if (widget.items.isEmpty) const Center(child: Padding(padding: EdgeInsets.all(40), child: Text('Нет данных')))
            else
              ListView.builder(
                shrinkWrap: true, physics: const NeverScrollableScrollPhysics(),
                itemCount: widget.items.length,
                itemBuilder: (context, index) {
                  final item = widget.items[index];
                  return Container(
                    margin: const EdgeInsets.only(bottom: 12), padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12), boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.01), blurRadius: 5)]),
                    child: Row(children: [
                        Container(width: 44, height: 44, decoration: BoxDecoration(color: const Color(0xFFF8F9FA), borderRadius: BorderRadius.circular(8)), child: const Icon(Icons.inventory_2_outlined, color: Colors.blueGrey, size: 20)),
                        const SizedBox(width: 12),
                        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text(item['name'] ?? 'Товар', maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13, height: 1.2)),
                            const SizedBox(height: 4),
                            Text('${item['quantity'] ?? 0} шт  /  ${f.format(item['amount_raw'] ?? 0)} ₽', style: TextStyle(color: Colors.blueGrey.shade400, fontSize: 11)),
                          ])),
                      ]),
                  );
                },
              ),
              const SizedBox(height: 100),
          ],
        ),
      ),
    );
  }

  Widget _buildPeriodBtn(String label, String code) {
    final active = widget.selectedPeriod == code;
    return Expanded(
      child: GestureDetector(
        onTap: () => widget.onPeriodChanged(code),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 8),
          decoration: BoxDecoration(color: active ? Colors.white : Colors.transparent, borderRadius: BorderRadius.circular(10), boxShadow: active ? [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 4)] : null),
          child: Text(label, textAlign: TextAlign.center, style: TextStyle(fontSize: 13, fontWeight: active ? FontWeight.bold : FontWeight.normal, color: active ? Colors.black : Colors.grey[600])),
        ),
      ),
    );
  }

  Widget _buildMetricBtn(String label, bool isMoney) {
    final active = _isMoneyMode == isMoney;
    return GestureDetector(
      onTap: () => setState(() => _isMoneyMode = isMoney),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        decoration: BoxDecoration(color: active ? Colors.white : Colors.transparent, borderRadius: BorderRadius.circular(8), boxShadow: active ? [BoxShadow(color: Colors.black.withOpacity(0.1), blurRadius: 4)] : null),
        child: Text(label, style: TextStyle(fontSize: 12, fontWeight: active ? FontWeight.bold : FontWeight.normal, color: active ? Colors.black : Colors.grey)),
      ),
    );
  }

  Widget _buildChart(NumberFormat f) {
    final bool isMonth = widget.selectedPeriod == 'month';
    // Отрезаем последние 7 дней, если не выбран месяц
    final stats = isMonth ? widget.weeklyStats : widget.weeklyStats.skip(widget.weeklyStats.length > 7 ? widget.weeklyStats.length - 7 : 0).toList();
    
    if (stats.isEmpty) return const SizedBox(height: 120, child: Center(child: Text('Нет данных')));

    final values = stats.map((s) => (_isMoneyMode ? s['revenue'] : s['items']) as num).toList();
    final maxVal = values.isNotEmpty ? values.reduce((a, b) => a > b ? a : b) : 0;
    final activeDateStr = DateFormat('yyyy-MM-dd').format(widget.activeDate);

    final chartContent = Column(
      children: [
        Row(
          mainAxisAlignment: isMonth ? MainAxisAlignment.start : MainAxisAlignment.spaceEvenly,
          mainAxisSize: MainAxisSize.min, // Важно для корректного скролла
          crossAxisAlignment: CrossAxisAlignment.end,
          children: stats.map((s) {
            final val = (_isMoneyMode ? s['revenue'] : s['items']) as num;
            final double h = maxVal > 0 ? (val / maxVal * 120).toDouble().clamp(5.0, 120.0) : 5.0;
            final bool isActive = s['date'] == activeDateStr;
            final bool isMax = (val == maxVal && maxVal > 0);

            return Tooltip(
              message: "${s['date']}\n${_isMoneyMode ? f.format(val) + ' ₽' : '$val шт'}",
              triggerMode: TooltipTriggerMode.tap,
              child: Container(
                width: isMonth ? 16 : 36, // Немного увеличим для месяца
                height: h,
                margin: const EdgeInsets.symmetric(horizontal: 4),
                decoration: BoxDecoration(
                  color: isActive ? const Color(0xFF4CAF50) : (isMax ? Colors.red : const Color(0xFF90CAF9)),
                  border: (isActive && isMax) ? Border.all(color: Colors.red, width: 2) : null,
                  borderRadius: BorderRadius.circular(4),
                ),
              ),
            );
          }).toList(),
        ),
        const SizedBox(height: 12),
        Row(
          mainAxisAlignment: isMonth ? MainAxisAlignment.start : MainAxisAlignment.spaceEvenly,
          mainAxisSize: MainAxisSize.min,
          children: stats.map((s) {
            final date = DateTime.parse(s['date']);
            String label = isMonth ? date.day.toString() : "${['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][date.weekday-1]}\n${date.day}";
            return SizedBox(
              width: isMonth ? 24 : 44, // Должно совпадать с шириной бара + маржинами
              child: Center(child: Text(label, textAlign: TextAlign.center, style: const TextStyle(fontSize: 8, color: Colors.grey, height: 1.2))),
            );
          }).toList(),
        )
      ],
    );

    if (isMonth) {
      return SingleChildScrollView(
        scrollDirection: Axis.horizontal, 
        reverse: true, 
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8.0),
          child: chartContent,
        )
      );
    }
    return chartContent;
  }
}
