import 'dart:convert';
import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

class OzonApiClient {
  final Dio dio;
  final Function()? onUnauthorized;

  static String getDefaultBaseUrl() {
    if (kIsWeb) {
      // Автоматически берем IP сервера, с которого открыт сайт
      final host = Uri.base.host;
      if (host.isNotEmpty && host != 'localhost') {
        return 'http://$host:8082';
      }
    }
    return 'http://45.150.11.25:8082';
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
          if (onUnauthorized != null) {
            onUnauthorized!();
          }
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
    // Логируем для отладки в консоль браузера
    print('Sending keys to: ${dio.options.baseUrl}/auth/me/ozon-credentials');

    final resp = await dio.post(
      '/auth/me/ozon-credentials',
      data: {
        'ozon_client_id': clientId,
        'ozon_api_key': apiKey,
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

  Future<Map<String, dynamic>> getSyncStatus() async {
    final resp = await dio.get('/auth/me/sync-status');
    return _toJson(resp);
  }

  Map<String, dynamic> _toJson(Response resp) {
    if (resp.data is String) return json.decode(resp.data) as Map<String, dynamic>;
    return resp.data as Map<String, dynamic>;
  }
}
