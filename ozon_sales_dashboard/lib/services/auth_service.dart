import 'dart:convert';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart'; // Добавляем
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart'; // Добавляем
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
    baseUrl: OzonApiClient.getDefaultBaseUrl(),
    connectTimeout: const Duration(seconds: 30),
    receiveTimeout: const Duration(seconds: 30),
  ));

  /// Безопасно извлекает Map из тела ответа (обрабатывает null, String JSON, Map).
  Map<String, dynamic>? _extractMap(dynamic data) {
    if (data == null) return null;
    if (data is Map<String, dynamic>) return data;
    if (data is String) {
      if (data.isEmpty) return null;
      try {
        final decoded = json.decode(data);
        if (decoded is Map<String, dynamic>) return decoded;
      } catch (_) {}
    }
    return null;
  }

  /// Выполняет вход в систему.
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
          headers: {'Accept': 'application/json'},
        ),
      );

      final data = _extractMap(response.data);
      if (data == null) {
        throw Exception('Некорректный ответ сервера');
      }
      final token = data['access_token'];
      if (token is! String || token.isEmpty) {
        throw Exception('Токен не получен от сервера');
      }

      await _saveToken(token);
      return token;
    } on DioException catch (e) {
      if (e.response?.statusCode == 401) {
        throw Exception('Неверный email или пароль');
      }
      final errorData = _extractMap(e.response?.data);
      if (errorData != null && errorData['detail'] is String) {
        throw Exception(errorData['detail']);
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
        options: Options(contentType: Headers.jsonContentType),
      );

      return await login(email, password);
    } on DioException catch (e) {
      if (e.response?.statusCode == 400 || e.response?.statusCode == 422) {
        final errorData = _extractMap(e.response?.data);
        if (errorData != null) {
          final detail = errorData['detail'];
          if (detail is String) throw Exception(detail);
          if (detail is List && detail.isNotEmpty) {
            final first = detail.first;
            if (first is Map && first['msg'] is String) {
              throw Exception(first['msg']);
            }
          }
        }
        throw Exception('Ошибка валидации данных');
      }
      throw Exception('Ошибка сервера при регистрации');
    }
  }

  Future<void> logout() async {
    try {
      if (kIsWeb) {
        final prefs = await SharedPreferences.getInstance();
        await prefs.remove(_tokenKey);
      } else {
        await _secureStorage.delete(key: _tokenKey);
      }
    } catch (_) {}
  }

  Future<bool> isAuthenticated() async {
    try {
      String? token;
      if (kIsWeb) {
        final prefs = await SharedPreferences.getInstance();
        token = prefs.getString(_tokenKey);
      } else {
        token = await _secureStorage.read(key: _tokenKey);
      }
      return token != null && token.isNotEmpty;
    } catch (_) {
      return false;
    }
  }

  Future<String?> getToken() async {
    try {
      if (kIsWeb) {
        final prefs = await SharedPreferences.getInstance();
        return prefs.getString(_tokenKey);
      } else {
        return await _secureStorage.read(key: _tokenKey);
      }
    } catch (_) {
      return null;
    }
  }

  Future<void> _saveToken(String token) async {
    try {
      if (kIsWeb) {
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString(_tokenKey, token);
      } else {
        await _secureStorage.write(key: _tokenKey, value: token);
      }
    } catch (_) {}
  }
}