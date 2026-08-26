"""
Скрипт для сверки данных между локальной БД и официальным Ozon API.

Назначение:
    - Используется администратором для контроля полноты данных.
    - Помогает найти "пропущенные" заказы, которые есть в Ozon, но не попали в базу приложения.

Логика работы:
    1. Выгружает список всех постингов напрямую из Ozon API за указанный период (08-17 июня).
    2. Группирует полученные из API заказы по дате (в часовом поясе МСК).
    3. Выгружает все заказы из локальной таблицы 'order_postings' и также группирует по дате.
    4. Сравнивает два набора данных день за днем и выводит разницу (каких номеров заказов не хватает).

Ключевые переменные:
    - all_postings: Список всех заказов, полученных напрямую из Ozon (через пагинацию offset/limit).
    - ozon_by_date: Словарь {дата: [список номеров заказов в Ozon]}.
    - db_by_date: Словарь {дата: [список номеров заказов в БД]}.
    - only_in_ozon: Заказы, которые нужно догрузить в БД.
"""
import asyncio
from db.database import SessionLocal, User, OzonCredential, OrderPosting
from utils.encryption import decrypt_credential
from services.ozon import ozon_fbo_list_async
from utils.common import parse_ozon_datetime

async def main():
    """
    Основной цикл сверки данных.
    """
    session = SessionLocal()
    # Берем первого пользователя для теста
    user = session.query(User).first()
    if not user:
        print('Ошибка: Пользователь не найден')
        return
    
    # Получаем активные ключи API
    cred = session.query(OzonCredential).filter(OzonCredential.user_id == user.id, OzonCredential.is_active == True).first()
    if not cred:
        print('Ошибка: API ключи не найдены или не активны')
        return
    
    client_id = decrypt_credential(cred.client_id_encrypted)
    api_key = decrypt_credential(cred.api_key_encrypted)
    
    # 1. Сбор данных из Ozon API (Период: 2026-06-08 - 2026-06-17)
    all_postings = []
    print("Запрос данных из Ozon API...")
    for offset in range(0, 2000, 50):
        resp = await ozon_fbo_list_async(
            client_id, api_key,
            {"since": "2026-06-08T00:00:00Z", "to": "2026-06-17T23:59:59Z"},
            limit=50,
            offset=offset
        )
        if not resp:
            break
        result = resp.get('result')
        if not result:
            break
        
        # Унификация формата ответа API (может быть списком или словарем с ключом postings)
        if isinstance(result, dict):
            postings = result.get('postings', [])
        elif isinstance(result, list):
            postings = result
        else:
            postings = []
            
        if not postings:
            break
            
        all_postings.extend(postings)
        print(f"Загружено из API: {len(all_postings)} заказов...")
    
    print(f"\nИтого в Ozon за период: {len(all_postings)}")
    
    # Группировка данных Ozon по датам (MSK) для удобного сравнения
    from collections import defaultdict
    from utils.common import to_msk
    
    ozon_by_date = defaultdict(list)
    for p in all_postings:
        pn = p.get('posting_number')
        created = p.get('created_at')
        status = p.get('status')
        if created:
            dt = parse_ozon_datetime(created)
            if dt:
                msk_dt = to_msk(dt)
                date = msk_dt.date().isoformat()
                ozon_by_date[date].append((pn, status))
    
    # 2. Сбор данных из локальной БД
    db_by_date = defaultdict(list)
    db_postings = session.query(OrderPosting).all()
    for op in db_postings:
        if op.created_at:
            dt = parse_ozon_datetime(op.created_at)
            if dt:
                msk_dt = to_msk(dt)
                date = msk_dt.date().isoformat()
                db_by_date[date].append((op.posting_number, op.status))
    
    # 3. Сравнение и вывод результатов
    print("\n=== ОТЧЕТ О СРАВНЕНИИ (OZON vs DATABASE) ===")
    all_dates = sorted(set(list(ozon_by_date.keys()) + list(db_by_date.keys())))
    
    for date in all_dates:
        # Фильтруем вывод только по интересующему нас диапазону
        if '2026-06-08' <= date <= '2026-06-17':
            ozon_list = sorted([pn for pn, _ in ozon_by_date[date]])
            db_list = sorted([pn for pn, _ in db_by_date[date]])
            
            # Нахождение разницы через множества (Sets)
            only_in_ozon = set(ozon_list) - set(db_list)
            only_in_db = set(db_list) - set(ozon_list)
            
            print(f"{date}: Ozon={len(ozon_list)}, DB={len(db_list)}, Разница={len(only_in_ozon)}")
            
            if only_in_db:
                print(f"  [!] Только в БД (неизвестно Ozon): {list(only_in_db)[:5]}")
            if only_in_ozon:
                print(f"  [+] Отсутствуют в БД: {list(only_in_ozon)[:5]}")
    
    session.close()

if __name__ == '__main__':
    asyncio.run(main())
