import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter/foundation.dart';
import 'api.dart';

class AuthService {
  static const String _tokenKey = 'jwt_token';
  final Dio dio;

  AuthService() : dio = Dio(BaseOptions(
    baseUrl: OzonApiClient.getDefaultBaseUrl(),
    connectTimeout: const Duration(seconds: 30),
    receiveTimeout: const Duration(seconds: 30),
  )) {
    // Логирование для отладки
    if (kDebugMode) {
      print('[AuthService] Используемый baseUrl: ${dio.options.baseUrl}');
    }
  }

  /// Вход в систему
  Future<String> login(String email, String password) async {
    try {
      if (kDebugMode) {
        print('[AuthService] Попытка входа: $email на ${dio.options.baseUrl}/auth/login');
      }
      
      final response = await dio.post(
        '/auth/login',
        data: {
          'username': email,  // FastAPI OAuth2PasswordRequestForm использует 'username'
          'password': password,
        },
        options: Options(
          contentType: Headers.formUrlEncodedContentType,
        ),
      );

      final data = response.data as Map<String, dynamic>;
      final token = data['access_token'] as String;
      
      // Сохраняем токен
      await _saveToken(token);
      
      if (kDebugMode) {
        print('[AuthService] Вход успешен, токен получен');
      }
      
      return token;
    } on DioException catch (e) {
      if (kDebugMode) {
        print('[AuthService] Login DioException: ${e.message}, statusCode: ${e.response?.statusCode}');
      }
      
      if (e.response?.statusCode == 401) {
        throw Exception('Неверный email или пароль');
      }
      throw Exception('Ошибка входа: ${e.message}');
    }
  }

  /// Регистрация
  Future<String> register(String email, String password, String confirmPassword) async {
    // 1. Локальная проверка
    if (password != confirmPassword) {
      throw Exception('Пароли не совпадают');
    }

    try {
      if (kDebugMode) {
        print('[AuthService] Попытка регистрации: $email на ${dio.options.baseUrl}/auth/register');
      }
      
      // 2. Отправка запроса на регистрацию
      // ВАЖНО: Мы добавляем поле confirm_password, которое ждет бэкенд
      final response = await dio.post(
        '/auth/register',
        data: {
          'email': email,
          'password': password,
          'confirm_password': confirmPassword,
        },
        options: Options(
          contentType: Headers.jsonContentType,
        ),
      );
      
      if (kDebugMode) {
        print('[AuthService] Регистрация успешна: $response');
      }

      // 3. Сразу выполняем автоматический вход, чтобы получить токен
      return await login(email, password);

    } on DioException catch (e) {
      if (kDebugMode) {
        print('[AuthService] DioException: ${e.message}, statusCode: ${e.response?.statusCode}');
        print('[AuthService] Response data: ${e.response?.data}');
      }
      
      if (e.response?.statusCode == 400) {
        final errorData = e.response?.data;
        if (errorData is Map && errorData['detail'] != null) {
          throw Exception(errorData['detail']);
        }
        throw Exception('Ошибка валидации данных');
      }
      // Обработка ошибки 422 (если данные не соответствуют схеме Pydantic)
      if (e.response?.statusCode == 422) {
         throw Exception('Ошибка данных (422). Проверьте правильность email.');
      }
      
      throw Exception('Ошибка регистрации: ${e.message}');
    } catch (e) {
      if (kDebugMode) {
        print('[AuthService] Неизвестная ошибка: $e');
      }
      throw Exception('Ошибка регистрации: $e');
    }
  }

  /// Выход из системы
  Future<void> logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
  }

  /// Получить текущий токен
  Future<String?> getToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_tokenKey);
  }

  /// Проверить, авторизован ли пользователь
  Future<bool> isAuthenticated() async {
    final token = await getToken();
    return token != null && token.isNotEmpty;
  }

  /// Сохранить токен
  Future<void> _saveToken(String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, token);
  }
}
