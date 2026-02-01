import os
import sqlalchemy as sa
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.types import JSON
from datetime import datetime

# PostgreSQL connection setup
# Формат: postgresql://user:password@host:port/dbname
# Для asyncpg: postgresql+asyncpg://user:password@host:port/dbname
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://ozonuser:ozonpass@localhost:5432/ozondb"
)

# Для продакшена рекомендуется использовать connection pool
engine = sa.create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # Проверка соединения перед использованием
    pool_size=10,
    max_overflow=20,
    echo=False  # True для отладки SQL-запросов
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    """Модель пользователя для SaaS (мультитенантность)."""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    
    # Зашифрованные Ozon credentials (используйте cryptography.fernet для шифрования)
    ozon_client_id = Column(Text, nullable=True)  # Encrypted
    ozon_api_key = Column(Text, nullable=True)     # Encrypted
    
    # Управление подпиской
    is_demo = Column(Boolean, default=False, nullable=False)
    subscription_end_date = Column(DateTime, nullable=True)
    
    # Метаданные
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationships
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    order_headers = relationship("OrderHeader", back_populates="user", cascade="all, delete-orphan")
    order_postings = relationship("OrderPosting", back_populates="user", cascade="all, delete-orphan")
    costs = relationship("Cost", back_populates="user", cascade="all, delete-orphan")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(Integer, index=True)
    posting_number = Column(String(255), index=True)
    status = Column(String(100))
    created_at = Column(String(100))
    updated_at = Column(String(100))
    data = Column(JSON)
    
    # Relationship
    user = relationship("User", back_populates="orders")
    
    __table_args__ = (
        # Уникальность posting_number только в рамках одного пользователя
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
    
    # Relationship
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
    
    # Relationship
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
    sku = Column(Integer, index=True)
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
    
    # Relationship
    posting = relationship("OrderPosting", back_populates="products")


class Cost(Base):
    __tablename__ = "costs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(50), index=True)  # COGS, logistics, ads, withdrawal, other
    amount = Column(Integer)
    currency = Column(String(10), default="RUB")
    date = Column(String(100), index=True)
    scope_order_number = Column(String(255), index=True, nullable=True)
    scope_posting_number = Column(String(255), index=True, nullable=True)
    scope_sku = Column(Integer, index=True, nullable=True)
    scope_offer_id = Column(String(255), index=True, nullable=True)
    notes = Column(Text)
    
    # Relationship
    user = relationship("User", back_populates="costs")


# НЕ создаем таблицы автоматически! Используйте Alembic для миграций
# Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency для FastAPI endpoints."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Создание всех таблиц (используйте только для первичной инициализации).
    Для продакшена используйте Alembic migrations.
    """
    Base.metadata.create_all(bind=engine)


def get_user_db_session(user_id: int):
    """
    Вспомогательная функция для создания сессии с автоматической фильтрацией по user_id.
    Полезно для изоляции данных пользователей в SaaS.
    """
    db = SessionLocal()
    # В реальном приложении можно добавить Query Filter для автоматической фильтрации
    return db
