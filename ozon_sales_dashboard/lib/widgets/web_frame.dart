import 'dart:math';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

/// WebFrame — адаптивная обёртка для имитации мобильного устройства в Web-версии.
/// Реализована согласно спецификации: W = min(450, availH/2.05, availW), H = W*2.05.
class WebFrame extends StatelessWidget {
  final Widget? child;
  static const double threshold = 600.0;
  static const double maxWebWidth = 450.0;
  static const double aspectRatio = 2.05; // Соотношение сторон корпуса

  const WebFrame({super.key, this.child});

  @override
  Widget build(BuildContext context) {
    if (child == null) return const SizedBox.shrink();

    return LayoutBuilder(
      builder: (context, constraints) {
        final double availW = constraints.maxWidth;
        final double availH = constraints.maxHeight - 32; // Поля 16+16 по вертикали

        // Guard: Если это не Web или ширина окна маленькая
        if (!kIsWeb || availW <= threshold) {
          return child!;
        }

        // Расчёт размеров согласно формуле
        double frameW = min(maxWebWidth, availH / aspectRatio);
        frameW = min(frameW, availW - 32);
        
        // Если рамка получается слишком узкой (например, в низких окнах) — уходим в fullscreen
        if (frameW < 320) return child!;
        
        final double frameH = frameW * aspectRatio;
        final double radius = frameW * 0.08;
        const double bezel = 10.0; // Ширина рамки (безеля)

        return Container(
          color: const Color(0xFF1A252F), // Внешний фон
          child: Center(
            child: Container(
              width: frameW,
              height: frameH,
              decoration: BoxDecoration(
                color: const Color(0xFF1A252F), // Цвет корпуса телефона
                borderRadius: BorderRadius.circular(radius),
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x99000000), // Тень (0.6 opacity)
                    blurRadius: 40,
                    offset: Offset(0, 15),
                  ),
                ],
              ),
              padding: const EdgeInsets.all(bezel), // Безель
              child: ClipRRect(
                borderRadius: BorderRadius.circular(radius - bezel),
                child: Container(
                  color: const Color(0xFFF8F9FA), // Фон экрана приложения
                  child: _MediaQueryOverride(
                    size: Size(frameW - (bezel * 2), frameH - (bezel * 2)),
                    child: child!,
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

class _MediaQueryOverride extends StatelessWidget {
  final Size size;
  final Widget child;

  const _MediaQueryOverride({required this.size, required this.child});

  @override
  Widget build(BuildContext context) {
    final data = MediaQuery.of(context);
    return MediaQuery(
      data: data.copyWith(
        size: size,
        // Обнуляем системные отступы, так как внутри рамки "телефон" имитирует чистый экран
        padding: EdgeInsets.zero,
        viewInsets: EdgeInsets.zero,
        viewPadding: EdgeInsets.zero,
      ),
      child: child,
    );
  }
}
