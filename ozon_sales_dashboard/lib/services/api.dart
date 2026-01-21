import 'dart:convert';
import 'package:dio/dio.dart';
import '../config/api_config.dart';

class OzonApiClient {
  final Dio dio;
  OzonApiClient({String? baseUrl})
    : dio = Dio(BaseOptions(
        baseUrl: baseUrl ?? ApiConfig.baseUrl,
        connectTimeout: const Duration(seconds: 30),
        receiveTimeout: const Duration(seconds: 30),
      ));

  Future<Map<String, dynamic>> getSalesRaw({
    required String since,
    required String to,
    String includeStatuses =
        'awaiting_assembly,awaiting_packaging,awaiting_deliver,delivering,delivered,canceled',
    String? status,
  }) async {
    final resp = await dio.get(
      '/analytics/sales_today_raw',
      queryParameters: {
        'since': since,
        'to': to,
        'include_statuses': includeStatuses,
        if (status != null) 'status': status,
      },
    );
    return _toJson(resp);
  }

  Future<Map<String, dynamic>> getSalesRange({
    required String since,
    required String to,
    String? status,
  }) async {
    final resp = await dio.get(
      '/analytics/sales_range',
      queryParameters: {
        'since': since,
        'to': to,
        if (status != null) 'status': status,
      },
    );
    return _toJson(resp);
  }

  Future<Map<String, dynamic>> getSalesBySkuMonthly({
    String? offerId,
    String? sku,
    int monthsBack = 12,
  }) async {
    final resp = await dio.get(
      '/analytics/sales_by_sku_monthly',
      queryParameters: {
        if (offerId != null) 'offer_id': offerId,
        if (sku != null) 'sku': sku,
        'months_back': monthsBack,
      },
    );
    return _toJson(resp);
  }

  Map<String, dynamic> _toJson(Response resp) {
    if (resp.data is String)
      return json.decode(resp.data as String) as Map<String, dynamic>;
    return resp.data as Map<String, dynamic>;
  }
}

