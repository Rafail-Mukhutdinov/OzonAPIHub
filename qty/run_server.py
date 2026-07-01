#!/usr/bin/env python
import sys
import os

# Добавляем текущую директорию в path
sys.path.insert(0, os.path.dirname(__file__))

if __name__ == "__main__":
    import uvicorn
    # В продакшене (Docker) reload должен быть False, чтобы избежать бесконечных перезапусков из-за логов.
    # Можно управлять этим через переменную окружения.
    is_reload = os.getenv("DEBUG", "false").lower() in ("true", "1", "t")

    print(f"Запуск сервера (reload={is_reload})...")
    uvicorn.run("main:app", host="0.0.0.0", port=8083, reload=is_reload)
