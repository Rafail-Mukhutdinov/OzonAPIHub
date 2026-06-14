#!/usr/bin/env python
import sys
import os

# Добавляем текущую директорию в path
sys.path.insert(0, os.path.dirname(__file__))

if __name__ == "__main__":
    import uvicorn
    # host="0.0.0.0" для Docker, порт 8080 согласно docker-compose.yml
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
