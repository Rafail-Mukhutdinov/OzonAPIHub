#!/usr/bin/env python3
"""
Скрипт для массового обогащения ВСЕХ постингов пользователя в базе данных.

Назначение:
    - Используется администратором или разработчиком для принудительного обновления 
      информации о постингах (товары, изображения, финансовые детали) по всей истории в БД.
    - Полезно после обновления логики парсинга или если часть данных была пропущена.

Логика работы:
    1. Получает все уникальные номера постингов из таблиц 'order_postings' и 'orders'.
    2. Для каждого номера вызывает сервис 'enrich_posting_from_ozon'.
    3. Выполняет коммит каждые 5 успешных операций для снижения нагрузки на БД.
    4. Соблюдает небольшую задержку (await asyncio.sleep), чтобы не превысить лимиты Ozon API.

Ключевые переменные:
    - user_id: ID пользователя, чьи данные будут обогащены.
    - all_pns: Отсортированный список уникальных номеров постингов (posting_number).
    - success/errors: Счетчики для итогового отчета.
"""
import asyncio
import sys
from sqlalchemy.orm import Session
from db.database import SessionLocal, OrderPosting, User, Order
from services.enrichment import enrich_posting_from_ozon

async def enrich_all_for_user(user_id: int):
    """
    Основная функция обогащения данных для пользователя.
    """
    print(f"--- Запуск полного обогащения для пользователя ID: {user_id} ---")

    db = SessionLocal()
    try:
        # Проверка существования пользователя
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            print(f"Ошибка: Пользователь {user_id} не найден в базе.")
            return

        # 1. Собираем все уникальные номера постингов из обеих таблиц
        # Это позволяет найти заказы, которые могли быть в сыром виде, но не попали в нормализованные
        print("Сканирование базы данных на наличие заказов...")

        # Постинги из нормализованной таблицы (уже обработанные)
        norm_pns = db.query(OrderPosting.posting_number).filter(OrderPosting.user_id == user_id).all()
        # Постинги из сырой таблицы (возможно, еще не полностью обработанные)
        raw_pns = db.query(Order.posting_number).filter(Order.user_id == user_id).all()

        # Объединяем и удаляем дубликаты
        all_pns = sorted(set([p[0] for p in norm_pns] + [p[0] for p in raw_pns]))
        total = len(all_pns)

        print(f"Найдено заказов в базе: {total}")

        if total == 0:
            print("Заказов не найдено. Обогащение не требуется.")
            return

        print("Начинаю процесс обогащения. Это может занять время из-за лимитов Ozon API...")

        success = 0
        errors = 0

        # Основной цикл обработки каждого найденного заказа
        for i, pn in enumerate(all_pns, 1):
            try:
                # Каждые 10 заказов выводим прогресс в консоль
                if i % 10 == 0 or i == total:
                    print(f"Прогресс: {i}/{total} (Успешно: {success}, Ошибок: {errors})")

                # Вызываем обогащение. Функция сама идет в Ozon API, скачивает детали и картинку
                result = await enrich_posting_from_ozon(pn, user_id, db)

                if result.get("status") == "ok":
                    success += 1
                    # Коммитим транзакцию пачками по 5, чтобы не держать соединение долго
                    if i % 5 == 0:
                        db.commit()
                else:
                    errors += 1
                    db.rollback() # Откатываем в случае ошибки в сервисе
                    print(f"\n[!] Ошибка для {pn}: {result.get('status')} - {result.get('detail', '')}")

                # Небольшая пауза для соблюдения Rate Limits API Ozon
                await asyncio.sleep(0.1)

            except Exception as e:
                errors += 1
                db.rollback()
                print(f"\n[!] Критическая ошибка на заказе {pn}: {e}")

        # Финальный коммит оставшихся записей
        db.commit()
        print(f"\n--- Обогащение завершено ---")
        print(f"Всего обработано: {total}")
        print(f"Успешно обновлено: {success}")
        print(f"Ошибок: {errors}")

    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python enrich_all.py <user_id>")
        sys.exit(1)

    uid = int(sys.argv[1])
    asyncio.run(enrich_all_for_user(uid))
