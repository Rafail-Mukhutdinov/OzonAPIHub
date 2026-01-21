import 'dart:convert';
import 'package:dio/dio.dart';

class OzonApiClient {
  final Dio dio;
  OzonApiClient({String baseUrl = 'http://127.0.0.1:8080'})
    : dio = Dio(BaseOptions(baseUrl: baseUrl));

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
    String? since,
    String? to,
    int monthsBack = 12,
  }) async {
    final resp = await dio.get(
      '/analytics/sales_by_sku_monthly',
      queryParameters: {
        if (offerId != null) 'offer_id': offerId,
        if (sku != null) 'sku': sku,
        if (since != null) 'since': since,
        if (to != null) 'to': to,
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

