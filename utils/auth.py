"""
Модуль аутентификации для SaaS режима.

Функционал:
- JWT токены для аутентификации
- Хеширование паролей (bcrypt)
- Dependency для получения текущего пользователя
- Регистрация и вход
"""

import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from db.database import get_db, User

# Настройки из .env
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-CHANGE-ME")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

# Хеширование паролей
# Используем bcryptpy вместо дефолтного bcrypt backend для избежания ошибки wrap bug detection
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__default_rounds=12)

# OAuth2 scheme для JWT
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверка пароля."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Хеширование пароля."""
    # Проверка длины пароля (ограничение bcrypt)
    if len(password.encode('utf-8')) > 72:
        raise ValueError("Пароль слишком длинный (максимум 72 байта)")
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Создание JWT токена.
    
    Args:
        data: Данные для включения в токен (обычно {"sub": user.email})
        expires_delta: Время жизни токена
        
    Returns:
        JWT токен (строка)
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """
    Аутентификация пользователя.
    
    Args:
        db: Database session
        email: Email пользователя
        password: Пароль (plain text)
        
    Returns:
        User объект или None
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
    FastAPI dependency для получения текущего пользователя из JWT токена.
    
    Использование:
        @router.get("/me")
        async def get_me(current_user: User = Depends(get_current_user)):
            return current_user
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось проверить учетные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Аккаунт деактивирован"
        )
    
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Дополнительная проверка на активность аккаунта."""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Неактивный пользователь")
    return current_user


def check_subscription(user: User) -> bool:
    """
    Проверка активной подписки.
    
    Returns:
        True если подписка активна или is_demo=True
    """
    if user.is_demo:
        return True
    
    if user.subscription_end_date is None:
        return False
    
    return user.subscription_end_date > datetime.utcnow()


async def get_current_user_with_subscription(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """Dependency с проверкой подписки."""
    if not check_subscription(current_user):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Подписка истекла. Пожалуйста, продлите подписку."
        )
    return current_user
