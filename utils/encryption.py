"""
Утилиты для работы с зашифрованными Ozon credentials в SaaS режиме.

Использует Fernet (симметричное шифрование) для защиты API ключей в БД.
"""

import os
from dotenv import load_dotenv  # Добавляем импорт
from cryptography.fernet import Fernet
from typing import Optional

# Загружаем переменные окружения
load_dotenv()

# Ключ шифрования должен быть в .env и НИКОГДА не коммититься в git!
# Генерация нового ключа: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

if not ENCRYPTION_KEY:
    raise ValueError(
        "ENCRYPTION_KEY не установлен в .env! "
        "Сгенерируйте его: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )

cipher_suite = Fernet(ENCRYPTION_KEY.encode())


def encrypt_credential(plaintext: str) -> str:
    """
    Шифрует credentials (Client ID или API Key).
    
    Args:
        plaintext: Незашифрованный ключ
        
    Returns:
        Зашифрованная строка (base64)
    """
    if not plaintext:
        return ""
    encrypted = cipher_suite.encrypt(plaintext.encode())
    return encrypted.decode()


def decrypt_credential(ciphertext: Optional[str]) -> Optional[str]:
    """
    Расшифровывает credentials.
    
    Args:
        ciphertext: Зашифрованный ключ
        
    Returns:
        Расшифрованная строка или None
    """
    if not ciphertext:
        return None
    try:
        decrypted = cipher_suite.decrypt(ciphertext.encode())
        return decrypted.decode()
    except Exception as e:
        print(f"Ошибка расшифровки: {e}")
        return None


def get_user_ozon_headers(user) -> dict:
    """
    Получает HTTP headers для Ozon API для конкретного пользователя.
    
    Args:
        user: SQLAlchemy User model instance
        
    Returns:
        dict с Client-Id и Api-Key
        
    Raises:
        ValueError: Если credentials не настроены
    """
    client_id = decrypt_credential(user.ozon_client_id)
    api_key = decrypt_credential(user.ozon_api_key)
    
    if not client_id or not api_key:
        raise ValueError(
            f"Ozon credentials не настроены для пользователя {user.email}. "
            "Пожалуйста, добавьте Client ID и API Key в настройках профиля."
        )
    
    return {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }


# Пример использования:
if __name__ == "__main__":
    # Тест шифрования/расшифрования
    test_client_id = "123456"
    test_api_key = "secret-key-12345"
    
    encrypted_id = encrypt_credential(test_client_id)
    encrypted_key = encrypt_credential(test_api_key)
    
    print(f"Encrypted Client ID: {encrypted_id}")
    print(f"Encrypted API Key: {encrypted_key}")
    
    decrypted_id = decrypt_credential(encrypted_id)
    decrypted_key = decrypt_credential(encrypted_key)
    
    print(f"Decrypted Client ID: {decrypted_id}")
    print(f"Decrypted API Key: {decrypted_key}")
    
    assert test_client_id == decrypted_id
    assert test_api_key == decrypted_key
    print("✓ Шифрование работает корректно!")