# 📊 OzonAPIHub

**SaaS-платформа для аналитики и автоматизации продаж на Ozon**

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Flutter](https://img.shields.io/badge/Flutter-02569B?style=flat&logo=flutter)](https://flutter.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=flat&logo=postgresql)](https://www.postgresql.org/)

---

## 🎯 О проекте

OzonAPIHub — это профессиональный инструмент для селлеров, позволяющий автоматизировать сбор данных, анализировать прибыльность и управлять расходами в режиме реального времени.

- 🐍 **Backend**: FastAPI, SQLAlchemy, PostgreSQL.
- 📱 **Frontend**: Flutter Web/Android/iOS с единой базой кода.

### Основные фичи
- **Multi-tenancy**: Полная изоляция данных пользователей на уровне БД.
- **Безопасность**: Шифрование API-ключей (Fernet) и JWT-авторизация.
- **Аналитика**: Детальные отчеты по FBO, статусам, SKU и прибыльности.
- **Синхронизация**: Автоматический сбор данных с Ozon API в фоновом режиме.
- **Логирование**: Раздельные логи для системы и каждого пользователя с ротацией файлов.

---

## 📚 Документация

Для быстрого старта и глубокого понимания системы используйте следующие руководства:

1.  🚀 **[SETUP.md](SETUP.md)** — Установка Backend, настройка БД PostgreSQL, запуск и работа с логами.
2.  📱 **[FRONTEND.md](FRONTEND.md)** — Запуск Flutter-приложения, архитектура и авторизация.
3.  🗺️ **[ROADMAP.md](ROADMAP.md)** — План развития и технические рекомендации по улучшению.
4.  📜 **[CHANGELOG.md](CHANGELOG.md)** — История изменений и рефакторинга.

---

## 🏗️ Структура проекта

- `/routes`: API эндпоинты (аналитика, заказы, расходы, аутентификация).
- `/services`: Бизнес-логика синхронизации и интеграции с Ozon.
- `/db`: Модели данных SQLAlchemy.
- `/utils`: Утилиты шифрования, авторизации, валидации и логирования.
- `/ozon_sales_dashboard`: Исходный код Flutter-приложения.

---

## 🛠️ Разработка

### Backend
Сервер запускается через `main.py`. Для локальной разработки:
```bash
uvicorn main:app --reload --port 8080
```
Swagger UI доступен по адресу: `http://localhost:8080/docs`

---
⭐ **OzonAPIHub Team**
