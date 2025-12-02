from fastapi import FastAPI
import requests
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

@app.get("/ping")
def ping():
    return {"message": "pong"}

# Эндпоинт для получения заказов с Ozon Seller API

# Эндпоинт для получения FBO заказов с фильтрами
@app.post("/orders/fbo")
def get_fbo_orders(
    since: str,
    to: str,
    limit: int = 5,
    offset: int = 0,
    analytics_data: bool = True,
    financial_data: bool = True,
    legal_info: bool = False
):
    """
    Получить список FBO заказов с Ozon Seller API
    Параметры фильтрации: даты, лимит, offset, дополнительные данные
    """
    client_id = os.getenv("OZON_CLIENT_ID")
    api_key = os.getenv("OZON_API_KEY")
    url = "https://api-seller.ozon.ru/v2/posting/fbo/list"
    headers = {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json"
    }
    body = {
        "dir": "ASC",
        "filter": {
            "since": since,
            "status": "",
            "to": to
        },
        "limit": limit,
        "offset": offset,
        "translit": True,
        "with": {
            "analytics_data": analytics_data,
            "financial_data": financial_data,
            "legal_info": legal_info
        }
    }
    try:
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()
        data = response.json()
        return data
    except Exception as e:
        return {"error": str(e)}
