"""
Модуль для работы с базой данных SQLAlchemy.
"""

import os
import sqlalchemy as sa
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, BigInteger, Index
from sqlalchemy.types import JSON
from datetime import datetime, timezone
from utils.common import get_now_utc

def get_utc_now():
    # Используем общую утилиту для единообразия во всем проекте.
    # Возвращает наивный UTC datetime.
    return get_now_utc()

# Настройка подключения
# ВАЖНО: На сервере DATABASE_URL передается через docker-compose
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Please configure DATABASE_URL in environment variables or .env file.")

engine_kwargs = {
    "pool_pre_ping": True,
    "echo": False,
    "pool_recycle": 3600,
    "pool_timeout": 30,
}

# pool_size и max_overflow не поддерживаются в SQLite (используется StaticPool)
if DATABASE_URL.startswith("postgresql"):
    engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
    })

engine = sa.create_engine(DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_demo = Column(Boolean, default=False, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    subscription_end_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=get_utc_now, nullable=False)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(DateTime, nullable=True) # Поле для Soft Delete

    ozon_credentials = relationship("OzonCredential", back_populates="user", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    order_headers = relationship("OrderHeader", back_populates="user", cascade="all, delete-orphan")
    order_postings = relationship("OrderPosting", back_populates="user", cascade="all, delete-orphan")
    costs = relationship("Cost", back_populates="user", cascade="all, delete-orphan")
    product_costs = relationship("ProductCost", back_populates="user", cascade="all, delete-orphan")

class OzonCredential(Base):
    __tablename__ = "ozon_credentials"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    marketplace = Column(String(50), default='ozon', nullable=False)
    name = Column(String(255), nullable=False)
    client_id_encrypted = Column(Text, nullable=False)
    api_key_encrypted = Column(Text, nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=get_utc_now, nullable=False)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)
    user = relationship("User", back_populates="ozon_credentials")
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'name', name='uq_user_credential_name'),
    )

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(BigInteger, index=True)
    posting_number = Column(String(255), index=True)
    scheme = Column(String(20), default='fbo') # Индексируется в составе композитного индекса
    status = Column(String(100))
    created_at = Column(DateTime, index=True)
    updated_at = Column(DateTime, index=True)
    data = Column(JSON)
    user = relationship("User", back_populates="orders")
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'posting_number', name='uq_user_posting'),
        Index('idx_order_user_created', 'user_id', 'created_at'),
        Index('idx_order_scheme_user', 'scheme', 'user_id', 'created_at'),
    )

class OrderHeader(Base):
    __tablename__ = "order_headers"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_number = Column(String(255), index=True)
    first_created_at = Column(DateTime)
    last_delivery_at = Column(DateTime)
    total_payout = Column(Integer)
    total_commission = Column(Integer)
    user = relationship("User", back_populates="order_headers")
    __table_args__ = (sa.UniqueConstraint('user_id', 'order_number', name='uq_user_order_number'),)

class OrderPosting(Base):
    __tablename__ = "order_postings"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_number = Column(String(255), index=True)
    posting_number = Column(String(255), index=True)
    scheme = Column(String(20), default='fbo') # Индексируется в составе композитного индекса
    status = Column(String(100))
    created_at = Column(DateTime, index=True)
    in_process_at = Column(DateTime, index=True)
    fact_delivery_date = Column(DateTime)
    
    # Специфичные поля для FBS / rFBS
    is_express = Column(Boolean, default=False)
    shipment_date = Column(DateTime, index=True)
    tpl_provider = Column(String(255))
    delivery_method_id = Column(BigInteger)
    delivery_method_name = Column(String(255))
    tracking_number = Column(String(255))
    
    substatus = Column(String(100))
    analytics_data = Column(JSON)
    financial_data = Column(JSON)
    user = relationship("User", back_populates="order_postings")
    products = relationship("OrderProduct", back_populates="posting", cascade="all, delete-orphan")
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'posting_number', name='uq_user_posting_number'),
        Index('idx_posting_user_created', 'user_id', 'created_at'),
        Index('idx_posting_user_in_process', 'user_id', 'in_process_at'),
        Index('idx_posting_scheme_user', 'scheme', 'user_id', 'created_at'),
    )

class OrderProduct(Base):
    __tablename__ = "order_products"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    posting_id = Column(Integer, ForeignKey("order_postings.id", ondelete="CASCADE"), nullable=True, index=True)
    posting_number = Column(String(255), index=True)
    sku = Column(BigInteger, index=True)
    offer_id = Column(String(255), index=True)
    name = Column(String(500))
    quantity = Column(Integer)
    price = Column(Integer)
    currency_code = Column(String(10))
    commission_amount = Column(Integer)
    commission_percent = Column(Integer)
    payout = Column(Integer)
    total_discount_value = Column(Integer)
    total_discount_percent = Column(Integer)
    image_url = Column(String(1024), nullable=True)
    posting = relationship("OrderPosting", back_populates="products")

class Cost(Base):
    __tablename__ = "costs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(50), index=True)
    amount = Column(Integer)
    currency = Column(String(10), default="RUB")
    date = Column(DateTime, index=True)
    scope_order_number = Column(String(255), index=True, nullable=True)
    scope_posting_number = Column(String(255), index=True, nullable=True)
    scope_sku = Column(BigInteger, index=True, nullable=True)
    scope_offer_id = Column(String(255), index=True, nullable=True)
    notes = Column(Text)
    user = relationship("User", back_populates="costs")

class ProductCost(Base):
    """
    Таблица для хранения истории себестоимости товаров.
    Позволяет отслеживать изменение себестоимости во времени.
    """
    __tablename__ = "product_costs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    sku = Column(BigInteger, index=True, nullable=False)
    offer_id = Column(String(255), index=True, nullable=True)
    cost_price = Column(sa.Float, nullable=False) # Себестоимость (может быть дробной)
    effective_from = Column(DateTime, index=True, nullable=False) # Дата начала действия этой цены
    created_at = Column(DateTime, default=get_utc_now, nullable=False)
    
    user = relationship("User", back_populates="product_costs")

class OzonAccrual(Base):
    """
    Таблица для хранения детальных транзакций из /v1/finance/accrual/by-day.
    Распаковывает POSTING на доходы и расходы для 100% точности.
    """
    __tablename__ = "ozon_accruals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ozon_accrual_id = Column(BigInteger, index=True) # ID от Ozon (может дублироваться при распаковке)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(DateTime, index=True, nullable=False)
    unit_number = Column(String(255), index=True) 
    accrued_category = Column(String(50), index=True) # POSTING, ITEM, NON_ITEM
    
    # Тип записи: 'revenue' (доход) или 'expense' (списание)
    operation_type = Column(String(20), index=True, default='expense')
    
    amount = Column(sa.Float) # Сумма конкретной части (например, только комиссия)
    quantity = Column(Integer, default=1) # Количество товаров
    currency = Column(String(10))
    
    type_id = Column(Integer, index=True) # ID услуги Озона (74, 32 и т.д.)
    sku = Column(BigInteger, index=True)
    
    posting_id = Column(Integer, ForeignKey("order_postings.id", ondelete="SET NULL"), nullable=True)
    scheme = Column(String(20), default='fbo', index=True)
    created_at = Column(DateTime, default=get_utc_now)
    
    user = relationship("User")
    posting = relationship("OrderPosting")

class AdminActionLog(Base):
    """
    Audit trail действий администратора.
    Логирует все чувствительные операции (impersonation, продление подписки,
    блокировка, очистка данных и т.д.) для соответствия требованиям SaaS / 152-ФЗ.
    """
    __tablename__ = "admin_action_logs"
    id = Column(Integer, primary_key=True, index=True)
    admin_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=False, index=True)
    target_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action_type = Column(String(50), nullable=False, index=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=get_utc_now, nullable=False, index=True)

    admin_user = relationship("User", foreign_keys=[admin_user_id])
    target_user = relationship("User", foreign_keys=[target_user_id])


class SystemSetting(Base):
    """
    Глобальные настройки платформы (key-value): feature flags,
    режим обслуживания, глобальные лимиты и т.д.
    """
    __tablename__ = "system_settings"
    key = Column(String(100), primary_key=True)
    value = Column(JSON, nullable=True)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class SyncStatus(Base):
    __tablename__ = "sync_status"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True, unique=True)
    is_syncing = Column(Boolean, default=False, nullable=False)
    status_message = Column(String(255), default="", nullable=False)
    sync_started_at = Column(DateTime, nullable=True)
    sync_completed_at = Column(DateTime, nullable=True)
    total_records_synced = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)

    # Поля для устойчивого Backfill
    backfill_cursor = Column(DateTime, nullable=True)
    backfill_started_at = Column(DateTime, nullable=True)
    backfill_completed_at = Column(DateTime, nullable=True)
    backfill_from = Column(DateTime, nullable=True)
    backfill_to = Column(DateTime, nullable=True)
    backfill_is_complete = Column(Boolean, default=False, nullable=False)

    # Поля для раздельной синхронизации FBS
    fbs_last_sync_at = Column(DateTime, nullable=True)
    fbs_backfill_cursor = Column(DateTime, nullable=True)
    fbs_backfill_is_complete = Column(Boolean, default=False, nullable=False)
    
    # Чекпоинт для годовой загрузки начислений
    accruals_backfill_cursor = Column(DateTime, nullable=True)

    last_sync_attempt_at = Column(DateTime, nullable=True) # Без onupdate для точности планировщика

    user = relationship("User")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def init_db():
    """
    Инициализация БД. 
    ВАЖНО: Сами таблицы создаются и обновляются через миграции Alembic.
    Здесь могут быть только проверки или начальное заполнение справочников.
    """
    pass
