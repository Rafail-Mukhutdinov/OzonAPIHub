import 'dart:convert';
import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

class OzonApiClient {
  final Dio dio;

  /// Умный выбор адреса в зависимости от платформы
  static String get _defaultBaseUrl {
    // На Android эмуляторе нужен спец. адрес, который маппится на хост-машину
    if (!kIsWeb && Platform.isAndroid) {
      return 'http://10.0.2.2:8080';
    }
    // Везде else: Web, iOS, Desktop -> localhost
    return 'http://127.0.0.1:8080';
  }

  /// Создает клиент с автоматическим выбором URL или явно переданным
  OzonApiClient({String? baseUrl})
    : dio = Dio(BaseOptions(
        baseUrl: baseUrl ?? _defaultBaseUrl,
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

