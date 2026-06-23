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
  final String weekMode;
  final String monthMode;
  final DateTimeRange? customRange;
  final DateTime activeDate;
  final DateTime? drillDownDate;
  final Function(String) onPeriodChanged;
  final Function(String, String) onSettingsChanged;
  final Function(DateTimeRange) onCustomRangeSelected;
  final Function(DateTime) onDateChanged;
  final Function(DateTime) onDrillDown;
  final VoidCallback onResetDrillDown;

  const MobileDashboardView({
    super.key,
    required this.items,
    this.totals,
    this.yesterdayTotals,
    required this.weeklyStats,
    required this.isLoading,
    required this.selectedPeriod,
    required this.weekMode,
    required this.monthMode,
    this.customRange,
    required this.activeDate,
    this.drillDownDate,
    required this.onPeriodChanged,
    required this.onSettingsChanged,
    required this.onCustomRangeSelected,
    required this.onDateChanged,
    required this.onDrillDown,
    required this.onResetDrillDown,
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
    
    final displayDate = widget.drillDownDate ?? widget.activeDate;
    final dateStr = DateFormat("EEEE, d MMMM", "ru_RU").format(displayDate);

    // --- РАСЧЕТ ДИАПАЗОНА ДАТ ДЛЯ ЗАГОЛОВКА ---
    DateTime rangeStart;
    if (widget.drillDownDate != null) {
      rangeStart = displayDate;
    } else if (widget.selectedPeriod == 'custom' && widget.customRange != null) {
      rangeStart = widget.customRange!.start;
    } else if (widget.selectedPeriod == 'today') {
      rangeStart = displayDate;
    } else if (widget.selectedPeriod == 'week') {
      if (widget.weekMode == 'calendar') {
        rangeStart = widget.activeDate.subtract(Duration(days: widget.activeDate.weekday - 1));
      } else {
        rangeStart = widget.activeDate.subtract(const Duration(days: 6));
      }
    } else {
      if (widget.monthMode == 'calendar') {
        rangeStart = DateTime(widget.activeDate.year, widget.activeDate.month, 1);
      } else {
        rangeStart = widget.activeDate.subtract(const Duration(days: 29));
      }
    }

    final String displayRangeText = widget.selectedPeriod == 'today' || widget.drillDownDate != null
        ? dateStr
        : (widget.selectedPeriod == 'custom' && widget.customRange != null)
          ? "${DateFormat("d MMMM", "ru_RU").format(widget.customRange!.start)} — ${DateFormat("d MMMM", "ru_RU").format(widget.customRange!.end)}"
          : "${DateFormat("d MMMM", "ru_RU").format(rangeStart)} — ${DateFormat("d MMMM", "ru_RU").format(widget.activeDate)}";

    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final isAtMaxDate = !widget.activeDate.isBefore(today);

    // --- РАСЧЕТ ТЕКУЩИХ ПОКАЗАТЕЛЕЙ ---
    final revenueCurr = widget.items.fold<num>(0, (sum, item) => sum + (item['amount_raw'] ?? 0));
    final itemsCurr = widget.items.fold<num>(0, (sum, item) => sum + (item['quantity'] ?? 0));
    final avgPriceCurr = itemsCurr > 0 ? revenueCurr / itemsCurr : 0;

    // --- РАСЧЕТ ПРЕДЫДУЩИХ ПОКАЗАТЕЛЕЙ ---
    final revenuePrev = widget.yesterdayTotals?['total_amount_raw'] ?? 0;
    final itemsPrev = widget.yesterdayTotals?['total_items'] ?? 0;
    final avgPricePrev = itemsPrev > 0 ? revenuePrev / itemsPrev : 0;

    return ScrollConfiguration(
      behavior: ScrollConfiguration.of(context).copyWith(
        dragDevices: {PointerDeviceKind.touch, PointerDeviceKind.mouse, PointerDeviceKind.trackpad},
      ),
      child: SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 1. ПЕРИОДЫ
            Row(
              children: [
                Expanded(
                  child: Container(
                    padding: const EdgeInsets.all(4),
                    decoration: BoxDecoration(
                      color: const Color(0xFFE9ECEF),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Row(
                      children: [
                        _buildPeriodBtn('Сегодня', 'today'),
                        _buildPeriodBtn('Неделя', 'week'),
                        _buildPeriodBtn('Месяц', 'month'),
                      ],
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton(
                  onPressed: _selectCustomRange,
                  icon: Icon(Icons.calendar_month_outlined, color: widget.selectedPeriod == 'custom' ? Theme.of(context).primaryColor : const Color(0xFF6C757D)),
                  style: IconButton.styleFrom(
                    backgroundColor: const Color(0xFFE9ECEF),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton(
                  onPressed: _showSettingsSheet,
                  icon: const Icon(Icons.tune, color: Color(0xFF6C757D)),
                  style: IconButton.styleFrom(
                    backgroundColor: const Color(0xFFE9ECEF),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 20),

            // 2. ДАТЫ
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      widget.drillDownDate != null 
                        ? 'Детали за день:' 
                        : (widget.selectedPeriod == 'today' ? 'Выбранный день:' : 'Итоги периода:'), 
                      style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 17, color: Color(0xFF1A1C1E)),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      displayRangeText, 
                      style: TextStyle(
                        color: widget.drillDownDate != null ? Theme.of(context).primaryColor : Colors.grey[600], 
                        fontSize: 13,
                        fontWeight: widget.drillDownDate != null ? FontWeight.bold : FontWeight.normal,
                      ),
                    ),
                  ],
                ),
                if (widget.drillDownDate != null)
                  TextButton.icon(
                    onPressed: widget.onResetDrillDown, 
                    icon: const Icon(Icons.close, size: 18, color: Colors.redAccent), 
                    label: const Text('Сброс', style: TextStyle(fontSize: 13, color: Colors.redAccent, fontWeight: FontWeight.bold))
                  )
                else
                  Row(
                    children: [
                      IconButton(
                        icon: const Icon(Icons.chevron_left), 
                        onPressed: () => widget.onDateChanged(widget.activeDate.subtract(const Duration(days: 1)))
                      ),
                      IconButton(
                        icon: const Icon(Icons.chevron_right), 
                        onPressed: isAtMaxDate ? null : () => widget.onDateChanged(widget.activeDate.add(const Duration(days: 1)))
                      ),
                    ],
                  ),
              ],
            ),
            const SizedBox(height: 24),

            // 3. ПОКАЗАТЕЛИ (ТРИ В ОДНОМ РЯДУ)
            const Text('ПОКАЗАТЕЛИ', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 11, letterSpacing: 0.8, color: Colors.grey)),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(child: MobileStatCard(title: 'Выручка', value: '${f.format(revenueCurr)} ₽', change: _calcChange(revenueCurr, revenuePrev), isPositive: revenueCurr >= revenuePrev, icon: Icons.paid)),
                const SizedBox(width: 8),
                Expanded(child: MobileStatCard(title: 'Продано', value: '${f.format(itemsCurr)} шт', change: _calcChange(itemsCurr, itemsPrev), isPositive: itemsCurr >= itemsPrev, icon: Icons.shopping_bag)),
                const SizedBox(width: 8),
                Expanded(child: MobileStatCard(title: 'Ср. цена', value: '${f.format(avgPriceCurr.toInt())} ₽', change: _calcChange(avgPriceCurr, avgPricePrev), isPositive: avgPriceCurr >= avgPricePrev, icon: Icons.analytics)),
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
                  final qty = item['quantity'] ?? 0;
                  final total = item['amount_raw'] ?? 0;
                  final avgItemPrice = qty > 0 ? total / qty : 0; // СРЕДНЯЯ ЦЕНА ТОВАРА
                  final imageUrl = item['image_url'];

                  return Container(
                    margin: const EdgeInsets.only(bottom: 12), padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12), boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.01), blurRadius: 5)]),
                    child: Row(children: [
                        Container(
                          width: 44, height: 44, 
                          decoration: BoxDecoration(color: const Color(0xFFF8F9FA), borderRadius: BorderRadius.circular(8)), 
                          clipBehavior: Clip.antiAlias,
                          child: imageUrl != null && imageUrl.isNotEmpty
                            ? Image.network(
                                imageUrl,
                                fit: BoxFit.cover,
                                errorBuilder: (context, error, stackTrace) => const Icon(Icons.inventory_2_outlined, color: Colors.blueGrey, size: 20),
                              )
                            : const Icon(Icons.inventory_2_outlined, color: Colors.blueGrey, size: 20),
                        ),
                        const SizedBox(width: 12),
                        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text(item['name'] ?? 'Товар', maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13, height: 1.2)),
                            const SizedBox(height: 4),
                            // Добавили среднюю цену в строку инфо
                            Text('$qty шт × ${f.format(avgItemPrice.toInt())} ₽  =  ${f.format(total)} ₽', style: TextStyle(color: Colors.blueGrey.shade400, fontSize: 11)),
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
          padding: const EdgeInsets.symmetric(vertical: 10),
          decoration: BoxDecoration(
            color: active ? Colors.white : Colors.transparent,
            borderRadius: BorderRadius.circular(10),
            boxShadow: active 
              ? [BoxShadow(color: Colors.black.withOpacity(0.08), blurRadius: 8, offset: const Offset(0, 2))] 
              : null,
          ),
          child: Text(
            label, 
            textAlign: TextAlign.center, 
            style: TextStyle(
              fontSize: 12, 
              fontWeight: active ? FontWeight.bold : FontWeight.w500, 
              color: active ? Theme.of(context).primaryColor : const Color(0xFF6C757D),
            ),
          ),
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

  void _showSettingsSheet() {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (context) => Container(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Настройка периодов', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
            const SizedBox(height: 24),
            const Text('РЕЖИМ "НЕДЕЛЯ"', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Colors.grey)),
            ListTile(
              title: const Text('С понедельника'),
              leading: Radio<String>(value: 'calendar', groupValue: widget.weekMode, onChanged: (v) { widget.onSettingsChanged(v!, widget.monthMode); Navigator.pop(context); }),
            ),
            ListTile(
              title: const Text('Последние 7 дней'),
              leading: Radio<String>(value: 'rolling', groupValue: widget.weekMode, onChanged: (v) { widget.onSettingsChanged(v!, widget.monthMode); Navigator.pop(context); }),
            ),
            const Divider(),
            const Text('РЕЖИМ "МЕСЯЦ"', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Colors.grey)),
            ListTile(
              title: const Text('С 1-го числа месяца'),
              leading: Radio<String>(value: 'calendar', groupValue: widget.monthMode, onChanged: (v) { widget.onSettingsChanged(widget.weekMode, v!); Navigator.pop(context); }),
            ),
            ListTile(
              title: const Text('Последние 30 дней'),
              leading: Radio<String>(value: 'rolling', groupValue: widget.monthMode, onChanged: (v) { widget.onSettingsChanged(widget.weekMode, v!); Navigator.pop(context); }),
            ),
            const SizedBox(height: 16),
          ],
        ),
      ),
    );
  }

  Future<void> _selectCustomRange() async {
    final DateTimeRange? picked = await showDateRangePicker(
      context: context,
      firstDate: DateTime(2023),
      lastDate: DateTime.now(),
      initialDateRange: widget.customRange,
      locale: const Locale('ru', 'RU'),
      builder: (context, child) {
        return Theme(
          data: Theme.of(context).copyWith(
            colorScheme: ColorScheme.light(
              primary: Theme.of(context).primaryColor,
              onPrimary: Colors.white,
              onSurface: Colors.black,
            ),
          ),
          child: child!,
        );
      },
    );

    if (picked != null) {
      widget.onCustomRangeSelected(picked);
    }
  }

  Widget _buildChart(NumberFormat f) {
    final stats = widget.weeklyStats;
    final bool isLongPeriod = stats.length > 10;
    
    if (stats.isEmpty) return const SizedBox(height: 120, child: Center(child: Text('Нет данных')));

    final values = stats.map((s) => (_isMoneyMode ? s['revenue'] : s['items']) as num).toList();
    final maxVal = values.isNotEmpty ? values.reduce((a, b) => a > b ? a : b) : 0;
    
    // ОПРЕДЕЛЯЕМ "СЕГОДНЯ" ПО МОСКВЕ (UTC+3)
    final nowMoscow = DateTime.now().toUtc().add(const Duration(hours: 3));
    final todayStr = DateFormat('yyyy-MM-dd').format(nowMoscow);
    
    final activeDateStr = DateFormat('yyyy-MM-dd').format(widget.drillDownDate ?? widget.activeDate);

    final chartContent = Column(
      children: [
        Row(
          mainAxisAlignment: isLongPeriod ? MainAxisAlignment.start : MainAxisAlignment.spaceEvenly,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: stats.map((s) {
            final val = (_isMoneyMode ? s['revenue'] : s['items']) as num;
            final double h = maxVal > 0 ? (val / maxVal * 120).toDouble().clamp(5.0, 120.0) : 5.0;
            
            final sDate = DateTime.parse(s['date']);
            final sDateStr = DateFormat('yyyy-MM-dd').format(sDate);

            final bool isActive = sDateStr == activeDateStr;
            final bool isToday = sDateStr == todayStr;
            final bool isMax = (val == maxVal && maxVal > 0);
            final bool isWeekend = sDate.weekday == DateTime.saturday || sDate.weekday == DateTime.sunday;

            // ЛОГИКА ЦВЕТОВ:
            Color barColor = const Color(0xFF90CAF9); 
            if (isMax) {
              barColor = Colors.red; 
            } else if (isToday) {
              barColor = const Color(0xFF4CAF50); 
            }

            BoxBorder? border;
            if (isActive || (isToday && isMax)) {
              border = Border.all(color: const Color(0xFF4CAF50), width: 2.5);
            }

            return Tooltip(
              message: "${DateFormat("d MMMM", "ru_RU").format(sDate)}\n${_isMoneyMode ? f.format(val) + ' ₽' : '$val шт'}",
              triggerMode: TooltipTriggerMode.tap,
              child: Container(
                decoration: const BoxDecoration(
                  color: Colors.transparent, // Убрали подсветку фона за столбиком
                ),
                child: Material(
                  color: Colors.transparent,
                  child: InkWell(
                    onTap: () => widget.onDrillDown(sDate),
                    borderRadius: BorderRadius.circular(4),
                    splashColor: Colors.transparent,
                    highlightColor: Colors.transparent,
                    child: Container(
                      width: isLongPeriod ? 26 : 44,
                      height: 130, 
                      alignment: Alignment.bottomCenter,
                      padding: const EdgeInsets.only(bottom: 2),
                      child: Container(
                        width: isLongPeriod ? 18 : 36,
                        height: h,
                        decoration: BoxDecoration(
                          color: barColor,
                          border: border,
                          borderRadius: BorderRadius.circular(4),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            );
          }).toList(),
        ),
        const SizedBox(height: 12),
        Row(
          mainAxisAlignment: isLongPeriod ? MainAxisAlignment.start : MainAxisAlignment.spaceEvenly,
          children: stats.map((s) {
            final date = DateTime.parse(s['date']);
            final bool isWeekend = date.weekday == DateTime.saturday || date.weekday == DateTime.sunday;
            String label = isLongPeriod ? date.day.toString() : "${['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][date.weekday-1]}\n${date.day}";
            return Container(
              width: isLongPeriod ? 26 : 44,
              padding: const EdgeInsets.symmetric(vertical: 4),
              decoration: BoxDecoration(
                // Оставили подсветку только для блока дат
                color: isWeekend ? Colors.blue.withOpacity(0.1) : Colors.transparent,
                borderRadius: BorderRadius.circular(6),
              ),
              child: Center(
                child: Text(
                  label, 
                  textAlign: TextAlign.center, 
                  style: TextStyle(
                    fontSize: isLongPeriod ? 9 : 8, 
                    color: isWeekend ? Colors.blue[700] : Colors.grey,
                    fontWeight: isWeekend ? FontWeight.bold : FontWeight.normal,
                    height: 1.2
                  )
                )
              ),
            );
          }).toList(),
        )
      ],
    );

    if (isLongPeriod) {
      return SingleChildScrollView(scrollDirection: Axis.horizontal, reverse: true, child: chartContent);
    }
    return chartContent;
  }
}
