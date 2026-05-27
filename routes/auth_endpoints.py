"""
Эндпоинты для аутентификации и управления пользователями.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Response, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, field_validator
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

router = APIRouter(prefix="/auth", tags=["authentication"])


# ============================================================================
# Models
# ============================================================================

class UserRegister(BaseModel):
    email: EmailStr
    password: str
    confirm_password: str
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
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
    subscription_end_date: datetime | None
    is_active: bool
    has_credentials: bool
    
    class Config:
        from_attributes = True


class OzonCredentialCreate(BaseModel):
    marketplace: str
    name: str
    client_id: str
    api_key: str


class DataPurgeRequest(BaseModel):
    marketplace: str


class SyncStatusResponse(BaseModel):
    is_syncing: bool
    status_message: str
    total_records_synced: int
    sync_started_at: datetime | None
    sync_completed_at: datetime | None
    
    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    email: EmailStr | None = None


# ============================================================================
# Endpoints
# ============================================================================

@router.options("/register")
def options_register():
    return Response(status_code=200)

@router.options("/login")
def options_login():
    return Response(status_code=200)

@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
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

    logger.info(f"Зарегистрирован новый пользователь: {new_user.email} (ID: {new_user.id})")
    log_user_event(new_user.id, "Аккаунт успешно создан. Начало пробного периода (30 дней).")

    access_token = create_access_token(
        data={"sub": new_user.email},
        expires_delta=timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    return Token(access_token=access_token, token_type="bearer")


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        logger.warning(f"Неудачная попытка входа: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )

    log_user_event(user.id, "Успешный вход в систему.")
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    has_credentials = db.query(OzonCredential).filter(
        OzonCredential.user_id == current_user.id
    ).first() is not None
    
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        is_demo=current_user.is_demo,
        subscription_end_date=current_user.subscription_end_date,
        is_active=current_user.is_active,
        has_credentials=has_credentials
    )


@router.get("/me/ozon-credentials")
def list_ozon_credentials(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    credentials = db.query(OzonCredential).filter(
        OzonCredential.user_id == current_user.id
    ).order_by(OzonCredential.created_at.desc()).all()
    
    result = []
    for cred in credentials:
        client_id = decrypt_credential(cred.client_id_encrypted)
        preview = f"{client_id[:4]}...{client_id[-4:]}" if client_id and len(client_id) > 8 else "****"
        
        result.append({
            "id": cred.id,
            "marketplace": cred.marketplace,
            "name": cred.name,
            "is_active": cred.is_active,
            "created_at": cred.created_at,
            "client_id_preview": preview
        })
    return {"credentials": result}


async def _initial_sync_task(user_id: int):
    from services.sync import initial_backfill_for_user
    from db.database import SessionLocal

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            await initial_backfill_for_user(user, db)
    finally:
        db.close()


@router.post("/me/ozon-credentials", status_code=status.HTTP_201_CREATED)
def create_ozon_credential(
    data: OzonCredentialCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    existing = db.query(OzonCredential).filter(
        OzonCredential.user_id == current_user.id,
        OzonCredential.marketplace == data.marketplace
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Ключи для этого маркетплейса уже существуют")
    
    is_first = db.query(OzonCredential).filter(OzonCredential.user_id == current_user.id).first() is None
    
    credential = OzonCredential(
        user_id=current_user.id,
        marketplace=data.marketplace,
        name=data.name,
        client_id_encrypted=encrypt_credential(data.client_id),
        api_key_encrypted=encrypt_credential(data.api_key),
        is_active=is_first
    )
    
    db.add(credential)
    db.commit()
    db.refresh(credential)

    log_user_event(current_user.id, f"Добавлен новый набор ключей: {data.name} ({data.marketplace})")

    if is_first:
        log_user_event(current_user.id, "Запуск первичной синхронизации для первого набора ключей.")
        background_tasks.add_task(_initial_sync_task, current_user.id)
    
    return {"id": credential.id, "name": credential.name, "is_active": credential.is_active}


@router.put("/me/ozon-credentials/{credential_id}/activate")
def activate_ozon_credential(
    credential_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    credential = db.query(OzonCredential).filter(
        OzonCredential.id == credential_id,
        OzonCredential.user_id == current_user.id
    ).first()
    
    if not credential:
        raise HTTPException(status_code=404, detail="Набор не найден")
    
    db.query(OzonCredential).filter(OzonCredential.user_id == current_user.id).update({"is_active": False})
    credential.is_active = True
    db.commit()

    log_user_event(current_user.id, f"Активирован набор ключей: {credential.name}")
    return {"status": "ok"}


@router.delete("/me/ozon-credentials/{credential_id}")
def delete_ozon_credential(
    credential_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    credential = db.query(OzonCredential).filter(
        OzonCredential.id == credential_id,
        OzonCredential.user_id == current_user.id
    ).first()
    
    if not credential:
        raise HTTPException(status_code=404, detail="Набор не найден")
    
    was_active = credential.is_active
    name = credential.name
    db.delete(credential)
    db.commit()

    log_user_event(current_user.id, f"Удален набор ключей: {name}")

    if was_active:
        next_one = db.query(OzonCredential).filter(OzonCredential.user_id == current_user.id).first()
        if next_one:
            next_one.is_active = True
            db.commit()
            log_user_event(current_user.id, f"Автоматически активирован следующий набор: {next_one.name}")
    return {"status": "ok"}


@router.post("/me/data/purge")
def purge_user_data(
    payload: DataPurgeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.marketplace.lower() != "ozon":
        raise HTTPException(status_code=400, detail="Только Ozon")

    db.query(OrderProduct).filter(OrderProduct.user_id == current_user.id).delete()
    db.query(OrderPosting).filter(OrderPosting.user_id == current_user.id).delete()
    db.query(OrderHeader).filter(OrderHeader.user_id == current_user.id).delete()
    db.query(Order).filter(Order.user_id == current_user.id).delete()
    db.query(Cost).filter(Cost.user_id == current_user.id).delete()
    db.commit()

    log_user_event(current_user.id, "ВНИМАНИЕ: Пользователь инициировал полную очистку данных Ozon.", "warning")
    return {"status": "ok"}


@router.get("/me/sync-status", response_model=SyncStatusResponse)
def get_sync_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    status = db.query(SyncStatus).filter(SyncStatus.user_id == current_user.id).first()
    if not status:
        return SyncStatusResponse(is_syncing=False, status_message="not_started", total_records_synced=0)
    return status
