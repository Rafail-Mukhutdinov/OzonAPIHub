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

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
