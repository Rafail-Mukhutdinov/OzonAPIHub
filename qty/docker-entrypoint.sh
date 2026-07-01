#!/bin/sh
set -e

echo "OzonAPIHub backend entrypoint started"

# DATABASE_URL больше не выводится в логи в целях безопасности (содержит пароль)

if [ "$INIT_DB_ON_STARTUP" = "true" ]; then
  echo "INIT_DB_ON_STARTUP is enabled, initializing database..."
  # python scripts/init_db_auto.py # Старый метод (SQL-запросы)
  alembic upgrade head # Новый метод (профессиональные миграции)
else
  echo "INIT_DB_ON_STARTUP is not enabled, skipping database initialization."
fi

exec "$@"
