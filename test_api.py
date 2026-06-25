"""
Полный тест API
"""
import httpx
import json

BASE_URL = "http://127.0.0.1:8083"

async def test_full_flow():
    """Тестируем полный цикл"""
    import time
    timestamp = int(time.time())
    email = f"testuser_{timestamp}@test.com"
    
    async with httpx.AsyncClient() as client:
        # 1. Health check
        print("=" * 60)
        print("1. Проверяем здоровье сервера (/ping)...")
        resp = await client.get(f"{BASE_URL}/ping")
        print(f"   Статус: {resp.status_code}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        print(f"   ✓ Ответ: {resp.json()}")
        
        # 2. Регистрация
        print("\n" + "=" * 60)
        print("2. Регистрируем пользователя...")
        register_data = {
            "email": email,
            "password": "SecurePass123",
            "confirm_password": "SecurePass123"
        }
        
        resp = await client.post(f"{BASE_URL}/auth/register", json=register_data)
        print(f"   Статус: {resp.status_code}")
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        
        token_data = resp.json()
        token = token_data["access_token"]
        print(f"   ✓ Token получен: {token[:50]}...")
        
        headers = {"Authorization": f"Bearer {token}"}
        
        # 3. Получаем профиль
        print("\n" + "=" * 60)
        print("3. Получаем профиль (/auth/me)...")
        resp = await client.get(f"{BASE_URL}/auth/me", headers=headers)
        print(f"   Статус: {resp.status_code}")
        assert resp.status_code == 200
        
        user = resp.json()
        print(f"   ✓ Email: {user['email']}")
        print(f"   ✓ Is Active: {user['is_active']}")
        print(f"   ✓ Is Admin: {user['is_admin']}")
        print(f"   ✓ Has Credentials: {user['has_credentials']}")
        assert user['is_admin'] == False, "New user should not be an admin"
        assert user['has_credentials'] == False, "Should not have credentials yet"
        
        # 4. Добавляем первый набор ключей
        print("\n" + "=" * 60)
        print("4. Добавляем первый набор ключей Ozon...")
        cred_data = {
            "client_id": "9876543210",
            "api_key": "api-key-first-12345",
            "name": "Main Store",
            "marketplace": "ozon"
        }
        
        resp = await client.post(f"{BASE_URL}/auth/me/ozon-credentials", json=cred_data, headers=headers)
        print(f"   Статус: {resp.status_code}")
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        print(f"   ✓ Ответ: {resp.json()}")
        
        # 5. Получаем список ключей
        print("\n" + "=" * 60)
        print("5. Получаем список ключей...")
        resp = await client.get(f"{BASE_URL}/auth/me/ozon-credentials", headers=headers)
        print(f"   Статус: {resp.status_code}")
        assert resp.status_code == 200
        
        creds = resp.json()["credentials"]
        print(f"   ✓ Найдено {len(creds)} набор(ов) ключей")
        assert len(creds) == 1
        assert creds[0]["name"] == "Main Store"
        assert creds[0]["is_active"] == True
        cred_id = creds[0]["id"]
        print(f"   ✓ Первый ключ ID: {cred_id}, активен: {creds[0]['is_active']}")
        
        # 6. Проверяем обновление профиля
        print("\n" + "=" * 60)
        print("6. Проверяем профиль после добавления ключей...")
        resp = await client.get(f"{BASE_URL}/auth/me", headers=headers)
        user = resp.json()
        print(f"   ✓ Has Credentials: {user['has_credentials']}")
        assert user['has_credentials'] == True, "Should have credentials now"
        
        # 7. Добавляем второй набор ключей
        print("\n" + "=" * 60)
        print("7. Добавляем второй набор ключей...")
        cred_data2 = {
            "client_id": "1111111111",
            "api_key": "api-key-second-67890",
            "name": "Secondary Store",
            "marketplace": "ozon"
        }
        
        resp = await client.post(f"{BASE_URL}/auth/me/ozon-credentials", json=cred_data2, headers=headers)
        print(f"   Статус: {resp.status_code}")
        assert resp.status_code == 201
        print(f"   ✓ Второй набор добавлен")
        
        # 8. Получаем список ключей (должно быть 2)
        print("\n" + "=" * 60)
        print("8. Проверяем список ключей (должно быть 2)...")
        resp = await client.get(f"{BASE_URL}/auth/me/ozon-credentials", headers=headers)
        creds = resp.json()["credentials"]
        print(f"   ✓ Найдено {len(creds)} наборов ключей")
        assert len(creds) == 2
        
        # Второй должен быть активным, первый - неактивным
        active_cred = next((c for c in creds if c["is_active"]), None)
        print(f"   ✓ Активный ключ: {active_cred['name']}")
        assert active_cred["name"] == "Secondary Store"
        
        # 9. Активируем первый ключ
        print("\n" + "=" * 60)
        print("9. Активируем первый ключ...")
        resp = await client.put(f"{BASE_URL}/auth/me/ozon-credentials/{cred_id}/activate", headers=headers)
        print(f"   Статус: {resp.status_code}")
        assert resp.status_code == 200
        print(f"   ✓ Первый ключ активирован")
        
        # 10. Проверяем, что первый активен, второй - нет
        print("\n" + "=" * 60)
        print("10. Проверяем активность ключей...")
        resp = await client.get(f"{BASE_URL}/auth/me/ozon-credentials", headers=headers)
        creds = resp.json()["credentials"]
        
        first = next((c for c in creds if c["id"] == cred_id), None)
        print(f"   ✓ Первый ключ активен: {first['is_active']}")
        assert first['is_active'] == True
        
        # 11. Удаляем второй ключ
        print("\n" + "=" * 60)
        print("11. Удаляем второй ключ...")
        second_id = next((c["id"] for c in creds if c["id"] != cred_id), None)
        resp = await client.delete(f"{BASE_URL}/auth/me/ozon-credentials/{second_id}", headers=headers)
        print(f"   Статус: {resp.status_code}")
        assert resp.status_code == 200
        print(f"   ✓ Второй ключ удален")
        
        # 12. Проверяем, что остался только один ключ
        print("\n" + "=" * 60)
        print("12. Проверяем финальный список ключей...")
        resp = await client.get(f"{BASE_URL}/auth/me/ozon-credentials", headers=headers)
        creds = resp.json()["credentials"]
        print(f"   ✓ Осталось {len(creds)} ключ(ей)")
        assert len(creds) == 1
        assert creds[0]["id"] == cred_id
        
        # 13. Узнаем общее количество пользователей
        print("\n" + "=" * 60)
        print("13. Узнаем общее количество пользователей на сервере...")
        url = f"{BASE_URL}/users-count-debug"
        print(f"   Запрос к: {url} (с токеном)")
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            total = resp.json()["total_users"]
            print(f"   ✓ Всего зарегистрировано: {total} пользователь(ей)")
        elif resp.status_code == 403:
            print(f"   🔒 Доступ запрещен (403): Сервер защищен, обычный юзер не видит статистику.")
        else:
            print(f"   ❌ Не удалось получить данные: {resp.status_code} (URL: {url})")

        print("\n" + "=" * 60)
        print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
        print("=" * 60)


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_full_flow())
