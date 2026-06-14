"""
Модуль шифрования конфиденциальных данных.
Использует библиотеку cryptography (Fernet) для защиты API-ключей пользователей в базе данных.
Это критически важно для SaaS-сервиса, чтобы даже при доступе к БД ключи нельзя было прочитать.
"""

import os
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from typing import Optional

# Загружаем переменные окружения, чтобы получить мастер-ключ ENCRYPTION_KEY
load_dotenv()

# Мастер-ключ должен быть 32-битной строкой base64.
# Он является "корнем доверия" всей системы.
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

if not ENCRYPTION_KEY:
    raise ValueError(
        "ОШИБКА: ENCRYPTION_KEY не найден в .env! Без него работа с ключами Ozon невозможна. "
        "Сгенерируйте новый: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )

# Инициализируем объект для шифрования/дешифрования
try:
    cipher_suite = Fernet(ENCRYPTION_KEY.encode())
except Exception as e:
    raise ValueError(f"ОШИБКА: Некорректный ENCRYPTION_KEY. Он должен быть валидным Fernet-ключом. Детали: {e}")


def encrypt_credential(plaintext: str) -> str:
    """
    Зашифровывает открытый текст (например, API-ключ Ozon).
    
    Args:
        plaintext: Строка в открытом виде.
        
    Returns:
        Зашифрованная строка (в формате base64), готовую для сохранения в БД.
    """
    if not plaintext:
        return ""
    encrypted = cipher_suite.encrypt(plaintext.encode())
    return encrypted.decode()


def decrypt_credential(ciphertext: Optional[str]) -> Optional[str]:
    """
    Расшифровывает данные, полученные из базы данных.
    
    Args:
        ciphertext: Зашифрованная строка из столбца *_encrypted в БД.
        
    Returns:
        Исходная строка (открытый текст) или None при ошибке.
    """
    if not ciphertext:
        return None
    try:
        # Пытаемся расшифровать мастер-ключом
        decrypted = cipher_suite.decrypt(ciphertext.encode())
        return decrypted.decode()
    except Exception as e:
        # Ошибка может возникнуть, если сменился ENCRYPTION_KEY в .env
        print(f"КРИТИЧЕСКАЯ ОШИБКА РАСШИФРОВКИ: Возможно, мастер-ключ не совпадает. {e}")
        return None


def get_user_ozon_headers(user) -> dict:
    """
    Вспомогательная функция (устарела, используется в legacy коде).
    Генерирует заголовки для Ozon API, расшифровывая ключи пользователя на лету.
    """
    client_id = decrypt_credential(user.ozon_client_id)
    api_key = decrypt_credential(user.ozon_api_key)
    
    if not client_id or not api_key:
        raise ValueError(
            f"Ozon credentials не настроены для пользователя {user.email}."
        )
    
    return {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }


# Тестовый запуск модуля (для проверки работоспособности ключа)
if __name__ == "__main__":
    test_val = "ozon-api-key-test-123"
    enc = encrypt_credential(test_val)
    dec = decrypt_credential(enc)
    
    print(f"Original:  {test_val}")
    print(f"Encrypted: {enc}")
    print(f"Decrypted: {dec}")
    
    if test_val == dec:
        print("✓ Шифрование работает корректно!")
    else:
        print("✗ ОШИБКА ШИФРОВАНИЯ!")
