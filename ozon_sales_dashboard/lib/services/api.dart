import 'dart:convert';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

class OzonApiClient {
  final Dio dio;
  final Function()? onUnauthorized;

  static String getDefaultBaseUrl() {
    const String envUrl = String.fromEnvironment('API_BASE_URL');
    if (envUrl.isNotEmpty) {
      return envUrl;
    }

    if (kIsWeb) {
      final host = Uri.base.host;
      if (host == 'localhost' || host == '127.0.0.1') {
        return 'http://localhost:8083';
      }
      if (host.isNotEmpty) {
        // Явно добавляем порт 8083, игнорируя порт из Uri.base
        return 'http://$host:8083';
      }
    }
    // Для мобильных приложений (Android/iOS)
    // ВАЖНО: Используйте --dart-define=BASE_URL=ваша_ссылка при сборке.
    // Если переменная не задана, используем значение по умолчанию.
    return const String.fromEnvironment('BASE_URL', defaultValue: 'http://45.150.11.25:8083');
  }

  OzonApiClient({String? baseUrl, this.onUnauthorized})
    : dio = Dio(BaseOptions(
        baseUrl: baseUrl ?? getDefaultBaseUrl(),
        connectTimeout: const Duration(seconds: 30),
        receiveTimeout: const Duration(seconds: 30),
      )) {
    
    dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) async {
        final prefs = await SharedPreferences.getInstance();
        final token = prefs.getString('jwt_token');
        if (token != null && token.isNotEmpty) {
          options.headers['Authorization'] = 'Bearer $token';
        }
        return handler.next(options);
      },
      onError: (DioException error, handler) async {
        if (error.response?.statusCode == 401) {
          final prefs = await SharedPreferences.getInstance();
          await prefs.remove('jwt_token');
          if (onUnauthorized != null) onUnauthorized!();
        }
        return handler.next(error);
      },
    ));
  }

  Future<Map<String, dynamic>> addOzonCredential({
    required String clientId,
    required String apiKey,
    String marketplace = 'ozon',
    String name = 'Основной магазин',
  }) async {
    final resp = await dio.post(
      '/auth/me/ozon-credentials',
      data: {
        'client_id': clientId,
        'api_key': apiKey,
        'marketplace': marketplace,
        'name': name,
      },
    );
    return _toJson(resp);
  }

  Future<Map<String, dynamic>> getSalesRaw({
    required String since,
    required String to,
    String includeStatuses = 'awaiting_assembly,awaiting_packaging,awaiting_deliver,delivering,delivered,canceled',
    String? status,
  }) async {
    final resp = await dio.get('/analytics/sales_today_raw', queryParameters: {
      'since': since,
      'to': to,
      'include_statuses': includeStatuses,
      if (status != null) 'status': status,
    });
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
    String mode = 'delivered',
  }) async {
    final resp = await dio.get(
      '/analytics/sales_by_sku_monthly',
      queryParameters: {
        if (offerId != null) 'offer_id': offerId,
        if (sku != null) 'sku': sku,
        'months_back': monthsBack,
        'mode': mode,
      },
    );
    return _toJson(resp);
  }

  Future<Map<String, dynamic>> getSyncStatus() async {
    final resp = await dio.get('/auth/me/sync-status');
    return _toJson(resp);
  }

  Future<Map<String, dynamic>> getProfile() async {
    final resp = await dio.get('/auth/me');
    return _toJson(resp);
  }

  Future<Map<String, dynamic>> getShipments({
    String? skus,
    String? since,
    String? to,
    int limit = 50,
    int offset = 0,
  }) async {
    final resp = await dio.get(
      '/analytics/shipments',
      queryParameters: {
        if (skus != null) 'skus': skus,
        if (since != null) 'since': since,
        if (to != null) 'to': to,
        'limit': limit,
        'offset': offset,
      },
    );
    return _toJson(resp);
  }

  Future<Map<String, dynamic>> getExpensesSummary({
    required String since,
    required String to,
  }) async {
    final resp = await dio.get(
      '/analytics/expenses_summary',
      queryParameters: {
        'since': since,
        'to': to,
      },
    );
    return _toJson(resp);
  }

  Future<Map<String, dynamic>> triggerManualSync() async {
    final resp = await dio.post('/sync/manual');
    return _toJson(resp);
  }

  Map<String, dynamic> _toJson(Response resp) {
    if (resp.data is String) return json.decode(resp.data) as Map<String, dynamic>;
    return resp.data as Map<String, dynamic>;
  }
}
