import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:ota_update/ota_update.dart';
import 'api.dart';

class UpdateService {
  final OzonApiClient api;

  UpdateService(this.api);

  Future<void> checkForUpdates(BuildContext context) async {
    try {
      // 1. Получаем инфо о текущей версии
      final packageInfo = await PackageInfo.fromPlatform();
      // buildNumber — это то, что идет после + в version (например, 1.0.0+1 -> 1)
      final currentVersionCode = int.tryParse(packageInfo.buildNumber) ?? 0;

      // 2. Запрашиваем инфо о последней версии с сервера
      final response = await api.dio.get('/app/latest-version');
      final data = response.data;

      final latestVersionCode = data['version_code'] as int;
      final latestVersionName = data['version_name'] as String;
      final updateMessage = data['display_message'] as String;
      final downloadUrlFragment = data['download_url'] as String;

      // Ссылка на скачивание (объединяем base_url и фрагмент из ответа)
      // Убираем лишние слеши при склейке
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
      } else {
        debugPrint('Приложение актуально: $currentVersionCode >= $latestVersionCode');
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
        title: Text('Доступна новая версия: $version'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(message),
            const SizedBox(height: 10),
            const Text(
              'При нажатии на "Обновить" начнется скачивание файла. Пожалуйста, разрешите установку из этого источника, если система спросит.',
              style: TextStyle(fontSize: 12, color: Colors.grey),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Позже'),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(context);
              _executeUpdate(context, url);
            },
            child: const Text('Обновить сейчас'),
          ),
        ],
      ),
    );
  }

  void _executeUpdate(BuildContext context, String url) {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Загрузка обновления...')),
    );
    
    try {
      OtaUpdate().execute(
        url,
        destinationFilename: 'ozon_hub_update.apk',
      ).listen(
        (OtaEvent event) {
          debugPrint('OTA Status: ${event.status} : ${event.value}');
          if (event.status == OtaStatus.DOWNLOADING) {
            // Можно добавить прогресс-бар, если захотим
          }
        },
      );
    } catch (e) {
      debugPrint('Не удалось запустить обновление: $e');
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Ошибка обновления: $e')),
      );
    }
  }
}
