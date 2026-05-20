import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import '../services/api.dart';

class ShipmentsScreen extends StatefulWidget {
  const ShipmentsScreen({Key? key}) : super(key: key);

  @override
  State<ShipmentsScreen> createState() => _ShipmentsScreenState();
}

class _ShipmentsScreenState extends State<ShipmentsScreen> {
  final TextEditingController _skuController = TextEditingController();
  final TextEditingController _startDateController = TextEditingController();
  final TextEditingController _endDateController = TextEditingController();
  late OzonApiClient _apiClient;
  List<dynamic> _shipments = [];
  int _currentPage = 0;
  int _totalItems = 0;
  int _limit = 50;
  bool _isLoading = false;

  @override
  void initState() {
    super.initState();
    _apiClient = OzonApiClient();
  }

  Future<void> _loadShipments() async {
    setState(() {
      _isLoading = true;
    });

    try {
      final result = await _apiClient.getShipments(
        skus: _skuController.text.isNotEmpty ? _skuController.text : null,
        since: _startDateController.text.isNotEmpty ? '${_startDateController.text}T00:00:00Z' : null,
        to: _endDateController.text.isNotEmpty ? '${_endDateController.text}T23:59:59Z' : null,
        limit: _limit,
        offset: _currentPage * _limit,
      );

      setState(() {
        _shipments = result['items'] ?? [];
        _totalItems = result['total'] ?? 0;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _isLoading = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Ошибка при загрузке данных: $e')),
      );
    }
  }

  Future<void> _selectDate(TextEditingController controller) async {
    final DateTime? picked = await showDatePicker(
      context: context,
      initialDate: DateTime.now(),
      firstDate: DateTime(2020),
      lastDate: DateTime(2101),
    );
    if (picked != null) {
      controller.text = picked.toString().split(' ')[0]; // yyyy-mm-dd
    }
  }

  @override
  Widget build(BuildContext context) {
    final authProvider = Provider.of<AuthProvider>(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Отгрузки'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
        foregroundColor: Theme.of(context).colorScheme.onSurface, // Исправлено: заменено onInversePrimary на onSurface
      ),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Card(
              elevation: 2,
              child: Padding(
                padding: const EdgeInsets.all(16.0),
                child: Column(
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: TextField(
                            controller: _skuController,
                            decoration: const InputDecoration(
                              labelText: 'Артикулы (через запятую)',
                              border: OutlineInputBorder(),
                              hintText: 'Например: 12345,67890',
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    Row(
                      children: [
                        Expanded(
                          child: TextField(
                            controller: _startDateController,
                            readOnly: true,
                            decoration: const InputDecoration(
                              labelText: 'Дата начала',
                              border: OutlineInputBorder(),
                              hintText: 'Выберите дату',
                            ),
                            onTap: () => _selectDate(_startDateController),
                          ),
                        ),
                        const SizedBox(width: 16),
                        Expanded(
                          child: TextField(
                            controller: _endDateController,
                            readOnly: true,
                            decoration: const InputDecoration(
                              labelText: 'Дата окончания',
                              border: OutlineInputBorder(),
                              hintText: 'Выберите дату',
                            ),
                            onTap: () => _selectDate(_endDateController),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    ElevatedButton(
                      onPressed: _isLoading ? null : _loadShipments,
                      child: _isLoading
                          ? const CircularProgressIndicator()
                          : const Text('Применить фильтры'),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            Expanded(
              child: _isLoading
                  ? const Center(child: CircularProgressIndicator())
                  : _shipments.isEmpty
                      ? const Center(child: Text('Нет данных об отгрузках'))
                      : Column(
                          children: [
                            Flexible(
                              child: SingleChildScrollView(
                                scrollDirection: Axis.horizontal,
                                child: DataTable(
                                  columnSpacing: 16,
                                  horizontalMargin: 16,
                                  columns: const [
                                    DataColumn(
                                      label: Text(
                                        'SKU',
                                        style: TextStyle(fontWeight: FontWeight.bold),
                                      ),
                                    ),
                                    DataColumn(
                                      label: Text(
                                        'Название',
                                        style: TextStyle(fontWeight: FontWeight.bold),
                                      ),
                                    ),
                                    DataColumn(
                                      label: Text(
                                        'Номер отправления',
                                        style: TextStyle(fontWeight: FontWeight.bold),
                                      ),
                                    ),
                                    DataColumn(
                                      label: Text(
                                        'Дата отгрузки',
                                        style: TextStyle(fontWeight: FontWeight.bold),
                                      ),
                                    ),
                                    DataColumn(
                                      label: Text(
                                        'Количество',
                                        style: TextStyle(fontWeight: FontWeight.bold),
                                      ),
                                    ),
                                    DataColumn(
                                      label: Text(
                                        'Статус',
                                        style: TextStyle(fontWeight: FontWeight.bold),
                                      ),
                                    ),
                                    DataColumn(
                                      label: Text(
                                        'Цена',
                                        style: TextStyle(fontWeight: FontWeight.bold),
                                      ),
                                    ),
                                    DataColumn(
                                      label: Text(
                                        'Выплата',
                                        style: TextStyle(fontWeight: FontWeight.bold),
                                      ),
                                    ),
                                    DataColumn(
                                      label: Text(
                                        'Комиссия',
                                        style: TextStyle(fontWeight: FontWeight.bold),
                                      ),
                                    ),
                                  ],
                                  rows: _shipments.map((shipment) {
                                    return DataRow(cells: [
                                      DataCell(Text(shipment['sku'].toString())),
                                      DataCell(Text(shipment['name'] ?? '')),
                                      DataCell(Text(shipment['posting_number'] ?? '')),
                                      DataCell(Text(
                                          shipment['shipment_date']?.toString() ?? '')),
                                      DataCell(Text(shipment['quantity'].toString())),
                                      DataCell(Text(shipment['status'] ?? '')),
                                      DataCell(Text(shipment['price'].toString())),
                                      DataCell(Text(shipment['payout'].toString())),
                                      DataCell(Text(shipment['commission'].toString())),
                                    ]);
                                  }).toList(),
                                ),
                              ),
                            ),
                            const SizedBox(height: 16),
                            Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Text(
                                  'Всего: $_totalItems | Страница: ${_currentPage + 1}',
                                ),
                                const Spacer(),
                                Row(
                                  children: [
                                    IconButton(
                                      icon: const Icon(Icons.arrow_back_ios),
                                      onPressed: _currentPage > 0
                                          ? () {
                                              setState(() {
                                                _currentPage--;
                                              });
                                              _loadShipments();
                                            }
                                          : null,
                                    ),
                                    IconButton(
                                      icon: const Icon(Icons.arrow_forward_ios),
                                      onPressed: (_currentPage + 1) * _limit < _totalItems
                                          ? () {
                                              setState(() {
                                                _currentPage++;
                                              });
                                              _loadShipments();
                                            }
                                          : null,
                                    ),
                                  ],
                                ),
                              ],
                            ),
                          ],
                        ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  void dispose() {
    _skuController.dispose();
    _startDateController.dispose();
    _endDateController.dispose();
    super.dispose();
  }
}