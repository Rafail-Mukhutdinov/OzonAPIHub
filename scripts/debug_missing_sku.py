"""
Скрипт для глубокой отладки отсутствующих SKU в данных о начислениях.

Назначение:
    - Используется разработчиком, когда в итоговом отчете "пропадает" товар или транзакция.
    - Позволяет увидеть "сырой" ответ от Ozon API и понять, на каком этапе теряются данные.

Логика работы:
    1. Делает прямой запрос к API начислений за конкретный день (2026-07-01).
    2. Проходит циклом через все страницы ответа API (пагинация через last_id).
    3. Выполняет текстовый поиск целевого SKU во всей структуре ответа.
    4. Если SKU найден, выводит подробности: категорию начисления, суммы комиссий и номер заказа.

Ключевые переменные:
    - target_sku: Артикул (SKU) товара, который мы разыскиваем.
    - date_str: День, в котором ищем транзакцию.
    - accruals: Список всех транзакций, полученных от Ozon за день.
"""
import sys
import os
import asyncio
from datetime import datetime

# Настройка окружения
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from db.database import SessionLocal, OzonCredential
from utils.encryption import decrypt_credential
from services.ozon import ozon_accruals_by_day_async, init_http_client, close_http_client

async def main():
    """
    Поиск конкретного SKU в сыром потоке данных API.
    """
    db = SessionLocal()
    # Получаем ключи первого доступного пользователя
    cred = db.query(OzonCredential).first()
    client_id = decrypt_credential(cred.client_id_encrypted)
    api_key = decrypt_credential(cred.api_key_encrypted)
    
    # Параметры поиска
    date_str = "2026-07-01"
    target_sku = 3454933416
    
    print(f"Запуск отладки: Ищем SKU {target_sku} в начислениях Ozon за {date_str}...")
    init_http_client()
    
    accruals = []
    last_id = ""
    # Цикл получения данных с учетом пагинации API Ozon
    while True:
        res = await ozon_accruals_by_day_async(client_id, api_key, date_str, last_id)
        data = res.get("accruals") or []
        if not data: 
            break
        accruals.extend(data)
        last_id = res.get("last_id")
        # Если last_id пустой, значит мы скачали все страницы
        if not last_id: 
            break

    print(f"Всего получено транзакций за день: {len(accruals)}")
    
    found = False
    # Перебор всех полученных транзакций для поиска нужного SKU
    for acc in accruals:
        raw_str = str(acc)
        # Простой текстовый поиск SKU в сыром дампе данных транзакции
        if str(target_sku) in raw_str:
            found = True
            print("\n--- ТРАНЗАКЦИЯ НАЙДЕНА ---")
            print(f"Категория (accrued_category): {acc.get('accrued_category')}")
            print(f"Итоговая сумма (total_amount): {acc.get('total_amount')}")
            
            # Если транзакция привязана к конкретному заказу (постингу)
            if acc.get("posting"):
                p = acc["posting"]
                print(f"Номер заказа: {p.get('posting_number')}")
                # Проверяем список товаров внутри заказа в этой транзакции
                for prod in p.get("products", []):
                    if int(prod.get("sku") or 0) == target_sku:
                        print(f"  ДЕТАЛИ ТОВАРА: SKU={prod.get('sku')}, sale_amount={prod.get('commission', {}).get('sale_amount')}")
            
            # Вывод дополнительных услуг (логистика, хранение и т.д.)
            if acc.get("item_fees"):
                print(f"Услуги/Сборы (item_fees): {acc.get('item_fees')}")

    if not found:
        print(f"\n[!] SKU {target_sku} не обнаружен в данных API Ozon за этот день.")
    
    # Закрытие ресурсов
    await close_http_client()
    db.close()

if __name__ == "__main__":
    asyncio.run(main())
