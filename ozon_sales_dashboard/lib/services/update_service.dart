import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:flutter/foundation.dart' show kIsWeb;

// Условный импорт: если мы в вебе, берем заглушку, если нет - мобильную версию
import 'ota_stub.dart' if (dart.library.io) 'ota_mobile.dart' as ota;
import 'api.dart';

class UpdateService {
  final OzonApiClient api;

  UpdateService(this.api);

  Future<void> checkForUpdates(BuildContext context) async {
    try {
      // 1. Получаем инфо о текущей версии
      final packageInfo = await PackageInfo.fromPlatform();
      final currentVersionCode = int.tryParse(packageInfo.buildNumber) ?? 0;

      debugPrint('Текущий version_code: $currentVersionCode');

      // 2. Запрашиваем инфо о последней версии с сервера
      final response = await api.dio.get('/app/latest-version');
      final data = response.data;

      final latestVersionCode = data['version_code'] as int;
      final latestVersionName = data['version_name'] as String;
      final updateMessage = data['display_message'] as String;
      final downloadUrlFragment = data['download_url'] as String;

      debugPrint('Последний version_code на сервере: $latestVersionCode');

      // Ссылка на скачивание
      String baseUrl = api.dio.options.baseUrl;
      if (baseUrl.endsWith('/')) baseUrl = baseUrl.substring(0, baseUrl.length - 1);
      String fragment = downloadUrlFragment;
      if (!fragment.startsWith('/')) fragment = '/$fragment';
      
      final fullDownloadUrl = "$baseUrl$fragment";

      // 3. Сравниваем версии
      if (latestVersionCode > currentVersionCode) {
        if (context.mounted) {
          _showUpdateDialog(context, latestVersionName, updateMessage, fullDownloadUrl);
        }
      }
    } catch (e) {
      debugPrint('Ошибка при проверке обновлений: $e');
    }
  }

  void _showUpdateDialog(BuildContext context, String version, String message, String url) {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: Text('Доступна версия $version'),
        content: Text(message),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Позже'),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(context);
              if (kIsWeb) {
                _launchUpdateUrl(context, url);
              } else {
                ota.startOtaUpdate(context, url);
              }
            },
            child: const Text('Обновить'),
          ),
        ],
      ),
    );
  }

  Future<void> _launchUpdateUrl(BuildContext context, String url) async {
    final uri = Uri.parse(url);
    try {
      if (await canLaunchUrl(uri)) {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
      }
    } catch (e) {
      debugPrint('Ошибка при открытии ссылки: $e');
    }
  }
}

class UpdateProgressDialog extends StatefulWidget {
  const UpdateProgressDialog({super.key});

  @override
  State<UpdateProgressDialog> createState() => _UpdateProgressDialogState();
}

class _UpdateProgressDialogState extends State<UpdateProgressDialog> {
  @override
  Widget build(BuildContext context) {
    return const AlertDialog(
      title: Text('Загрузка обновления...'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          LinearProgressIndicator(),
          SizedBox(height: 16),
          Text('Пожалуйста, не закрывайте приложение'),
        ],
      ),
    );
  }
}
