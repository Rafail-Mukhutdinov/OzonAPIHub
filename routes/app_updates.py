import json
import os
from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(prefix="/app", tags=["App Updates"])

# Путь к конфигурационному файлу версии
VERSION_FILE = os.path.join("static", "apps", "version.json")

# Значения по умолчанию, если файл не найден
DEFAULT_APP_INFO = {
    "version_name": "1.0.0",
    "version_code": 1,
    "display_message": "Стандартное обновление системы.",
    "download_url": "/app/download/app-release.apk"
}

@router.get("/latest-version")
async def get_latest_version():
    """
    Возвращает информацию о последней доступной версии.
    Данные берутся из файла static/apps/version.json.
    Это позволяет обновлять приложение без перезагрузки бэкенда.
    """
    if os.path.exists(VERSION_FILE):
        try:
            with open(VERSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            return {
                "error": f"Ошибка чтения файла версии: {e}",
                "data": DEFAULT_APP_INFO
            }
    
    # Если файла нет, создадим его с дефолтными данными (для удобства)
    os.makedirs(os.path.dirname(VERSION_FILE), exist_ok=True)
    try:
        with open(VERSION_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_APP_INFO, f, indent=4, ensure_ascii=False)
    except:
        pass
        
    return DEFAULT_APP_INFO

@router.get("/download/{filename}")
async def download_app(filename: str):
    """Эндпоинт для скачивания APK файла"""
    # Санитизация имени файла для защиты от Path Traversal
    safe_filename = os.path.basename(filename)
    file_path = os.path.join("static", "apps", safe_filename)
    
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            filename=safe_filename,
            media_type='application/vnd.android.package-archive'
        )
    return {"error": "Файл не найден. Убедитесь, что вы положили APK в static/apps/"}
