"""
Модуль для работы с базой данных SQLAlchemy.
Определяет модели данных, настройки подключения и вспомогательные функции для работы с сессиями.
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
    """
    Возвращает текущую дату и время в формате UTC.
    Использует общую утилиту для единообразия во всем проекте.
    
    Returns:
        datetime: Текущее время UTC (naive).
    """
    return get_now_utc()

# Настройка подключения
# ВАЖНО: На сервере DATABASE_URL передается через docker-compose
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Please configure DATABASE_URL in environment variables or .env file.")

# Параметры пула соединений
engine_kwargs = {
    "pool_pre_ping": True, # Проверка активности соединения перед использованием
    "echo": False,         # Логирование всех SQL-запросов (отключено)
    "pool_recycle": 3600,  # Пересоздание соединений каждый час
    "pool_timeout": 30,    # Таймаут ожидания свободного соединения
}

# pool_size и max_overflow не поддерживаются в SQLite (используется StaticPool)
if DATABASE_URL.startswith("postgresql"):
    engine_kwargs.update({
        "pool_size": 10,     # Базовое количество соединений в пуле
        "max_overflow": 20,  # Максимальное количество дополнительных соединений
    })

engine = sa.create_engine(DATABASE_URL, **engine_kwargs)

# Фабрика сессий для взаимодействия с БД
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# Базовый класс для всех моделей
Base = declarative_base()

class User(Base):
    """
    Модель пользователя системы.
    Хранит учетные данные, настройки подписки и связи с данными маркетплейсов.
    """
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_demo = Column(Boolean, default=False, nullable=False) # Флаг демо-режима
    is_admin = Column(Boolean, default=False, nullable=False) # Флаг администратора
    subscription_end_date = Column(DateTime, nullable=True) # Дата окончания подписки
    created_at = Column(DateTime, default=get_utc_now, nullable=False)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(DateTime, nullable=True) # Поле для Soft Delete (логическое удаление)

    # Связи с другими таблицами
    ozon_credentials = relationship("OzonCredential", back_populates="user", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    order_headers = relationship("OrderHeader", back_populates="user", cascade="all, delete-orphan")
    order_postings = relationship("OrderPosting", back_populates="user", cascade="all, delete-orphan")
    costs = relationship("Cost", back_populates="user", cascade="all, delete-orphan")
    product_costs = relationship("ProductCost", back_populates="user", cascade="all, delete-orphan")

class OzonCredential(Base):
    """
    Модель API-ключей Ozon.
    Хранит зашифрованные Client-Id и Api-Key для доступа к данным конкретного кабинета продавца.
    """
    __tablename__ = "ozon_credentials"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    marketplace = Column(String(50), default='ozon', nullable=False)
    name = Column(String(255), nullable=False) # Название кабинета (для удобства пользователя)
    client_id_encrypted = Column(Text, nullable=False) # Зашифрованный Client ID
    api_key_encrypted = Column(Text, nullable=False) # Зашифрованный API Key
    is_active = Column(Boolean, default=False, nullable=False) # Активен ли ключ в данный момент
    created_at = Column(DateTime, default=get_utc_now, nullable=False)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)
    
    user = relationship("User", back_populates="ozon_credentials")
    
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'name', name='uq_user_credential_name'),
    )

class Order(Base):
    """
    Модель сырых данных заказа (постинга).
    Хранит JSON-ответ от Ozon API и базовые поля для быстрой фильтрации.
    """
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(BigInteger, index=True) # Внутренний ID заказа Ozon
    posting_number = Column(String(255), index=True) # Номер отправления (уникален)
    scheme = Column(String(20), default='fbo') # Схема работы: fbo, fbs, rfbs
    status = Column(String(100)) # Статус отправления
    created_at = Column(DateTime, index=True) # Дата создания отправления
    updated_at = Column(DateTime, index=True) # Дата последнего обновления в нашей системе
    data = Column(JSON) # Полный JSON-объект от API Ozon
    
    user = relationship("User", back_populates="orders")
    
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'posting_number', name='uq_user_posting'),
        Index('idx_order_user_created', 'user_id', 'created_at'),
        Index('idx_order_scheme_user', 'scheme', 'user_id', 'created_at'),
    )

class OrderHeader(Base):
    """
    Модель агрегированного заголовка заказа.
    Объединяет несколько отправлений (postings) одного заказа для отображения общей суммы.
    """
    __tablename__ = "order_headers"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_number = Column(String(255), index=True) # Номер заказа (может содержать несколько отправлений)
    first_created_at = Column(DateTime) # Дата самого первого отправления в заказе
    last_delivery_at = Column(DateTime) # Дата последней доставки по заказу
    total_payout = Column(Integer) # Общая сумма к выплате по всем товарам заказа
    total_commission = Column(Integer) # Общая сумма комиссии по всем товарам заказа
    
    user = relationship("User", back_populates="order_headers")
    
    __table_args__ = (sa.UniqueConstraint('user_id', 'order_number', name='uq_user_order_number'),)

class OrderPosting(Base):
    """
    Модель детализированного отправления.
    Содержит расширенную информацию о логистике, финансовых транзакциях и статусах.
    """
    __tablename__ = "order_postings"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_number = Column(String(255), index=True)
    posting_number = Column(String(255), index=True)
    scheme = Column(String(20), default='fbo')
    status = Column(String(100))
    created_at = Column(DateTime, index=True)
    in_process_at = Column(DateTime, index=True) # Когда начали собирать
    fact_delivery_date = Column(DateTime) # Фактическая дата доставки
    
    # Специфичные поля для FBS / rFBS
    is_express = Column(Boolean, default=False) # Флаг экспресс-доставки
    shipment_date = Column(DateTime, index=True) # Ожидаемая дата отгрузки
    tpl_provider = Column(String(255)) # Курьерская служба (для rFBS)
    delivery_method_id = Column(BigInteger)
    delivery_method_name = Column(String(255))
    tracking_number = Column(String(255)) # Трек-номер для отслеживания
    
    substatus = Column(String(100)) # Подстатус заказа
    analytics_data = Column(JSON) # Данные аналитики из API
    financial_data = Column(JSON) # Финансовые данные (выплаты, комиссии)
    
    user = relationship("User", back_populates="order_postings")
    products = relationship("OrderProduct", back_populates="posting", cascade="all, delete-orphan")
    
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'posting_number', name='uq_user_posting_number'),
        Index('idx_posting_user_created', 'user_id', 'created_at'),
        Index('idx_posting_user_in_process', 'user_id', 'in_process_at'),
        Index('idx_posting_scheme_user', 'scheme', 'user_id', 'created_at'),
    )

class OrderProduct(Base):
    """
    Модель товара внутри отправления.
    Хранит информацию о цене, комиссиях, количестве и SKU.
    """
    __tablename__ = "order_products"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    posting_id = Column(Integer, ForeignKey("order_postings.id", ondelete="CASCADE"), nullable=True, index=True)
    posting_number = Column(String(255), index=True)
    sku = Column(BigInteger, index=True) # Идентификатор товара в Ozon
    offer_id = Column(String(255), index=True) # Артикул продавца
    name = Column(String(500)) # Название товара
    quantity = Column(Integer) # Количество
    price = Column(Integer) # Цена продажи за единицу
    currency_code = Column(String(10)) # Код валюты (RUB)
    commission_amount = Column(Integer) # Сумма комиссии Ozon
    commission_percent = Column(Integer) # Процент комиссии
    payout = Column(Integer) # Чистая выплата продавцу (цена - комиссия)
    total_discount_value = Column(Integer) # Скидка в рублях
    total_discount_percent = Column(Integer) # Скидка в процентах
    image_url = Column(String(1024), nullable=True) # Ссылка на изображение товара
    
    posting = relationship("OrderPosting", back_populates="products")

class Cost(Base):
    """
    Модель дополнительных расходов.
    Хранит рекламные расходы, логистику, хранение и прочие списания.
    Может быть привязана к конкретному заказу или товару.
    """
    __tablename__ = "costs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(50), index=True) # Тип расхода: advertising, storage, logistics, other
    amount = Column(Integer) # Сумма расхода
    currency = Column(String(10), default="RUB")
    date = Column(DateTime, index=True) # Дата списания
    scope_order_number = Column(String(255), index=True, nullable=True)
    scope_posting_number = Column(String(255), index=True, nullable=True)
    scope_sku = Column(BigInteger, index=True, nullable=True)
    scope_offer_id = Column(String(255), index=True, nullable=True)
    notes = Column(Text) # Пояснения или ID транзакции Ozon
    
    user = relationship("User", back_populates="costs")

class ProductCost(Base):
    """
    Таблица для хранения истории себестоимости товаров.
    Позволяет отслеживать изменение себестоимости во времени для точного расчета прибыли.
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
    Распаковывает POSTING на отдельные доходы и расходы для 100% точности учета.
    """
    __tablename__ = "ozon_accruals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ozon_accrual_id = Column(BigInteger, index=True) # Внутренний ID транзакции от Ozon
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(DateTime, index=True, nullable=False) # Дата транзакции
    unit_number = Column(String(255), index=True) # Номер отправления или услуги
    accrued_category = Column(String(50), index=True) # Категория: POSTING, ITEM, NON_ITEM
    
    # Тип записи: 'revenue' (доход) или 'expense' (списание)
    operation_type = Column(String(20), index=True, default='expense')
    
    amount = Column(sa.Float) # Сумма конкретной части (например, только комиссия за продажу)
    quantity = Column(Integer, default=1) # Количество товаров в транзакции
    currency = Column(String(10))
    
    type_id = Column(Integer, index=True) # ID типа услуги Озона (например, 74 - логистика)
    sku = Column(BigInteger, index=True)
    
    posting_id = Column(Integer, ForeignKey("order_postings.id", ondelete="SET NULL"), nullable=True)
    scheme = Column(String(20), default='fbo', index=True)
    created_at = Column(DateTime, default=get_utc_now)
    
    user = relationship("User")
    posting = relationship("OrderPosting")

class AdminActionLog(Base):
    """
    Журнал действий администратора (Audit Trail).
    Логирует чувствительные операции для обеспечения безопасности и аудита.
    """
    __tablename__ = "admin_action_logs"
    id = Column(Integer, primary_key=True, index=True)
    admin_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=False, index=True)
    target_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action_type = Column(String(50), nullable=False, index=True) # Тип действия: impersonation, sub_extend и т.д.
    details = Column(JSON, nullable=True) # Дополнительные детали в JSON
    created_at = Column(DateTime, default=get_utc_now, nullable=False, index=True)

    admin_user = relationship("User", foreign_keys=[admin_user_id])
    target_user = relationship("User", foreign_keys=[target_user_id])


class SystemSetting(Base):
    """
    Глобальные настройки платформы (Key-Value).
    Хранит флаги функций, режимы обслуживания и глобальные лимиты.
    """
    __tablename__ = "system_settings"
    key = Column(String(100), primary_key=True)
    value = Column(JSON, nullable=True)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class SyncStatus(Base):
    """
    Модель статуса синхронизации данных пользователя.
    Хранит информацию о текущем прогрессе, времени последней синхронизации и курсорах бэкфилла.
    """
    __tablename__ = "sync_status"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True, unique=True)
    is_syncing = Column(Boolean, default=False, nullable=False) # Флаг активного процесса синхронизации
    status_message = Column(String(255), default="", nullable=False) # Текстовое описание статуса или ошибки
    sync_started_at = Column(DateTime, nullable=True) # Время начала последней синхронизации
    sync_completed_at = Column(DateTime, nullable=True) # Время успешного завершения
    total_records_synced = Column(Integer, default=0, nullable=False) # Количество обработанных записей
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now, nullable=False)

    # Поля для устойчивого Backfill (первичной загрузки истории за год)
    backfill_cursor = Column(DateTime, nullable=True) # Текущая точка загрузки истории (FBO)
    backfill_started_at = Column(DateTime, nullable=True)
    backfill_completed_at = Column(DateTime, nullable=True)
    backfill_from = Column(DateTime, nullable=True)
    backfill_to = Column(DateTime, nullable=True)
    backfill_is_complete = Column(Boolean, default=False, nullable=False)

    # Поля для раздельной синхронизации FBS
    fbs_last_sync_at = Column(DateTime, nullable=True)
    fbs_backfill_cursor = Column(DateTime, nullable=True)
    fbs_backfill_is_complete = Column(Boolean, default=False, nullable=False)
    
    # Чекпоинт для годовой загрузки начислений (accruals)
    accruals_backfill_cursor = Column(DateTime, nullable=True)

    last_sync_attempt_at = Column(DateTime, nullable=True) # Время последней попытки запуска (для планировщика)

    user = relationship("User")

def get_db():
    """
    Генератор для получения сессии базы данных.
    Используется в качестве зависимости (Depends) в FastAPI.
    
    Yields:
        Session: Сессия SQLAlchemy.
    """
    db = SessionLocal()
    try: 
        yield db
    finally: 
        db.close()

def init_db():
    """
    Инициализация БД. 
    Сами таблицы создаются и обновляются через миграции Alembic.
    В этой функции могут выполняться проверки структуры или начальное заполнение справочников.
    """
    pass
