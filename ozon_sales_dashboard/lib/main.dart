import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:provider/provider.dart';
import 'providers/auth_provider.dart';
import 'screens/check_auth_screen.dart';

void main() {
  initializeDateFormatting('ru_RU', null).then((_) {
    runApp(const MyApp());
  });
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});
  
  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => AuthProvider()),
      ],
      child: MaterialApp(
        title: 'Ozon Sales Dashboard',
        theme: ThemeData(
          colorSchemeSeed: Colors.blue,
          useMaterial3: true,
        ),
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        supportedLocales: const [
          Locale('en', 'US'),
          Locale('ru', 'RU'),
        ],
        home: const CheckAuthScreen(),
      ),
    );
  }
}
