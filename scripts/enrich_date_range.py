#!/usr/bin/env python3
"""
Скрипт для точечного обогащения постингов за конкретную календарную дату.

Назначение:
    - Разработчик использует этот скрипт для перепроверки или обновления данных за определенный день.
    - В отличие от 'enrich_all', работает только в узком окне времени, что быстрее.

Логика работы:
    1. Принимает дату в часовом поясе МСК (MSK, UTC+3).
    2. Вычисляет границы дня (00:00:00 - 23:59:59) и переводит их в UTC для запроса к БД.
    3. Ищет все постинги в БД, созданные в этот промежуток времени.
    4. Для каждого найденного постингу запускает процедуру 'enrich_posting_from_ozon'.

Ключевые переменные:
    - date_str: Целевая дата (ГГГГ-ММ-ДД).
    - start_utc / end_utc: Временное окно в формате ISO UTC для фильтрации в SQL.
    - all_pns: Список уникальных номеров постингов, найденных за этот день.
"""
import asyncio
import sys
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.database import SessionLocal, OrderPosting, User, Order
from services.enrichment import enrich_posting_from_ozon

async def enrich_date_range(user_id: int, date_str: str):
    """
    Обогатить все постинги за конкретную дату (MSK).
    
    Логика расчета времени:
        Ozon хранит данные в UTC, но пользователь оперирует датами MSK.
        Для поиска мы берем границы дня по МСК и смещаем их на -3 часа для UTC.
    """
    from datetime import datetime, timedelta, timezone

    # Парсим дату в MSK (UTC+3)
    try:
        y, m, d = map(int, date_str.split('-'))
        # Начало дня MSK (00:00:00+03:00)
        start_msk = datetime(y, m, d, 0, 0, 0, tzinfo=timezone(timedelta(hours=3)))
        # Конец дня MSK (23:59:59+03:00)
        end_msk = datetime(y, m, d, 23, 59, 59, tzinfo=timezone(timedelta(hours=3)))
    except Exception as e:
        print(f"Ошибка формата даты: {e}. Используйте ГГГГ-ММ-ДД")
        return

    # Переводим в UTC для поиска в БД (стандарт хранения в БД - UTC Z)
    start_utc = start_msk.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    end_utc = end_msk.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    
    print(f"Ищу постинги за {date_str} (MSK)")
    print(f"UTC range: {start_utc} to {end_utc}")
    
    db = SessionLocal()
    try:
        # 1. Поиск в таблице нормализованных данных
        norm_postings = db.query(OrderPosting.posting_number).filter(
            OrderPosting.user_id == user_id,
            OrderPosting.created_at >= start_utc,
            OrderPosting.created_at <= end_utc
        ).all()

        # 2. Поиск в сырой таблице (для захвата еще не обработанных заказов)
        raw_postings = db.query(Order.posting_number).filter(
            Order.user_id == user_id,
            Order.created_at >= start_utc,
            Order.created_at <= end_utc
        ).all()

        # Собираем уникальный набор номеров заказов
        all_pns = sorted(set([p[0] for p in norm_postings] + [p[0] for p in raw_postings]))

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            print(f"Пользователь {user_id} не найден")
            return
        
        print(f"Найдено {len(all_pns)} уникальных постингов")
        
        # Цикл по каждому найденному заказу
        for i, pn in enumerate(all_pns, 1):
            try:
                print(f"[{i}/{len(all_pns)}] Обогащение {pn}...", end="")
                
                # Вызов основной логики обновления данных из API Ozon
                result = await enrich_posting_from_ozon(pn, user_id, db)
                
                if result.get("status") == "ok":
                    db.commit()
                    print(f" ✓")
                else:
                    db.rollback()
                    print(f" ✗ {result.get('status')}")
            except Exception as e:
                db.rollback()
                print(f" ✗ Ошибка: {e}")
                
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Использование: python enrich_date_range.py <user_id> <date>")
        print("Пример: python enrich_date_range.py 2 2026-02-01")
        sys.exit(1)
    
    u_id = int(sys.argv[1])
    d_str = sys.argv[2]
    
    asyncio.run(enrich_date_range(u_id, d_str))
