import 'package:flutter/material.dart';
import 'package:ota_update/ota_update.dart';
import 'update_service.dart';

/// Мобильная реализация с использованием нативного пакета ota_update.
void startOtaUpdate(BuildContext context, String url) {
  try {
    debugPrint('Запуск мобильного OTA обновления с URL: $url');
    
    // Показываем индикатор прогресса
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => const UpdateProgressDialog(),
    );

    OtaUpdate().execute(
      url,
      destinationFilename: 'ozon_sales_dashboard.apk',
      androidProviderAuthority: 'com.example.ozon_sales_dashboard.ota_update_provider',
    ).listen(
      (OtaEvent event) {
        debugPrint('OTA Status: ${event.status}, Progress: ${event.value}');
        // При завершении или ошибке диалог закроется сам если добавить логику в UpdateProgressDialog
      },
      onError: (error) {
        debugPrint('OTA Error: $error');
        if (context.mounted) Navigator.pop(context);
      },
    );
  } catch (e) {
    debugPrint('Ошибка при запуске нативного OTA: $e');
  }
}
