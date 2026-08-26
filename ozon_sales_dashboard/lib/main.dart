import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:provider/provider.dart';
import 'providers/auth_provider.dart';
import 'services/api.dart'; // Для доступа к rootScaffoldMessengerKey

/// Точка входа в приложение Flutter.
/// Здесь инициализируются локализация, состояние (Providers) и глобальные настройки темы.
void main() {
  // Инициализация форматов дат для русского языка (необходимо для корректного отображения календарей и графиков)
  initializeDateFormatting('ru_RU', null).then((_) {
    runApp(const MyApp());
  });
}

/// MyApp — корневой виджет приложения.
/// Настраивает MultiProvider для управления состоянием и MaterialApp для конфигурации UI.
class MyApp extends StatelessWidget {
  const MyApp({super.key});
  
  @override
  Widget build(BuildContext context) {
    // MultiProvider позволяет централизованно управлять состоянием всего приложения.
    // Любой виджет в дереве может получить доступ к AuthProvider через context.watch или context.read.
    return MultiProvider(
      providers: [
        // Провайдер аутентификации — управляет токеном, ролями пользователя и локальной безопасностью.
        ChangeNotifierProvider(create: (_) => AuthProvider()),
      ],
      child: MaterialApp(
        title: 'Seller Hub',
        // Глобальный ключ для показа SnackBars из любой точки приложения (через OzonApiClient)
        scaffoldMessengerKey: rootScaffoldMessengerKey,
        
        /// Глобальная настройка визуальной темы приложения (Material 3).
        /// Цветовая схема построена на профессиональном темно-синем цвете (Color(0xFF2C3E50)).
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(
            seedColor: const Color(0xFF2C3E50), 
            primary: const Color(0xFF2C3E50),   // Основной цвет элементов управления
            secondary: const Color(0xFF3498DB), // Вспомогательный цвет (акценты)
          ),
          useMaterial3: true,
          
          // Настройка внешнего вида верхней панели (AppBar)
          appBarTheme: const AppBarTheme(
            backgroundColor: Colors.white,
            foregroundColor: Color(0xFF2C3E50),
            elevation: 0,
            centerTitle: false,
          ),
          
          // Фоновый цвет экранов — светло-серый для снижения нагрузки на глаза
          scaffoldBackgroundColor: const Color(0xFFF8F9FA),
          
          // Настройка стандартных карточек для создания чистого блочного интерфейса
          cardTheme: const CardThemeData(
            elevation: 2,
            surfaceTintColor: Colors.white,
          ),
        ),
        
        /// Поддержка локализации стандартных виджетов Flutter (диалоги, календари, кнопки выбора).
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        supportedLocales: const [
          Locale('en', 'US'),
          Locale('ru', 'RU'),
        ],
        
        /// AuthGate — экран-переключатель.
        /// Он анализирует состояние AuthProvider и решает: показать LoginScreen, PinScreen или DashboardScreen.
        home: const AuthGate(),
        
        // Примечание: Адаптивность реализована внутри экранов с помощью LayoutBuilder.
        // При ширине экрана > 800px приложение автоматически переходит в десктопный режим (NavRail вместо BottomBar).
      ),
    );
  }
}
