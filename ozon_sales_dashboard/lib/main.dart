import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:provider/provider.dart';
import 'providers/auth_provider.dart';
import 'services/api.dart'; // Для доступа к rootScaffoldMessengerKey

/**
 * Точка входа в приложение Flutter.
 * Здесь инициализируются локализация, состояние (Providers) и основные настройки темы.
 */
void main() {
  // Инициализация форматов дат для русского языка (нужно для календарей и графиков)
  initializeDateFormatting('ru_RU', null).then((_) {
    runApp(const MyApp());
  });
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});
  
  @override
  Widget build(BuildContext context) {
    // MultiProvider позволяет управлять состоянием всего приложения (Auth, Данные и т.д.)
    return MultiProvider(
      providers: [
        // Провайдер аутентификации - хранит данные о текущем пользователе и токене
        ChangeNotifierProvider(create: (_) => AuthProvider()),
      ],
      child: MaterialApp(
        title: 'Sales Hub',
        scaffoldMessengerKey: rootScaffoldMessengerKey,
        // Настройка визуальной темы приложения (Material 3)
        // Используем нейтральную профессиональную цветовую схему
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(
            seedColor: const Color(0xFF2C3E50), // Темно-синий/грифельный
            primary: const Color(0xFF2C3E50),
            secondary: const Color(0xFF3498DB),
          ),
          useMaterial3: true,
          appBarTheme: const AppBarTheme(
            backgroundColor: Colors.white,
            foregroundColor: Color(0xFF2C3E50),
            elevation: 0,
            centerTitle: false, // Более стандартно для дашбордов
          ),
          scaffoldBackgroundColor: const Color(0xFFF8F9FA),
          cardTheme: const CardThemeData(
            elevation: 2,
            surfaceTintColor: Colors.white,
          ),
        ),
        // Поддержка перевода стандартных виджетов (кнопки "OK", "Отмена", календари)
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        supportedLocales: const [
          Locale('en', 'US'),
          Locale('ru', 'RU'),
        ],
        // Начальный экран: проверяет наличие токена и перенаправляет на Login или Dashboard
        home: const AuthGate(),
      ),
    );
  }
}
