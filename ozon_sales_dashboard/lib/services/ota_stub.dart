import 'package:flutter/material.dart';

/// Заглушка для Web-платформы, где ota_update недоступен.
void startOtaUpdate(BuildContext context, String url) {
  debugPrint('OTA Update не поддерживается на данной платформе.');
}
