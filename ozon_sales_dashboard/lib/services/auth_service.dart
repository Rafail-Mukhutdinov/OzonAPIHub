import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter/foundation.dart';
import 'api.dart';

/**
 * AuthService — выделенный сервис для работы с аккаунтом.
 * Отвечает за:
 * 1. Отправку учетных данных на сервер (Login/Register).
 * 2. Получение и локальное сохранение JWT токена.
 * 3. Очистку сессии при выходе.
 */
class AuthService {
  static const String _tokenKey = 'jwt_token';
  final Dio dio;

  AuthService() : dio = Dio(BaseOptions(
    baseUrl: OzonApiClient.getDefaultBaseUrl(), // Авто-определение адреса сервера
    connectTimeout: const Duration(seconds: 30),
    receiveTimeout: const Duration(seconds: 30),
  ));

  /// Выполняет вход в систему.
  /// Использует формат x-www-form-urlencoded, так как бэкенд FastAPI использует OAuth2PasswordRequestForm.
  Future<String> login(String email, String password) async {
    try {
      final response = await dio.post(
        '/auth/login',
        data: {
          'username': email, // В OAuth2 стандартное поле называется username
          'password': password,
        },
        options: Options(
          contentType: Headers.formUrlEncodedContentType,
        ),
      );

      final data = response.data as Map<String, dynamic>;
      final token = data['access_token'] as String;
      
      await _saveToken(token); // Сохраняем для будущих запросов
      return token;
    } on DioException catch (e) {
      if (e.response?.statusCode == 401) {
        throw Exception('Неверный email или пароль');
      }
      throw Exception('Ошибка сети при входе');
    }
  }

  /// Регистрация нового аккаунта.
  Future<String> register(String email, String password, String confirmPassword) async {
    if (password != confirmPassword) {
      throw Exception('Пароли не совпадают');
    }

    try {
      await dio.post(
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
      
      // После успешной регистрации сразу авторизуем пользователя
      return await login(email, password);

    } on DioException catch (e) {
      // Парсим детальную ошибку от Pydantic/FastAPI
      if (e.response?.statusCode == 400 || e.response?.statusCode == 422) {
        final detail = e.response?.data?['detail'];
        throw Exception(detail ?? 'Ошибка валидации данных');
      }
      throw Exception('Ошибка сервера при регистрации');
    }
  }

  /// Удаляет токен из памяти устройства.
  Future<void> logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
  }

  /// Проверяет наличие сохраненной сессии.
  Future<bool> isAuthenticated() async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString(_tokenKey);
    return token != null && token.isNotEmpty;
  }

  /// Внутренний метод для записи токена в SharedPreferences.
  Future<void> _saveToken(String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, token);
  }
}
