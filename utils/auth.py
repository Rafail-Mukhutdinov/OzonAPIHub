"""
Модуль аутентификации и безопасности.
Отвечает за хеширование паролей, генерацию JWT-токенов и проверку прав доступа пользователей.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from db.database import get_db, User

# Настройки безопасности из переменных окружения
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

if not JWT_SECRET_KEY:
    raise RuntimeError(
        "ОШИБКА БЕЗОПАСНОСТИ: Переменная окружения JWT_SECRET_KEY не установлена. "
        "Приложение остановлено во избежание взлома. Пожалуйста, добавьте секретный ключ в .env файл."
    )

if len(JWT_SECRET_KEY) < 32:
    print("ВНИМАНИЕ: Ваш JWT_SECRET_KEY слишком короткий (менее 32 символов). Рекомендуется использовать более длинный ключ.")

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

# Схема OAuth2: FastAPI будет искать токен в заголовке Authorization: Bearer <token>
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверяет соответствие открытого пароля его хешу в БД."""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def get_password_hash(password: str) -> str:
    """
    Генерирует защищенный хеш пароля с использованием алгоритма bcrypt.
    Используется при регистрации и смене пароля.
    """
    if len(password.encode('utf-8')) > 72:
        raise ValueError("Пароль слишком длинный (максимум 72 байта для bcrypt)")
    salt = bcrypt.gensalt(rounds=12) # Соль делает хеш уникальным даже для одинаковых паролей
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Генерирует JWT (JSON Web Token) для аутентификации пользователя.
    В payload токена записывается 'sub' (email пользователя) и время истечения 'exp'.
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    # Шифруем данные секретным ключом
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """
    Выполняет поиск пользователя в БД и проверку пароля.
    Возвращает объект User при успехе или None.
    """
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    Главная зависимость (Dependency) для защищенных эндпоинтов.
    1. Извлекает токен из запроса.
    2. Проверяет его валидность и срок годности.
    3. Ищет пользователя в БД по email из токена.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось проверить учетные данные (токен истек или неверен)",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Декодируем токен
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    # Ищем пользователя
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception
    
    # Проверка на блокировку аккаунта
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Аккаунт заблокирован или деактивирован"
        )
    
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Обертка над get_current_user для явной проверки активности."""
    return current_user


def check_subscription(user: User) -> bool:
    """
    Проверяет, не истек ли оплаченный период использования сервиса.
    Пользователи в демо-режиме всегда имеют доступ.
    """
    if user.is_demo:
        return True
    
    if user.subscription_end_date is None:
        return False
    
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return user.subscription_end_date > now


async def get_current_user_with_subscription(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """
    Dependency для эндпоинтов, требующих активную подписку.
    Выдает ошибку 402 Payment Required, если период истек.
    """
    if not check_subscription(current_user):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Подписка истекла. Пожалуйста, продлите доступ в личном кабинете."
        )
    return current_user
