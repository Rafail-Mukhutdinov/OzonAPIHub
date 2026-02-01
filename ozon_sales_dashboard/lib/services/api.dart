import 'dart:convert';
import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

class OzonApiClient {
  final Dio dio;
  final Function()? onUnauthorized;

  /// Умный выбор адреса в зависимости от платформы
  static String getDefaultBaseUrl() {
    // На Android эмуляторе нужен спец. адрес, который маппится на хост-машину
    if (!kIsWeb && Platform.isAndroid) {
      return 'http://10.0.2.2:8080';
    }
    // На Web всегда используем localhost вместо 127.0.0.1 для лучшей совместимости с браузерами
    if (kIsWeb) {
      return 'http://localhost:8080';
    }
    // Desktop и iOS -> localhost
    return 'http://localhost:8080';
  }

  /// Создает клиент с автоматическим выбором URL или явно переданным
  OzonApiClient({String? baseUrl, this.onUnauthorized})
    : dio = Dio(BaseOptions(
        baseUrl: baseUrl ?? getDefaultBaseUrl(),
        connectTimeout: const Duration(seconds: 30),
        receiveTimeout: const Duration(seconds: 30),
      )) {
    // Добавляем interceptor для автоматического добавления токена
    dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) async {
        // Получаем токен из SharedPreferences
        final prefs = await SharedPreferences.getInstance();
        final token = prefs.getString('jwt_token');
        
        if (token != null && token.isNotEmpty) {
          options.headers['Authorization'] = 'Bearer $token';
        }
        
        return handler.next(options);
      },
      onError: (DioException error, handler) async {
        // Если получили 401 - пользователь не авторизован
        if (error.response?.statusCode == 401) {
          // Удаляем невалидный токен
          final prefs = await SharedPreferences.getInstance();
          await prefs.remove('jwt_token');
          
          // Вызываем callback для перенаправления на экран входа
          if (onUnauthorized != null) {
            onUnauthorized!();
          }
        }
        
        return handler.next(error);
      },
    ));
  }

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

  /// Получить статус синхронизации данных
  /// Используется для отслеживания полной загрузки (backfill)
  /// Периодические обновления по таймеру НЕ меняют этот статус
  Future<Map<String, dynamic>> getSyncStatus() async {
    final resp = await dio.get('/auth/me/sync-status');
    return _toJson(resp);
  }

  Map<String, dynamic> _toJson(Response resp) {
    if (resp.data is String)
      return json.decode(resp.data as String) as Map<String, dynamic>;
    return resp.data as Map<String, dynamic>;
  }
}