"""
Утилиты для работы с credentials пользователей в SaaS режиме.
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from db.database import OzonCredential, User
from utils.encryption import decrypt_credential
from typing import Tuple


def get_user_active_credentials(db: Session, user: User) -> Tuple[str, str]:
    """
    Получить активные Ozon credentials пользователя.
    
    Args:
        db: Сессия БД
        user: Объект пользователя
        
    Returns:
        Tuple[client_id, api_key] - расшифрованные ключи
        
    Raises:
        HTTPException: Если у пользователя нет активных ключей
    """
    # Ищем активный набор ключей
    active_cred = db.query(OzonCredential).filter(
        OzonCredential.user_id == user.id,
        OzonCredential.is_active == True
    ).first()
    
    if not active_cred:
        # Если нет активного, пробуем взять любой первый
        active_cred = db.query(OzonCredential).filter(
            OzonCredential.user_id == user.id
        ).first()
        
        if not active_cred:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="У вас не настроены Ozon API ключи. Перейдите в Настройки и добавьте ключи."
            )
        
        # Активируем первый найденный
        active_cred.is_active = True
        db.commit()
    
    # Расшифровываем credentials
    try:
        client_id = decrypt_credential(active_cred.client_id_encrypted)
        api_key = decrypt_credential(active_cred.api_key_encrypted)
        
        if not client_id or not api_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ошибка расшифровки ключей. Обратитесь к администратору."
            )
        
        return client_id, api_key
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка получения ключей: {str(e)}"
        )


def get_user_credential_by_id(db: Session, user: User, credential_id: int) -> Tuple[str, str]:
    """
    Получить конкретный набор Ozon credentials пользователя по ID.
    
    Args:
        db: Сессия БД
        user: Объект пользователя
        credential_id: ID набора ключей
        
    Returns:
        Tuple[client_id, api_key] - расшифрованные ключи
        
    Raises:
        HTTPException: Если набор не найден или не принадлежит пользователю
    """
    cred = db.query(OzonCredential).filter(
        OzonCredential.id == credential_id,
        OzonCredential.user_id == user.id
    ).first()
    
    if not cred:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Набор ключей не найден"
        )
    
    try:
        client_id = decrypt_credential(cred.client_id_encrypted)
        api_key = decrypt_credential(cred.api_key_encrypted)
        
        if not client_id or not api_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ошибка расшифровки ключей"
            )
        
        return client_id, api_key
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка получения ключей: {str(e)}"
        )
