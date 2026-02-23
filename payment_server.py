"""
payment_server.py — Асинхронный FastAPI-сервер для создания платежей через ЮKassa.

Запуск:
    pip install fastapi uvicorn python-dotenv yookassa
    python payment_server.py
"""

import uuid
import logging

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import os

from yookassa import Configuration, Payment

# ── Загрузка переменных окружения ────────────────────────────────────────────

load_dotenv()

SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")
BOT_USERNAME = "BananaGenerationBot"   # ← замени на username своего бота

if not SHOP_ID or not SECRET_KEY:
    raise RuntimeError(
        "Не найдены YOOKASSA_SHOP_ID или YOOKASSA_SECRET_KEY в файле .env"
    )

# ── Инициализация ЮKassa ──────────────────────────────────────────────────────

Configuration.account_id = SHOP_ID
Configuration.secret_key = SECRET_KEY

# ── FastAPI приложение ────────────────────────────────────────────────────────

app = FastAPI(title="Payment Server")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── CORS (разрешаем запросы с любого домена) ──────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # GitHub Pages и любой другой источник
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Схема входящего запроса ───────────────────────────────────────────────────

class PaymentRequest(BaseModel):
    amount: float           # сумма в рублях, например 890.00
    email: str              # email для чека
    description: str        # описание заказа, например "Подписка Оптимальный"
    telegram_id: int | None = None  # ID пользователя Telegram (опционально)

# ── POST /create-payment ──────────────────────────────────────────────────────

@app.post("/create-payment")
async def create_payment(data: PaymentRequest):
    """
    Создаёт платёж в ЮKassa и возвращает confirmation_url для редиректа.
    """
    logger.info(
        "Создание платежа: amount=%.2f, email=%s, description=%s, telegram_id=%s",
        data.amount, data.email, data.description, data.telegram_id,
    )

    try:
        payment = Payment.create(
            {
                "amount": {
                    "value": f"{data.amount:.2f}",
                    "currency": "RUB",
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": f"https://t.me/{BOT_USERNAME}",
                },
                "capture": True,
                "description": data.description,
                "receipt": {
                    "customer": {
                        "email": data.email,
                    },
                    "items": [
                        {
                            "description": data.description,
                            "quantity": "1.00",
                            "amount": {
                                "value": f"{data.amount:.2f}",
                                "currency": "RUB",
                            },
                            "vat_code": "1",  # без НДС
                        }
                    ],
                },
                # Сохраняем telegram_id в метаданных для вебхука (опционально)
                **({"metadata": {"telegram_id": str(data.telegram_id)}} if data.telegram_id else {}),
            },
            idempotency_key=str(uuid.uuid4()),  # защита от дублирования
        )
    except Exception as e:
        logger.error("Ошибка создания платежа: %s", e)
        raise HTTPException(status_code=500, detail=f"Ошибка ЮKassa: {e}")

    confirmation_url = payment.confirmation.confirmation_url
    payment_id = payment.id

    logger.info("Платёж создан: id=%s, url=%s", payment_id, confirmation_url)

    return {
        "payment_url": confirmation_url,
        "payment_id": payment_id,
    }

# ── Запуск ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("payment_server:app", host="0.0.0.0", port=8000, reload=False)
