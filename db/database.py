import os
import sqlalchemy as sa
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, BigInteger
from sqlalchemy.types import JSON
from datetime import datetime, timezone

# Вспомогательная функция для получения текущего UTC времени без TZ-информации (naive),
# так как это стандарт для многих БД и текущего кода проекта.
def get_utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

# Database connection setup
# Используем SQLite для локального тестирования вместо PostgreSQL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./ozon_saas.db"
)

# Если URL всё ещё PostgreSQL, переключаемся на SQLite
if "postgresql" in DATABASE_URL:
    DATABASE_URL = "sqlite:///./ozon_saas.db"

engine = sa.create_engine(
    DATABASE_URL,
    pool_pre_ping=True if not DATABASE_URL.startswith("sqlite") else False,
    pool_size=10 if not DATABASE_URL.startswith("sqlite") else 5,
    max_overflow=20 if not DATABASE_URL.startswith("sqlite") else 10,
    echo=False,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    """Модель пользователя для SaaS (мультитенантность)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)

    # Управление подпиской
    is_demo = Column(Boolean, default=False, nullable=False)
    subscription_end_date = Column(DateTime, nullable=True)

    # Метаданные
    created_at = Column(DateTime, default=get_utc_now, nullable=False)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationships
    ozon_credentials = relationship("OzonCredential", back_populates="user", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    order_headers = relationship("OrderHeader", back_populates="user", cascade="all, delete-orphan")
    order_postings = relationship("OrderPosting", back_populates="user", cascade="all, delete-orphan")
    costs = relationship("Cost", back_populates="user", cascade="all, delete-orphan")


class OzonCredential(Base):
    """Набор API ключей пользователя для различных маркетплейсов."""
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
    status = Column(String(100))
    created_at = Column(String(100))
    updated_at = Column(String(100))
    data = Column(JSON)

    user = relationship("User", back_populates="orders")

    __table_args__ = (
        sa.UniqueConstraint('user_id', 'posting_number', name='uq_user_posting'),
    )


class OrderHeader(Base):
    __tablename__ = "order_headers"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_number = Column(String(255), index=True)
    first_created_at = Column(String(100))
    last_delivery_at = Column(String(100))
    total_payout = Column(Integer)
    total_commission = Column(Integer)

    user = relationship("User", back_populates="order_headers")

    __table_args__ = (
        sa.UniqueConstraint('user_id', 'order_number', name='uq_user_order_number'),
    )


class OrderPosting(Base):
    __tablename__ = "order_postings"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_number = Column(String(255), index=True)
    posting_number = Column(String(255), index=True)
    status = Column(String(100))
    created_at = Column(String(100))
    in_process_at = Column(String(100))
    fact_delivery_date = Column(String(100))
    substatus = Column(String(100))
    analytics_data = Column(JSON)
    financial_data = Column(JSON)

    user = relationship("User", back_populates="order_postings")
    products = relationship("OrderProduct", back_populates="posting", cascade="all, delete-orphan")

    __table_args__ = (
        sa.UniqueConstraint('user_id', 'posting_number', name='uq_user_posting_number'),
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

    posting = relationship("OrderPosting", back_populates="products")


class Cost(Base):
    __tablename__ = "costs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(50), index=True)
    amount = Column(Integer)
    currency = Column(String(10), default="RUB")
    date = Column(String(100), index=True)
    scope_order_number = Column(String(255), index=True, nullable=True)
    scope_posting_number = Column(String(255), index=True, nullable=True)
    scope_sku = Column(BigInteger, index=True, nullable=True)
    scope_offer_id = Column(String(255), index=True, nullable=True)
    notes = Column(Text)

    user = relationship("User", back_populates="costs")


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

    user = relationship("User")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
