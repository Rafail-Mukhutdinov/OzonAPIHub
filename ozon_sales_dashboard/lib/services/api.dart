import 'dart:convert';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../providers/auth_provider.dart'; // Добавляем импорт
import 'package:flutter/material.dart';

// Глобальный ключ для показа SnackBar из любой части приложения (включая API клиент)
final GlobalKey<ScaffoldMessengerState> rootScaffoldMessengerKey = GlobalKey<ScaffoldMessengerState>();

/// Клиент для взаимодействия с API OzonHub.
/// Обрабатывает авторизацию, ошибки и основные запросы к бэкенду.
class OzonApiClient {
  final Dio dio; // Клиент для HTTP-запросов
  final AuthProvider? authProvider; // Провайдер авторизации для обработки истечения сессии
  final _secureStorage = const FlutterSecureStorage(); // Защищенное хранилище для токенов

  /// Определяет базовый URL API в зависимости от окружения и платформы.
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
      
      // Единый вход через Nginx: относительный путь того же домена.
      // Браузер обращается к seller.home-me.online/api/... — тот же origin,
      // поэтому нет ни CORS, ни зависимости от внешнего прокси api-ozon
      // (который может отдавать 502, когда недоступен снаружи).
      if (host == 'seller.home-me.online') {
        return '/api';
      }

      if (host.isNotEmpty) {
        // Резерв для локального IP (192.168.1.105)
        return 'http://$host:8083';
      }
    }
    // Для мобильных приложений (Android/iOS)
    // ВАЖНО: Используйте --dart-define=BASE_URL=ваша_ссылка при сборке.
    // Если переменная не задана, используем значение по умолчанию.
    return const String.fromEnvironment('BASE_URL', defaultValue: 'https://api-ozon.home-me.online');
  }

  OzonApiClient({String? baseUrl, this.authProvider})
    : dio = Dio(BaseOptions(
        baseUrl: baseUrl ?? getDefaultBaseUrl(),
        connectTimeout: const Duration(seconds: 30),
        receiveTimeout: const Duration(seconds: 30),
      )) {
    
    // Добавление интерцепторов для авторизации и обработки ошибок
    dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) async {
        String? token;
        try {
          if (kIsWeb) {
            final prefs = await SharedPreferences.getInstance();
            token = prefs.getString('jwt_token');
          } else {
            token = await _secureStorage.read(key: 'jwt_token');
          }
          
          if (token != null && token.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $token';
          }
        } catch (_) {}
        return handler.next(options);
      },
      onError: (DioException error, handler) async {
        if (error.response?.statusCode == 401) {
          // Если получили 401 (Unauthorized), сообщаем об этом провайдеру (разлогинивание)
          if (authProvider != null) {
            authProvider!.handleSessionExpired();
          }
        } else if (error.response?.statusCode == 403) {
          // Если получили 403 (Нет прав), НЕ разлогиниваем, а просто уведомляем.
          rootScaffoldMessengerKey.currentState?.showSnackBar(
            const SnackBar(
              content: Text('У вас нет прав для выполнения этого действия'),
              backgroundColor: Color(0xFFE67E22), // Оранжевый (предупреждение)
              behavior: SnackBarBehavior.floating,
            ),
          );
        }
        return handler.next(error);
      },
    ));
  }

  /// Добавление новых учетных данных Ozon (API Key и Client ID).
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

  /// Получение сырых данных о продажах за период.
  Future<Map<String, dynamic>> getSalesRaw({
    required String since,
    required String to,
    String includeStatuses = 'awaiting_assembly,awaiting_packaging,awaiting_deliver,delivering,delivered,canceled',
    String? status,
    String scheme = 'fbo',
  }) async {
    final resp = await dio.get('/analytics/sales_today_raw', queryParameters: {
      'since': since,
      'to': to,
      'include_statuses': includeStatuses,
      'scheme': scheme,
      if (status != null) 'status': status,
    });
    return _toJson(resp);
  }

  /// Получение отчета о продажах за период (товары, суммы, расходы).
  Future<Map<String, dynamic>> getSalesRange({
    required String since,
    required String to,
    String? status,
    String scheme = 'fbo',
  }) async {
    final resp = await dio.get(
      '/analytics/sales_range',
      queryParameters: {
        'since': since,
        'to': to,
        'scheme': scheme,
        if (status != null) 'status': status,
      },
    );
    return _toJson(resp);
  }

  /// Получение ежедневной статистики для графиков.
  Future<Map<String, dynamic>> getDailyStats({
    required String since,
    required String to,
    String scheme = 'fbo',
  }) async {
    final resp = await dio.get(
      '/analytics/daily_stats',
      queryParameters: {
        'since': since,
        'to': to,
        'scheme': scheme,
      },
    );
    return _toJson(resp);
  }

  /// Получение статуса синхронизации данных с Ozon.
  Future<Map<String, dynamic>> getSyncStatus() async {
    final resp = await dio.get('/auth/me/sync-status');
    return _toJson(resp);
  }

  /// Получение профиля текущего пользователя.
  Future<Map<String, dynamic>> getProfile() async {
    final resp = await dio.get('/auth/me');
    return _toJson(resp);
  }

  /// Получение списка невыполненных заказов FBS.
  Future<List<dynamic>> getUnfulfilledOrders() async {
    final resp = await dio.get('/orders/unfulfilled');
    if (resp.data is List) return resp.data;
    if (resp.data is Map && resp.data['items'] is List) return resp.data['items'];
    return [];
  }

  /// Получение сводной информации по конкретному заказу.
  Future<Map<String, dynamic>> getOrderSummary(String orderNumber) async {
    final resp = await dio.get('/order/$orderNumber');
    return _toJson(resp);
  }

  /// Получение сводки расходов за период.
  Future<Map<String, dynamic>> getExpensesSummary({
    required String since,
    required String to,
    String scheme = 'fbo',
  }) async {
    final resp = await dio.get(
      '/analytics/expenses_summary',
      queryParameters: {
        'since': since,
        'to': to,
        'scheme': scheme,
      },
    );
    return _toJson(resp);
  }

  /// Запуск ручной синхронизации данных.
  Future<Map<String, dynamic>> triggerManualSync() async {
    final resp = await dio.post('/sync/manual');
    return _toJson(resp);
  }

  /// Получение списка товаров и их себестоимости.
  Future<Map<String, dynamic>> getProductsList() async {
    final resp = await dio.get('/product-costs/products/list');
    return _toJson(resp);
  }

  /// Получение истории изменения себестоимости товара.
  Future<Map<String, dynamic>> getProductCostHistory(int sku) async {
    final resp = await dio.get('/product-costs/history/$sku');
    return _toJson(resp);
  }

  /// Установка новой себестоимости для товара.
  Future<Map<String, dynamic>> setProductCost({
    required int sku,
    String? offerId,
    required double costPrice,
    required DateTime effectiveFrom,
  }) async {
    final resp = await dio.post(
      '/product-costs',
      data: {
        'sku': sku,
        'offer_id': offerId,
        'cost_price': costPrice,
        'effective_from': effectiveFrom.toIso8601String(),
      },
    );
    return _toJson(resp);
  }

  /// Удаление записи о себестоимости.
  Future<Map<String, dynamic>> deleteProductCost(int costId) async {
    final resp = await dio.delete('/product-costs/$costId');
    return _toJson(resp);
  }

  /// Получает список методов доставки Ozon с маппингами.
  Future<List<dynamic>> getDeliveryMethods() async {
    final resp = await dio.get('/delivery-methods/');
    if (resp.data is List) return resp.data;
    return [];
  }

  /// Сохраняет пользовательское название для метода доставки.
  Future<Map<String, dynamic>> setDeliveryMethodMapping(int methodId, String customName) async {
    final resp = await dio.post('/delivery-methods/map', data: {
      'delivery_method_id': methodId,
      'custom_name': customName,
    });
    return _toJson(resp);
  }

  /// Удаляет пользовательское название (возврат к оригиналу).
  Future<Map<String, dynamic>> deleteDeliveryMethodMapping(int methodId) async {
    final resp = await dio.delete('/delivery-methods/map/$methodId');
    return _toJson(resp);
  }

  /// Безопасное преобразование тела ответа в Map<String, dynamic>.
  /// Обрабатывает null, String (JSON), Map и любые другие типы.
  Map<String, dynamic> _toJson(Response resp) {
    final data = resp.data;
    if (data == null) return {};
    if (data is Map<String, dynamic>) return data;
    if (data is String) {
      if (data.isEmpty) return {};
      try {
        final decoded = json.decode(data);
        if (decoded is Map<String, dynamic>) return decoded;
        return {};
      } catch (_) {
        debugPrint('_toJson: failed to decode JSON string');
        return {};
      }
    }
    // На случай, если Dio вернул List или другой тип — оборачиваем в Map
    if (data is List) {
      return {'items': data};
    }
    debugPrint('_toJson: unexpected data type ${data.runtimeType}');
    return {};
  }
}