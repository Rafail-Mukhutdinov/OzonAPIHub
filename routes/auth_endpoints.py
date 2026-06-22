"""
Эндпоинты для аутентификации и управления пользователями.
Включает регистрацию, логин, управление API-ключами Ozon и профилем.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Response, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, field_validator, Field, AliasChoices, ConfigDict
from datetime import datetime, timedelta, timezone
from db.database import get_db, User, OzonCredential, Order, OrderPosting, OrderProduct, OrderHeader, Cost, SyncStatus
from utils.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    get_password_hash,
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
)
from utils.encryption import encrypt_credential, decrypt_credential
from utils.logging_config import log_user_event, logger
from utils.rate_limiter import limiter
from fastapi import Request

router = APIRouter(prefix="/auth", tags=["authentication"])

# ============================================================================
# Pydantic Модели (Схемы данных)
# ============================================================================

class OzonCredentialCreate(BaseModel):
    """Данные для добавления новых API-ключей Ozon."""
    model_config = ConfigDict(populate_by_name=True)
    
    marketplace: str = "ozon"
    name: str = "Основной магазин"
    # Поддерживаем два варианта именования полей для совместимости с фронтендом
    client_id: str = Field(..., validation_alias=AliasChoices("client_id", "ozon_client_id"))
    api_key: str = Field(..., validation_alias=AliasChoices("api_key", "ozon_api_key"))


class UserRegister(BaseModel):
    """Схема данных для регистрации нового пользователя."""
    email: EmailStr
    password: str
    confirm_password: str
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        if len(v.encode('utf-8')) > 72:
            raise ValueError('Пароль слишком длинный')
        if len(v) < 6:
            raise ValueError('Минимум 6 символов')
        return v


class UserLogin(BaseModel):
    """Схема для входа по email и паролю."""
    email: EmailStr
    password: str


class Token(BaseModel):
    """Ответ сервера с JWT токеном."""
    access_token: str
    token_type: str


class UserResponse(BaseModel):
    """Данные профиля пользователя для фронтенда."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    email: str
    is_demo: bool
    subscription_end_date: datetime | None
    is_active: bool
    has_credentials: bool


class DataPurgeRequest(BaseModel):
    """Запрос на полную очистку данных."""
    marketplace: str


class SyncStatusResponse(BaseModel):
    """Статус текущей синхронизации."""
    model_config = ConfigDict(from_attributes=True)
    
    is_syncing: bool
    status_message: str
    total_records_synced: int
    sync_started_at: datetime | None
    sync_completed_at: datetime | None

    # Поля Backfill
    backfill_cursor: datetime | None = None
    backfill_started_at: datetime | None = None
    backfill_completed_at: datetime | None = None
    backfill_from: datetime | None = None
    backfill_to: datetime | None = None
    backfill_is_complete: bool = False


# ============================================================================
# Эндпоинты (Маршруты API)
# ============================================================================

@router.options("/ozon-credentials")
@router.options("/me/ozon-credentials")
@router.options("/register")
@router.options("/login")
def options_handler():
    """Обработчик preflight-запросов CORS."""
    return Response(status_code=200)

@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, user_data: UserRegister, db: Session = Depends(get_db)):
    """Регистрация нового пользователя и выдача пробного периода."""
    if user_data.password != user_data.confirm_password:
        raise HTTPException(status_code=400, detail="Пароли не совпадают")

    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email уже зарегистрирован")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    new_user = User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        is_demo=True,
        subscription_end_date=now + timedelta(days=30),
        is_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    log_user_event(new_user.id, "Аккаунт успешно создан.")
    return Token(access_token=create_access_token(data={"sub": new_user.email}), token_type="bearer")


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Авторизация пользователя (выдача JWT токена)."""
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Неверный email или пароль")

    log_user_event(user.id, "Успешный вход в систему.")
    return {"access_token": create_access_token(data={"sub": user.email}), "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Возвращает информацию о текущем авторизованном пользователе."""
    has_creds = db.query(OzonCredential).filter(OzonCredential.user_id == current_user.id).first() is not None
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        is_demo=current_user.is_demo,
        subscription_end_date=current_user.subscription_end_date,
        is_active=current_user.is_active,
        has_credentials=has_creds
    )


@router.get("/me/ozon-credentials")
def list_ozon_credentials(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Возвращает список всех подключенных API-ключей пользователя."""
    credentials = db.query(OzonCredential).filter(OzonCredential.user_id == current_user.id).all()
    return {"credentials": [{
        "id": c.id,
        "marketplace": c.marketplace,
        "name": c.name,
        "is_active": c.is_active,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "client_id_preview": f"{decrypt_credential(c.client_id_encrypted)[:4]}..." if c.client_id_encrypted else "****"
    } for c in credentials]}


async def _initial_sync_task(user_id: int):
    """Фоновая задача для запуска первичной синхронизации."""
    from services.sync import initial_backfill_for_user
    from db.database import SessionLocal
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user: await initial_backfill_for_user(user, db)
    finally: db.close()


@router.post("/me/ozon-credentials", status_code=status.HTTP_201_CREATED)
async def create_ozon_credential(
    request: Request,
    data: OzonCredentialCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Добавляет новый набор API-ключей Ozon или обновляет существующий по имени."""
    try:
        # Ищем существующий набор ключей по имени в рамках этого пользователя
        existing = db.query(OzonCredential).filter(
            OzonCredential.user_id == current_user.id,
            OzonCredential.name == data.name
        ).first()

        if existing:
            # Обновляем существующий магазин
            existing.client_id_encrypted = encrypt_credential(data.client_id)
            existing.api_key_encrypted = encrypt_credential(data.api_key)
            existing.marketplace = data.marketplace
            db.commit()
            log_user_event(current_user.id, f"Ключи для магазина '{data.name}' обновлены.")
            return {"status": "updated"}

        # Деактивируем все остальные ключи этого пользователя перед добавлением новых
        db.query(OzonCredential).filter(OzonCredential.user_id == current_user.id).update(
            {OzonCredential.is_active: False}
        )
        
        new_cred = OzonCredential(
            user_id=current_user.id,
            marketplace=data.marketplace,
            name=data.name,
            client_id_encrypted=encrypt_credential(data.client_id),
            api_key_encrypted=encrypt_credential(data.api_key),
            is_active=True
        )
        db.add(new_cred)
        db.commit()

        log_user_event(current_user.id, f"Добавлен новый магазин: {data.name}")

        # Запускаем первичную синхронизацию через воркер (Redis), а не локально
        if hasattr(request.app.state, "arq_pool"):
            await request.app.state.arq_pool.enqueue_job("initial_backfill_task", current_user.id)

        return {"status": "created"}

    except Exception as e:
        db.rollback()
        logger.error(f"Error adding credentials: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/me/ozon-credentials/{credential_id}/activate")
def activate_ozon_credential(credential_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Делает выбранный магазин активным."""
    db.query(OzonCredential).filter(OzonCredential.user_id == current_user.id).update({OzonCredential.is_active: False})
    db.query(OzonCredential).filter(OzonCredential.id == credential_id, OzonCredential.user_id == current_user.id).update({OzonCredential.is_active: True})
    db.commit()
    log_user_event(current_user.id, "Магазин переключен.")
    return {"status": "ok"}


@router.delete("/me/ozon-credentials/{credential_id}")
def delete_ozon_credential(credential_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Удаляет ключи магазина."""
    db.query(OzonCredential).filter(OzonCredential.id == credential_id, OzonCredential.user_id == current_user.id).delete()
    db.commit()
    return {"status": "ok"}


@router.post("/me/data/purge")
def purge_user_data(payload: DataPurgeRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Полная очистка данных пользователя."""
    db.query(OrderProduct).filter(OrderProduct.user_id == current_user.id).delete()
    db.query(OrderPosting).filter(OrderPosting.user_id == current_user.id).delete()
    db.query(OrderHeader).filter(OrderHeader.user_id == current_user.id).delete()
    db.query(Order).filter(Order.user_id == current_user.id).delete()
    db.query(Cost).filter(Cost.user_id == current_user.id).delete()
    db.commit()
    log_user_event(current_user.id, "ВНИМАНИЕ: Все данные маркетплейса удалены пользователем.", "warning")
    return {"status": "ok"}


@router.get("/me/sync-status", response_model=SyncStatusResponse)
def get_sync_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Возвращает статус текущей фоновой синхронизации."""
    status = db.query(SyncStatus).filter(SyncStatus.user_id == current_user.id).first()
    if not status:
        return {"is_syncing": False, "status_message": "not_started", "total_records_synced": 0}
    return status
