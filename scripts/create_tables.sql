-- ============================================================
-- OzonAPIHub PostgreSQL Schema for SaaS (Multi-tenant)
-- ============================================================
-- Создайте базу данных перед запуском этого скрипта:
-- CREATE DATABASE ozondb;
-- CREATE USER ozonuser WITH PASSWORD 'ozonpass';
-- GRANT ALL PRIVILEGES ON DATABASE ozondb TO ozonuser;
-- ============================================================

-- Подключение к БД
-- \c ozondb

-- Создание таблицы пользователей
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    ozon_client_id TEXT,  -- Encrypted Ozon Client ID
    ozon_api_key TEXT,    -- Encrypted Ozon API Key
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    subscription_end_date TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_is_active ON users(is_active);

-- Создание таблицы заказов (legacy)
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_id INTEGER,
    posting_number VARCHAR(255),
    status VARCHAR(100),
    created_at VARCHAR(100),
    updated_at VARCHAR(100),
    data JSONB,
    CONSTRAINT uq_user_posting UNIQUE (user_id, posting_number)
);

CREATE INDEX idx_orders_user_id ON orders(user_id);
CREATE INDEX idx_orders_order_id ON orders(order_id);
CREATE INDEX idx_orders_posting_number ON orders(posting_number);

-- Создание таблицы заголовков заказов
CREATE TABLE IF NOT EXISTS order_headers (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_number VARCHAR(255),
    first_created_at VARCHAR(100),
    last_delivery_at VARCHAR(100),
    total_payout INTEGER,
    total_commission INTEGER,
    CONSTRAINT uq_user_order_number UNIQUE (user_id, order_number)
);

CREATE INDEX idx_order_headers_user_id ON order_headers(user_id);
CREATE INDEX idx_order_headers_order_number ON order_headers(order_number);

-- Создание таблицы постингов
CREATE TABLE IF NOT EXISTS order_postings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_number VARCHAR(255),
    posting_number VARCHAR(255),
    status VARCHAR(100),
    created_at VARCHAR(100),
    in_process_at VARCHAR(100),
    fact_delivery_date VARCHAR(100),
    substatus VARCHAR(100),
    analytics_data JSONB,
    financial_data JSONB,
    CONSTRAINT uq_user_posting_number UNIQUE (user_id, posting_number)
);

CREATE INDEX idx_order_postings_user_id ON order_postings(user_id);
CREATE INDEX idx_order_postings_order_number ON order_postings(order_number);
CREATE INDEX idx_order_postings_posting_number ON order_postings(posting_number);
CREATE INDEX idx_order_postings_created_at ON order_postings(created_at);
CREATE INDEX idx_order_postings_fact_delivery_date ON order_postings(fact_delivery_date);

-- Создание таблицы товаров в заказах
CREATE TABLE IF NOT EXISTS order_products (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    posting_id INTEGER REFERENCES order_postings(id) ON DELETE CASCADE,
    posting_number VARCHAR(255),
    sku INTEGER,
    offer_id VARCHAR(255),
    name VARCHAR(500),
    quantity INTEGER,
    price INTEGER,
    currency_code VARCHAR(10),
    commission_amount INTEGER,
    commission_percent INTEGER,
    payout INTEGER,
    total_discount_value INTEGER,
    total_discount_percent INTEGER
);

CREATE INDEX idx_order_products_user_id ON order_products(user_id);
CREATE INDEX idx_order_products_posting_id ON order_products(posting_id);
CREATE INDEX idx_order_products_posting_number ON order_products(posting_number);
CREATE INDEX idx_order_products_sku ON order_products(sku);
CREATE INDEX idx_order_products_offer_id ON order_products(offer_id);

-- Создание таблицы расходов
CREATE TABLE IF NOT EXISTS costs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type VARCHAR(50),  -- COGS, logistics, ads, withdrawal, other
    amount INTEGER,
    currency VARCHAR(10) DEFAULT 'RUB',
    date VARCHAR(100),
    scope_order_number VARCHAR(255),
    scope_posting_number VARCHAR(255),
    scope_sku INTEGER,
    scope_offer_id VARCHAR(255),
    notes TEXT
);

CREATE INDEX idx_costs_user_id ON costs(user_id);
CREATE INDEX idx_costs_type ON costs(type);
CREATE INDEX idx_costs_date ON costs(date);
CREATE INDEX idx_costs_scope_order_number ON costs(scope_order_number);
CREATE INDEX idx_costs_scope_posting_number ON costs(scope_posting_number);
CREATE INDEX idx_costs_scope_sku ON costs(scope_sku);
CREATE INDEX idx_costs_scope_offer_id ON costs(scope_offer_id);

-- Триггер для автоматического обновления updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Комментарии к таблицам
COMMENT ON TABLE users IS 'SaaS пользователи с индивидуальными Ozon credentials';
COMMENT ON TABLE orders IS 'Legacy таблица заказов с raw JSON данными';
COMMENT ON TABLE order_headers IS 'Агрегированные заголовки заказов';
COMMENT ON TABLE order_postings IS 'Нормализованные постинги с аналитикой';
COMMENT ON TABLE order_products IS 'Товары в постингах';
COMMENT ON TABLE costs IS 'Учет расходов пользователей';

-- Создание demo пользователя (для тестирования)
INSERT INTO users (email, hashed_password, is_demo, is_active)
VALUES ('demo@example.com', 'hashed_demo_password', TRUE, TRUE)
ON CONFLICT (email) DO NOTHING;

-- Вывод информации
SELECT 'База данных успешно инициализирована!' AS status;
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'public' 
ORDER BY table_name;
