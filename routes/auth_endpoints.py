"""
Эндпоинты для аутентификации и управления пользователями.

Endpoints:
- POST /auth/register - регистрация
- POST /auth/login - вход (получение токена)
- GET /auth/me - информация о текущем пользователе
- PUT /auth/me - обновление профиля
- PUT /auth/me/ozon-credentials - обновление Ozon API ключей
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, field_validator
from datetime import timedelta
from db.database import get_db, User
from utils.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    get_password_hash,
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
)
from utils.encryption import encrypt_credential, decrypt_credential

router = APIRouter(prefix="/auth", tags=["authentication"])


# ============================================================================
# Request/Response Models
# ============================================================================

class UserRegister(BaseModel):
    email: EmailStr
    password: str
    confirm_password: str
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        """Проверяем что пароль не превышает 72 байта (ограничение bcrypt)"""
        if len(v.encode('utf-8')) > 72:
            raise ValueError('Пароль слишком длинный (максимум 72 байта)')
        if len(v) < 6:
            raise ValueError('Пароль должен содержать минимум 6 символов')
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class UserResponse(BaseModel):
    id: int
    email: str
    is_demo: bool
    subscription_end_date: str | None
    is_active: bool
    ozon_configured: bool  # True если credentials установлены
    
    class Config:
        from_attributes = True


class OzonCredentialsUpdate(BaseModel):
    client_id: str
    api_key: str


class ProfileUpdate(BaseModel):
    email: EmailStr | None = None


# ============================================================================
# Endpoints
# ============================================================================

# Явные OPTIONS обработчики для CORS preflight
@router.options("/register")
async def options_register():
    """CORS preflight для регистрации"""
    return {}

@router.options("/login")
async def options_login():
    """CORS preflight для входа"""
    return {}

@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """
    Регистрация нового пользователя.
    
    - Проверяет уникальность email
    - Создает пользователя с is_demo=True (30 дней trial)
    - Возвращает JWT токен для автоматического входа
    """
    # Проверка совпадения паролей
    if user_data.password != user_data.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пароли не совпадают"
        )
    
    # Проверка существования email
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email уже зарегистрирован"
        )
    
    # Создание пользователя
    from datetime import datetime, timedelta
    new_user = User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        is_demo=True,
        subscription_end_date=datetime.utcnow() + timedelta(days=30),  # 30 дней trial
        is_active=True
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Создаем токен для автоматического входа после регистрации
    access_token = create_access_token(
        data={"sub": str(new_user.id)},
        expires_delta=timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    return Token(access_token=access_token, token_type="bearer")


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Вход в систему (получение JWT токена).
    
    - Проверяет email и пароль
    - Возвращает access_token для использования в заголовке Authorization
    
    Использование токена:
        Authorization: Bearer <access_token>
    """
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Получение информации о текущем пользователе."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        is_demo=current_user.is_demo,
        subscription_end_date=current_user.subscription_end_date.isoformat() if current_user.subscription_end_date else None,
        is_active=current_user.is_active,
        ozon_configured=bool(current_user.ozon_client_id and current_user.ozon_api_key)
    )


@router.put("/me/ozon-credentials", status_code=status.HTTP_200_OK)
async def update_ozon_credentials(
    credentials: OzonCredentialsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Обновление Ozon API credentials.
    
    - Шифрует Client ID и API Key перед сохранением
    - Позволяет каждому пользователю использовать свой Ozon аккаунт
    """
    current_user.ozon_client_id = encrypt_credential(credentials.client_id)
    current_user.ozon_api_key = encrypt_credential(credentials.api_key)
    
    db.commit()
    
    return {
        "status": "ok",
        "message": "Ozon credentials успешно обновлены"
    }


@router.get("/me/ozon-credentials/test")
async def test_ozon_credentials(
    current_user: User = Depends(get_current_user)
):
    """
    Проверка расшифровки Ozon credentials (для отладки).
    
    ⚠️ УДАЛИТЕ этот endpoint в продакшене!
    """
    if not current_user.ozon_client_id or not current_user.ozon_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ozon credentials не настроены"
        )
    
    # Расшифровка для проверки
    client_id = decrypt_credential(current_user.ozon_client_id)
    api_key = decrypt_credential(current_user.ozon_api_key)
    
    # Показываем только первые/последние символы для безопасности
    return {
        "client_id_preview": f"{client_id[:4]}...{client_id[-4:]}" if client_id else None,
        "api_key_preview": f"{api_key[:8]}...{api_key[-4:]}" if api_key else None,
        "configured": True
    }


@router.put("/me", response_model=UserResponse)
async def update_profile(
    profile: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Обновление профиля пользователя."""
    if profile.email:
        # Проверка уникальности нового email
        existing = db.query(User).filter(
            User.email == profile.email,
            User.id != current_user.id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email уже используется"
            )
        current_user.email = profile.email
    
    db.commit()
    db.refresh(current_user)
    
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        is_demo=current_user.is_demo,
        subscription_end_date=current_user.subscription_end_date.isoformat() if current_user.subscription_end_date else None,
        is_active=current_user.is_active,
        ozon_configured=bool(current_user.ozon_client_id and current_user.ozon_api_key)
    )
