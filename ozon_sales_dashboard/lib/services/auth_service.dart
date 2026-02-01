import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'api.dart';

class AuthService {
  static const String _tokenKey = 'jwt_token';
  final Dio dio;

  AuthService() : dio = Dio(BaseOptions(
    baseUrl: OzonApiClient.getDefaultBaseUrl(),
    connectTimeout: const Duration(seconds: 30),
    receiveTimeout: const Duration(seconds: 30),
  ));

  /// Вход в систему
  Future<String> login(String email, String password) async {
    try {
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
      
      return token;
    } on DioException catch (e) {
      if (e.response?.statusCode == 401) {
        throw Exception('Неверный email или пароль');
      }
      throw Exception('Ошибка входа: ${e.message}');
    }
  }

  /// Регистрация
  Future<String> register(String email, String password, String confirmPassword) async {
    if (password != confirmPassword) {
      throw Exception('Пароли не совпадают');
    }

    try {
      final response = await dio.post(
        '/auth/register',
        data: {
          'email': email,
          'password': password,
        },
        options: Options(
          contentType: Headers.jsonContentType,
        ),
      );

      final data = response.data as Map<String, dynamic>;
      final token = data['access_token'] as String;
      
      // Сохраняем токен
      await _saveToken(token);
      
      return token;
    } on DioException catch (e) {
      if (e.response?.statusCode == 400) {
        final errorData = e.response?.data;
        if (errorData is Map && errorData['detail'] != null) {
          throw Exception(errorData['detail']);
        }
        throw Exception('Пользователь с таким email уже существует');
      }
      throw Exception('Ошибка регистрации: ${e.message}');
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
