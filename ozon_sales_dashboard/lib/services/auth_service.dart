import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter/foundation.dart';
import 'api.dart';

/**
 * AuthService — выделенный сервис для работы с аккаунтом.
 * Отвечает за:
 * 1. Отправку учетных данных на сервер (Login/Register).
 * 2. Получение и локальное сохранение JWT токена в защищенное хранилище.
 * 3. Очистку сессии при выходе.
 */
class AuthService {
  static const String _tokenKey = 'jwt_token';
  final Dio dio;
  final FlutterSecureStorage _secureStorage = const FlutterSecureStorage();

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
          'username': email, 
          'password': password,
        },
        options: Options(
          contentType: Headers.formUrlEncodedContentType,
          // ВАЖНО: Добавляем эти заголовки для Web
          headers: {
            'Accept': 'application/json',
          },
        ),
      );

      final data = response.data as Map<String, dynamic>;
      final token = data['access_token'] as String;
      
      await _saveToken(token); // Сохраняем защищенно
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

  /// Удаляет токен из защищенного хранилища.
  Future<void> logout() async {
    await _secureStorage.delete(key: _tokenKey);
  }

  /// Проверяет наличие сохраненной сессии.
  Future<bool> isAuthenticated() async {
    final token = await _secureStorage.read(key: _tokenKey);
    return token != null && token.isNotEmpty;
  }

  /// Читает токен из защищенного хранилища.
  Future<String?> getToken() async {
    return await _secureStorage.read(key: _tokenKey);
  }

  /// Внутренний метод для записи токена в FlutterSecureStorage.
  Future<void> _saveToken(String token) async {
    await _secureStorage.write(key: _tokenKey, value: token);
  }
}
