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
  }) async {
    final resp = await dio.get(
      '/analytics/sales_today_raw',
      queryParameters: {
        'since': since,
        'to': to,
        'include_statuses': includeStatuses,
      },
    );
    return _toJson(resp);
  }

  Future<Map<String, dynamic>> getSalesRange({
    required String since,
    required String to,
  }) async {
    final resp = await dio.get(
      '/analytics/sales_range',
      queryParameters: {'since': since, 'to': to},
    );
    return _toJson(resp);
  }

  Map<String, dynamic> _toJson(Response resp) {
    if (resp.data is String)
      return json.decode(resp.data as String) as Map<String, dynamic>;
    return resp.data as Map<String, dynamic>;
  }
}
