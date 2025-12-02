import os
import sqlalchemy as sa
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.types import JSON

# Абсолютный путь к БД из корня проекта, чтобы не зависеть от текущей директории процесса
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
DB_PATH = os.path.join(PROJECT_ROOT, 'orders.db')
# Преобразуем к виду с прямыми слэшами для SQLAlchemy/URI
DB_PATH_URI = DB_PATH.replace(os.sep, '/')
DATABASE_URL = f"sqlite:///{DB_PATH_URI}"

engine = sa.create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, index=True)
    posting_number = Column(String, unique=True, index=True)
    status = Column(String)
    created_at = Column(String)
    updated_at = Column(String)
    data = Column(JSON)

class OrderHeader(Base):
    __tablename__ = "order_headers"
    id = Column(Integer, primary_key=True)
    order_number = Column(String, unique=True, index=True)
    first_created_at = Column(String)
    last_delivery_at = Column(String)
    total_payout = Column(Integer)
    total_commission = Column(Integer)

class OrderPosting(Base):
    __tablename__ = "order_postings"
    id = Column(Integer, primary_key=True)
    order_number = Column(String, index=True)
    posting_number = Column(String, unique=True, index=True)
    status = Column(String)
    created_at = Column(String)
    in_process_at = Column(String)
    fact_delivery_date = Column(String)
    substatus = Column(String)
    analytics_data = Column(JSON)
    financial_data = Column(JSON)

class OrderProduct(Base):
    __tablename__ = "order_products"
    id = Column(Integer, primary_key=True)
    posting_number = Column(String, index=True)
    sku = Column(Integer, index=True)
    offer_id = Column(String, index=True)
    name = Column(String)
    quantity = Column(Integer)
    price = Column(Integer)
    currency_code = Column(String)
    commission_amount = Column(Integer)
    commission_percent = Column(Integer)
    payout = Column(Integer)
    total_discount_value = Column(Integer)
    total_discount_percent = Column(Integer)

class Cost(Base):
    __tablename__ = "costs"
    id = Column(Integer, primary_key=True)
    type = Column(String, index=True)  # COGS, logistics, ads, withdrawal, other
    amount = Column(Integer)
    currency = Column(String, default="RUB")
    date = Column(String, index=True)
    scope_order_number = Column(String, index=True, nullable=True)
    scope_posting_number = Column(String, index=True, nullable=True)
    scope_sku = Column(Integer, index=True, nullable=True)
    scope_offer_id = Column(String, index=True, nullable=True)
    notes = Column(Text)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
