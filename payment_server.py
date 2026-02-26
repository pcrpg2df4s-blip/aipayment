"""
payment_server.py — Асинхронный FastAPI-сервер для создания платежей через ЮKassa.

Запуск:
    pip install fastapi uvicorn python-dotenv yookassa
    python payment_server.py
"""

import uuid
import logging

import uvicorn
from fastapi import FastAPI, HTTPException, Request
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
    description: str        # описание заказа, например "Подписка Оптимальный"
    telegram_id: int | None = None  # ID пользователя Telegram (опционально)

# ── POST /create-payment ──────────────────────────────────────────────────────

@app.post("/create-payment")
async def create_payment(data: PaymentRequest):
    """
    Создаёт платёж в ЮKassa и возвращает confirmation_url для редиректа.
    """
    logger.info(
        "Создание платежа: amount=%.2f, description=%s, telegram_id=%s",
        data.amount, data.description, data.telegram_id,
    )

    try:
        payload: dict = {
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
        }

        # Сохраняем telegram_id в метаданных для вебхука (опционально)
        if data.telegram_id:
            payload["metadata"] = {"telegram_id": str(data.telegram_id)}

        payment = Payment.create(payload, idempotency_key=str(uuid.uuid4()))
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

# ── Тарифы: (мин_сумма, макс_сумма) → (токены, название) ────────────────────
# Корректируй суммы и токены под свои реальные тарифы.

TIERS: list[tuple[float, float, int, str]] = [
    # (от,    до,    токены, название)
    ( 400,   600,   530, "Старт"),
    ( 800,  1000,  1100, "Оптимальный"),
    (1500,  2000,  2200, "Про"),
]


def _resolve_tier(amount: float, description: str) -> tuple[int, str]:
    """Определяет тариф по сумме платежа (запасной вариант — по description)."""
    desc_lower = description.lower()
    
    # Сначала проверяем, не покупка ли это просто токенов
    if "докупка токенов:" in desc_lower:
        try:
            tokens = int(description.split(":")[1].strip())
            # Учитываем бонус 10%, как на фронтенде
            total_tokens = int(tokens * 1.1)
            return total_tokens, "Докупка токенов"
        except (IndexError, ValueError):
            pass

    # Далее пробуем по сумме (если это подписка)
    for low, high, tokens, name in TIERS:
        if low <= amount <= high:
            return tokens, name
            
    # Если сумма не попала ни в один диапазон — ищем ключевое слово в description
    for _, _, tokens, name in TIERS:
        if name.lower() in desc_lower:
            return tokens, name
            
    # Крайний случай: возвращаем 0 токенов, чтобы не начислять ошибочно
    logger.warning(
        "[WARNING! ALARM!] Платёж не подошел ни под один критерий тарифа. \n"
        "Сумма: %.2f | Описание: '%s'. Начислено токенов: 0. \n"
        "Требуется ручная проверка транзакции!", 
        amount, description
    )
    return 0, "Неизвестный платеж"


# ── Обновление баланса ───────────────────────────────────────────────
import db
import httpx

db.init_db()

async def update_user_balance(telegram_id: int, tokens_to_add: int, new_tier: str) -> None:
    """
    Реальное начисление токенов в базу и уведомление пользователя.
    """
    try:
        # ── ШАГ 1: Обновляем базу данных ─────────────────────────────────────
        new_balance = await db.add_tokens(telegram_id, tokens_to_add)
        
        logger.info(
            "УСПЕХ: telegram_id=%s | +%d токенов зачислено | тариф=%s | новый баланс=%d",
            telegram_id, tokens_to_add, new_tier, new_balance
        )

        # ── ШАГ 2: Отправляем сообщение пользователю через Bot API ──────────
        BOT_TOKEN = os.getenv("BOT_TOKEN")
        
        if BOT_TOKEN:
            text = (
                f"✅ *Оплата прошла успешно!*\n\n"
                f"Начислено: `{tokens_to_add}` бананов 🍌\n"
                f"Ваш текущий баланс: `{new_balance}` бананов 🍌\n"
                f"Тариф: {new_tier}\n\n"
                f"Приятного пользования!"
            )
            async with httpx.AsyncClient() as client:
                await client.get(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    params={"chat_id": telegram_id, "text": text, "parse_mode": "Markdown"}
                )

    except Exception as e:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА при зачислении баланса: %s", e)


# ── POST /yookassa-webhook ────────────────────────────────────────────────────

# Официальные IP-адреса ЮKassa (для фильтрации левых запросов)
YOOKASSA_IPS = {
    "185.71.76.0", "185.71.77.0",
    "77.75.153.0", "77.75.156.11",
    "77.75.156.35", "77.75.154.128",
    "2a02:5180:0:1509::",   # IPv6-блоки (для справки, не проверяем строго)
}


@app.post("/yookassa-webhook", status_code=200)
async def yookassa_webhook(request: Request):
    """
    Вебхук от ЮKassa. Ловит событие payment.succeeded,
    определяет тариф и начисляет токены пользователю.
    """
    # ── 1. Проверка IP (необязательно в тестовом режиме, но желательно в проде) ─
    client_ip = request.client.host
    logger.info("Вебхук от IP: %s", client_ip)

    # ── 2. Парсим тело ────────────────────────────────────────────────────────
    try:
        body = await request.json()
    except Exception as e:
        logger.error("Не удалось разобрать тело вебхука: %s", e)
        # Всегда возвращаем 200, иначе ЮKassa будет повторять запрос
        return {"status": "parse_error"}

    event = body.get("event", "")
    logger.info("Получено событие: %s", event)

    # ── 3. Обрабатываем только payment.succeeded ──────────────────────────────
    if event != "payment.succeeded":
        return {"status": "ignored"}

    payment_obj = body.get("object", {})

    # Сумма
    try:
        amount = float(payment_obj.get("amount", {}).get("value", 0))
    except (TypeError, ValueError):
        amount = 0.0

    # Описание (название тарифа)
    description = payment_obj.get("description", "")

    # telegram_id из metadata
    metadata = payment_obj.get("metadata", {})
    raw_tg_id = metadata.get("telegram_id")

    if not raw_tg_id:
        logger.warning("payment.succeeded без telegram_id в metadata! payment_id=%s",
                       payment_obj.get("id"))
        return {"status": "no_telegram_id"}

    try:
        telegram_id = int(raw_tg_id)
    except (TypeError, ValueError):
        logger.error("Некорректный telegram_id=%s", raw_tg_id)
        return {"status": "bad_telegram_id"}

    # ── 4. Определяем тариф ───────────────────────────────────────────────────
    tokens_to_add, tier_name = _resolve_tier(amount, description)
    logger.info(
        "Платёж принят: telegram_id=%s, amount=%.2f, тариф=%s, токены=%d",
        telegram_id, amount, tier_name, tokens_to_add,
    )

    # ── 5. Начисляем токены ───────────────────────────────────────────────────
    await update_user_balance(telegram_id, tokens_to_add, tier_name)

    return {"status": "ok"}


# ── Запуск ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("payment_server:app", host="0.0.0.0", port=8000, reload=False)
