from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
import json
import logging

from db.database import get_db, User, OzonDeliveryMethodMapping, OzonCredential
from utils.auth import get_current_user, verify_not_impersonating
from utils.encryption import decrypt_credential
from services.ozon import ozon_delivery_method_list_async

router = APIRouter(prefix="/delivery-methods", tags=["delivery_methods"])
logger = logging.getLogger("OzonAPIHub")

class MappingCreate(BaseModel):
    delivery_method_id: int
    custom_name: str = Field(..., min_length=1, max_length=255)

    @field_validator('custom_name')
    @classmethod
    def validate_custom_name(cls, v):
        stripped = v.strip()
        if not stripped:
            raise ValueError('Название не может состоять только из пробелов')
        return stripped

class DeliveryMethodResponse(BaseModel):
    id: int
    ozon_name: str
    custom_name: Optional[str] = None
    provider_name: str
    is_active: bool

@router.get("/", response_model=List[DeliveryMethodResponse])
async def list_delivery_methods(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Возвращает список всех методов доставки из Ozon API, 
    совмещенный с пользовательскими маппингами.
    Использует Redis для кеширования справочника на 1 час.
    """
    cache_key = f"ozon_methods_cache:{current_user.id}"
    redis = getattr(request.app.state, "arq_pool", None)
    
    methods_raw = None
    if redis:
        cached = await redis.get(cache_key)
        if cached:
            methods_raw = json.loads(cached)

    if not methods_raw:
        # Загружаем ключи
        cred = db.query(OzonCredential).filter(OzonCredential.user_id == current_user.id, OzonCredential.is_active == True).first()
        if not cred:
            return [] # Нет ключей - нет методов
        
        client_id = decrypt_credential(cred.client_id_encrypted)
        api_key = decrypt_credential(cred.api_key_encrypted)

        # Полный цикл пагинации Ozon API (🔴-4)
        all_methods = []
        limit = 100
        offset = 0
        while True:
            res = await ozon_delivery_method_list_async(client_id, api_key, limit=limit, offset=offset)
            
            # 🟡 Проверка ошибки API
            if res.get("error"):
                logger.error(f"Ozon API error for user {current_user.id}: {res['error']}")
                raise HTTPException(status_code=502, detail=f"Ozon API error: {res['error']}")

            items = res.get("result", [])
            if not items:
                break
            all_methods.extend(items)
            if len(items) < limit:
                break
            offset += limit
        
        methods_raw = all_methods
        # Сохраняем в кеш на 1 час (🔴-2)
        if redis and methods_raw:
            await redis.setex(cache_key, 3600, json.dumps(methods_raw))

    # Получаем маппинги пользователя из БД (одним запросом 🟡-7)
    mappings = db.query(OzonDeliveryMethodMapping).filter(
        OzonDeliveryMethodMapping.user_id == current_user.id
    ).all()
    mapping_dict = {m.delivery_method_id: m.custom_name for m in mappings}

    # Формируем итоговый список
    result = []
    for m in methods_raw:
        m_id = m.get("id")
        result.append(DeliveryMethodResponse(
            id=m_id,
            ozon_name=m.get("name", "Unknown"),
            custom_name=mapping_dict.get(m_id),
            provider_name=m.get("provider_name", "Ozon"),
            is_active=m.get("active", True)
        ))
    
    return result

@router.post("/map", dependencies=[Depends(verify_not_impersonating)])
async def update_mapping(
    data: MappingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Создает или обновляет маппинг для метода доставки (UPSERT)."""
    # 🟡 Безопасность: только current_user.id
    mapping = db.query(OzonDeliveryMethodMapping).filter(
        OzonDeliveryMethodMapping.user_id == current_user.id,
        OzonDeliveryMethodMapping.delivery_method_id == data.delivery_method_id
    ).first()

    if mapping:
        mapping.custom_name = data.custom_name
    else:
        mapping = OzonDeliveryMethodMapping(
            user_id=current_user.id,
            delivery_method_id=data.delivery_method_id,
            custom_name=data.custom_name
        )
        db.add(mapping)
    
    db.commit()
    return {"status": "ok"}

@router.delete("/map/{method_id}", dependencies=[Depends(verify_not_impersonating)])
async def delete_mapping(
    method_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Удаляет маппинг, возвращая стандартное название (🔴-3)."""
    db.query(OzonDeliveryMethodMapping).filter(
        OzonDeliveryMethodMapping.user_id == current_user.id,
        OzonDeliveryMethodMapping.delivery_method_id == method_id
    ).delete()
    db.commit()
    return {"status": "ok"}
