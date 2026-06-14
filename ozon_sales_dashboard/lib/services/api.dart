import 'dart:convert';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Централизованный HTTP-клиент для взаимодействия с OzonAPIHub.
/// Базируется на библиотеке Dio и реализует:
/// 1. Автоматическую подстановку JWT-токена в заголовки.
/// 2. Обработку ошибок авторизации (401).
/// 3. Определение базового URL в зависимости от платформы.
class OzonApiClient {
  final Dio dio;
  
  // Callback-функция, вызываемая при потере авторизации (истечении токена)
  final Function()? onUnauthorized;

  /// Статический метод для определения адреса сервера.
  /// В Flutter WebUri.base.host возвращает адрес, с которого загружен сайт.
  static String getDefaultBaseUrl() {
    if (kIsWeb) {
      final scheme = Uri.base.scheme.isNotEmpty ? Uri.base.scheme : 'http';
      final host = Uri.base.host.isNotEmpty ? Uri.base.host : 'localhost';
      return '$scheme://$host:8080';
    }
    // Для мобильных эмуляторов или десктоп-версий
    return 'http://localhost:8080';
  }

  OzonApiClient({String? baseUrl, this.onUnauthorized})
    : dio = Dio(BaseOptions(
        baseUrl: baseUrl ?? getDefaultBaseUrl(),
        connectTimeout: const Duration(seconds: 30),
        receiveTimeout: const Duration(seconds: 30),
      )) {
    
    // Инициализация интерцепторов (перехватчиков) для автоматизации рутины
    dio.interceptors.add(InterceptorsWrapper(
      // Перед каждым запросом добавляем заголовок Authorization
      onRequest: (options, handler) async {
        final prefs = await SharedPreferences.getInstance();
        final token = prefs.getString('jwt_token');
        
        if (token != null && token.isNotEmpty) {
          options.headers['Authorization'] = 'Bearer $token';
        }
        
        return handler.next(options);
      },
      // При получении ошибки от сервера
      onError: (DioException error, handler) async {
        // Если сервер ответил 401 (Unauthorized)
        if (error.response?.statusCode == 401) {
          final prefs = await SharedPreferences.getInstance();
          await prefs.remove('jwt_token'); // Удаляем невалидный токен
          
          if (onUnauthorized != null) {
            onUnauthorized!(); // Вызываем колбек для редиректа на Login
          }
        }
        
        return handler.next(error);
      },
    ));
  }

  // ===========================================================================
  // Методы API Аналитики
  // ===========================================================================

  /// Получает "сырые" данные о продажах. 
  /// Используется во вкладке "Отгрузки" для отображения текущих заказов (сборка, доставка).
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

  /// Получает агрегированные финансовые данные.
  /// Используется во вкладке "Финансы" для расчета прибыли по доставленным заказам.
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

  /// Получает исторические данные продаж товара для построения графиков.
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

  /// Проверка статуса синхронизации (завершена ли первичная загрузка истории).
  Future<Map<String, dynamic>> getSyncStatus() async {
    final resp = await dio.get('/auth/me/sync-status');
    return _toJson(resp);
  }

  /// Получение списка конкретных отправлений с пагинацией.
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

  /// Парсинг JSON-ответа. Поддерживает как Map, так и String (на случай сбоев контент-тайпа).
  Map<String, dynamic> _toJson(Response resp) {
    if (resp.data is String)
      return json.decode(resp.data as String) as Map<String, dynamic>;
    return resp.data as Map<String, dynamic>;
  }
}
