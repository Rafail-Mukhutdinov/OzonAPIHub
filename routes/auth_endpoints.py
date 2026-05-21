"""
Эндпоинты для аутентификации и управления пользователями.

Endpoints:
- POST /auth/register - регистрация
- POST /auth/login - вход (получение токена)
- GET /auth/me - информация о текущем пользователе
- PUT /auth/me - обновление профиля
- GET /auth/me/ozon-credentials - список API ключей
- POST /auth/me/ozon-credentials - создание нового набора ключей
- PUT /auth/me/ozon-credentials/{id}/activate - активация набора
- DELETE /auth/me/ozon-credentials/{id} - удаление набора
- POST /auth/me/data/purge - очистка данных по маркетплейсу
"""

from fastapi import APIRouter, Depends, HTTPException, status, Response, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, field_validator
from datetime import timedelta
from db.database import get_db, User, OzonCredential, Order, OrderPosting, OrderProduct, OrderHeader, Cost, SyncStatus
import asyncio
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
    has_credentials: bool  # True если есть хотя бы один набор ключей
    
    class Config:
        from_attributes = True


class OzonCredentialCreate(BaseModel):
    marketplace: str  # 'ozon', 'wildberries', 'yandex', и т.д.
    name: str
    client_id: str
    api_key: str


class DataPurgeRequest(BaseModel):
    marketplace: str


class SyncStatusResponse(BaseModel):
    is_syncing: bool
    status_message: str
    total_records_synced: int
    sync_started_at: str | None
    sync_completed_at: str | None
    
    class Config:
        from_attributes = True


class OzonCredentialResponse(BaseModel):
    id: int
    marketplace: str
    name: str
    is_active: bool
    created_at: str
    client_id_preview: str  # Только первые/последние символы
    
    class Config:
        from_attributes = True


class OzonCredentialsUpdate(BaseModel):
    marketplace: str | None = None  # Может быть обновлено
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
    return Response(status_code=200)

@router.options("/login")
async def options_login():
    """CORS preflight для входа"""
    return Response(status_code=200)

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
        data={"sub": new_user.email},
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
async def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение информации о текущем пользователе."""
    # Проверяем наличие хотя бы одного набора ключей
    has_credentials = db.query(OzonCredential).filter(
        OzonCredential.user_id == current_user.id
    ).first() is not None
    
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        is_demo=current_user.is_demo,
        subscription_end_date=current_user.subscription_end_date.isoformat() if current_user.subscription_end_date else None,
        is_active=current_user.is_active,
        has_credentials=has_credentials
    )


@router.get("/me/ozon-credentials")
async def list_ozon_credentials(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получить список всех наборов API ключей пользователя."""
    credentials = db.query(OzonCredential).filter(
        OzonCredential.user_id == current_user.id
    ).order_by(OzonCredential.created_at.desc()).all()
    
    result = []
    for cred in credentials:
        # Расшифровываем только для preview
        client_id = decrypt_credential(cred.client_id_encrypted)
        preview = f"{client_id[:4]}...{client_id[-4:]}" if client_id and len(client_id) > 8 else "****"
        
        result.append({
            "id": cred.id,
            "marketplace": cred.marketplace,
            "name": cred.name,
            "is_active": cred.is_active,
            "created_at": cred.created_at.isoformat(),
            "client_id_preview": preview
        })
    
    return {"credentials": result}


async def _initial_sync_for_new_credential(user_id: int, credential_id: int):
    """Фоновая задача: начальная загрузка данных при добавлении credentials."""
    from services.sync import initial_backfill_for_user
    from db.database import SessionLocal, User

    logger.info(f"Запуск начальной синхронизации для user_id={user_id}, credential_id={credential_id}")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            await initial_backfill_for_user(user, db)
            logger.info(f"Начальная синхронизация завершена для user_id={user_id}")
    except Exception as e:
        logger.error(f"Ошибка начальной синхронизации для user_id={user_id}: {e}")
    finally:
        db.close()


@router.post("/me/ozon-credentials", status_code=status.HTTP_201_CREATED)
async def create_ozon_credential(
    data: OzonCredentialCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Создать новый набор API ключей.
    
    - Проверяет дублей по маркетплейсу
    - Шифрует Client ID и API Key
    - Если это первый набор, автоматически делает его активным
    """
    # Проверка: нет ли уже ключей для этого маркетплейса
    existing_marketplace = db.query(OzonCredential).filter(
        OzonCredential.user_id == current_user.id,
        OzonCredential.marketplace == data.marketplace
    ).first()
    
    if existing_marketplace:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ключи для маркетплейса '{data.marketplace}' уже существуют. Удалите старые или используйте другой маркетплейс."
        )
    
    # Проверка уникальности названия
    existing_name = db.query(OzonCredential).filter(
        OzonCredential.user_id == current_user.id,
        OzonCredential.name == data.name
    ).first()
    
    if existing_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Набор с названием '{data.name}' уже существует"
        )
    
    # Проверяем, первый ли это набор
    is_first = db.query(OzonCredential).filter(
        OzonCredential.user_id == current_user.id
    ).first() is None
    
    # Создаем новый набор
    credential = OzonCredential(
        user_id=current_user.id,
        marketplace=data.marketplace,
        name=data.name,
        client_id_encrypted=encrypt_credential(data.client_id),
        api_key_encrypted=encrypt_credential(data.api_key),
        is_active=is_first  # Первый набор активируется автоматически
    )
    
    db.add(credential)
    db.commit()
    db.refresh(credential)
    
    # Запускаем фоновую синхронизацию для загрузки данных
    existing_orders = db.query(Order).filter(Order.user_id == current_user.id).count()
    if is_first or existing_orders == 0:
        background_tasks.add_task(_initial_sync_for_new_credential, current_user.id, credential.id)
    
    return {
        "id": credential.id,
        "name": credential.name,
        "is_active": credential.is_active,
        "message": "Набор ключей успешно создан" + (" и активирован" if is_first else "") + (" (синхронизация запущена)" if is_first else "")
    }


@router.put("/me/ozon-credentials/{credential_id}/activate")
async def activate_ozon_credential(
    credential_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Активировать набор ключей (деактивирует все остальные)."""
    # Проверяем что набор принадлежит пользователю
    credential = db.query(OzonCredential).filter(
        OzonCredential.id == credential_id,
        OzonCredential.user_id == current_user.id
    ).first()
    
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Набор ключей не найден"
        )
    
    # Деактивируем все наборы пользователя
    db.query(OzonCredential).filter(
        OzonCredential.user_id == current_user.id
    ).update({"is_active": False})
    
    # Активируем выбранный
    credential.is_active = True
    db.commit()
    
    return {
        "status": "ok",
        "message": f"Набор '{credential.name}' активирован"
    }


@router.delete("/me/ozon-credentials/{credential_id}")
async def delete_ozon_credential(
    credential_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Удалить набор ключей."""
    credential = db.query(OzonCredential).filter(
        OzonCredential.id == credential_id,
        OzonCredential.user_id == current_user.id
    ).first()
    
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Набор ключей не найден"
        )
    
    was_active = credential.is_active
    credential_name = credential.name
    
    db.delete(credential)
    db.commit()
    
    # Если удалили активный, активируем первый доступный
    if was_active:
        first_available = db.query(OzonCredential).filter(
            OzonCredential.user_id == current_user.id
        ).first()
        
        if first_available:
            first_available.is_active = True
            db.commit()

    return {
        "status": "ok",
        "message": f"Набор '{credential_name}' удален"
    }


@router.post("/me/data/purge")
async def purge_user_data(
    payload: DataPurgeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Очистить данные пользователя по выбранному маркетплейсу."""
    marketplace = (payload.marketplace or "").strip().lower()
    if marketplace != "ozon":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Очистка доступна только для Ozon",
        )

    counts = {
        "order_products": db.query(OrderProduct).filter(OrderProduct.user_id == current_user.id).count(),
        "order_postings": db.query(OrderPosting).filter(OrderPosting.user_id == current_user.id).count(),
        "order_headers": db.query(OrderHeader).filter(OrderHeader.user_id == current_user.id).count(),
        "orders": db.query(Order).filter(Order.user_id == current_user.id).count(),
        "costs": db.query(Cost).filter(Cost.user_id == current_user.id).count(),
    }

    db.query(OrderProduct).filter(OrderProduct.user_id == current_user.id).delete(synchronize_session=False)
    db.query(OrderPosting).filter(OrderPosting.user_id == current_user.id).delete(synchronize_session=False)
    db.query(OrderHeader).filter(OrderHeader.user_id == current_user.id).delete(synchronize_session=False)
    db.query(Order).filter(Order.user_id == current_user.id).delete(synchronize_session=False)
    db.query(Cost).filter(Cost.user_id == current_user.id).delete(synchronize_session=False)
    db.commit()

    return {
        "status": "ok",
        "message": "Данные очищены",
        "marketplace": marketplace,
        "deleted": counts,
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
    
    # Проверяем наличие credentials
    has_credentials = db.query(OzonCredential).filter(
        OzonCredential.user_id == current_user.id
    ).first() is not None
    
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        is_demo=current_user.is_demo,
        subscription_end_date=current_user.subscription_end_date.isoformat() if current_user.subscription_end_date else None,
        is_active=current_user.is_active,
        has_credentials=has_credentials
    )


@router.get("/me/sync-status", response_model=SyncStatusResponse)
async def get_sync_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получить статус синхронизации данных для текущего пользователя.
    Используется только для отслеживания полной скачки (backfill).
    Периодические обновления по таймеру НЕ меняют этот статус.
    """
    sync_status = db.query(SyncStatus).filter(
        SyncStatus.user_id == current_user.id
    ).first()
    
    if not sync_status:
        # Если записи нет, создаем дефолтную
        sync_status = SyncStatus(
            user_id=current_user.id,
            is_syncing=False,
            status_message="Данные не загружены"
        )
        db.add(sync_status)
        db.commit()
        db.refresh(sync_status)
    
    return SyncStatusResponse(
        is_syncing=sync_status.is_syncing,
        status_message=sync_status.status_message,
        total_records_synced=sync_status.total_records_synced,
        sync_started_at=sync_status.sync_started_at.isoformat() + 'Z' if sync_status.sync_started_at else None,
        sync_completed_at=sync_status.sync_completed_at.isoformat() + 'Z' if sync_status.sync_completed_at else None
    )
