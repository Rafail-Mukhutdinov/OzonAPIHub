import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:url_launcher/url_launcher.dart';
import 'api.dart';

class UpdateService {
  final OzonApiClient api;

  UpdateService(this.api);

  Future<void> checkForUpdates(BuildContext context) async {
    try {
      // 1. Получаем инфо о текущей версии
      final packageInfo = await PackageInfo.fromPlatform();
      final currentVersionCode = int.tryParse(packageInfo.buildNumber) ?? 0;

      // 2. Запрашиваем инфо о последней версии с сервера
      final response = await api.dio.get('/app/latest-version');
      final data = response.data;

      final latestVersionCode = data['version_code'] as int;
      final latestVersionName = data['version_name'] as String;
      final updateMessage = data['display_message'] as String;
      final downloadUrlFragment = data['download_url'] as String;

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
              _launchUpdateUrl(context, url);
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
      // Пытаемся открыть ссылку во внешнем браузере
      if (await canLaunchUrl(uri)) {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
      } else {
        throw 'Could not launch $url';
      }
    } catch (e) {
      debugPrint('Ошибка при открытии ссылки: $e');
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Ошибка: не удалось открыть браузер. Ссылка: $url')),
        );
      }
    }
  }
}
