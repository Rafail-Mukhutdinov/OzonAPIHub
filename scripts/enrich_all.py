#!/usr/bin/env python3
"""
Скрипт для массового обогащения ВСЕХ постингов пользователя в базе данных.
Используется для подгрузки изображений и финансовых данных для всей истории.
"""
import asyncio
import sys
from sqlalchemy.orm import Session
from db.database import SessionLocal, OrderPosting, User, Order
from services.enrichment import enrich_posting_from_ozon

async def enrich_all_for_user(user_id: int):
    print(f"--- Запуск полного обогащения для пользователя ID: {user_id} ---")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            print(f"Ошибка: Пользователь {user_id} не найден в базе.")
            return

        # 1. Собираем все уникальные номера постингов из обеих таблиц
        print("Сканирование базы данных на наличие заказов...")

        # Постинги из нормализованной таблицы
        norm_pns = db.query(OrderPosting.posting_number).filter(OrderPosting.user_id == user_id).all()
        # Постинги из сырой таблицы
        raw_pns = db.query(Order.posting_number).filter(Order.user_id == user_id).all()

        all_pns = sorted(set([p[0] for p in norm_pns] + [p[0] for p in raw_pns]))
        total = len(all_pns)

        print(f"Найдено заказов в базе: {total}")

        if total == 0:
            print("Заказов не найдено. Обогащение не требуется.")
            return

        print("Начинаю процесс обогащения. Это может занять время из-за лимитов Ozon API...")

        success = 0
        errors = 0

        for i, pn in enumerate(all_pns, 1):
            try:
                # Каждые 10 заказов выводим прогресс
                if i % 10 == 0 or i == total:
                    print(f"Прогресс: {i}/{total} (Успешно: {success}, Ошибок: {errors})")

                # Вызываем обогащение. Оно внутри себя сходит в Ozon за деталями и картинкой
                result = await enrich_posting_from_ozon(pn, user_id, db)

                if result.get("status") == "ok":
                    success += 1
                    # Коммитим каждые 5 заказов для стабильности
                    if i % 5 == 0:
                        db.commit()
                else:
                    errors += 1
                    db.rollback()
                    print(f"\n[!] Ошибка для {pn}: {result.get('status')} - {result.get('detail', '')}")

                # Небольшая пауза, чтобы не спамить API слишком сильно
                await asyncio.sleep(0.1)

            except Exception as e:
                errors += 1
                db.rollback()
                print(f"\n[!] Критическая ошибка на заказе {pn}: {e}")

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
