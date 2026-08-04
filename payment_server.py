"""
payment_server.py — Асинхронный FastAPI-сервер для создания платежей через ЮKassa.

Запуск:
    pip install fastapi uvicorn python-dotenv yookassa
    python payment_server.py
"""

import asyncio
import uuid
import logging

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import httpx
import requests
from pydantic import BaseModel
from dotenv import load_dotenv
import os

from yookassa import Configuration, Payment
from utils import send_admin_log

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

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    import db
    await db.init_db()
    await send_admin_log("💳 Сервер оплаты YooKassa успешно запущен!")
    try:
        yield
    finally:
        await db.close_db()

app = FastAPI(title="Payment Server", lifespan=lifespan)

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
    method: str | None = None       # метод оплаты, например "stars" или "yookassa"

# ── GET /check_payment_status ─────────────────────────────────────────────────

@app.get("/check_payment_status")
async def check_payment_status(payment_id: str):
    """
    Проверяет статус платежа в ЮKassa.
    """
    if not payment_id or payment_id == "test":
        return {"status": "canceled"}

    if payment_id.startswith("stars_") or payment_id.startswith("cryptobot_"):
        # Для других методов вернем pending (их проверка идет через вебхуки напрямую в бот)
        return {"status": "pending"}
    
    try:
        payment = await asyncio.to_thread(Payment.find_one, payment_id)
        if payment and hasattr(payment, "status") and payment.status:
            return {"status": payment.status}
        return {"status": "error"}
    except Exception as e:
        logger.error("Ошибка при проверке статуса платежа %s: %s", payment_id, e)
        return {"status": "error"}

# ── GET /check-trial-status ───────────────────────────────────────────────────

@app.get("/check-trial-status")
async def check_trial_status(telegram_id: int):
    """
    Проверяет, использовал ли пользователь пробный период.
    """
    try:
        used = await db.check_trial_used(telegram_id)
        return {"has_used_trial": used}
    except Exception as e:
        logger.error("Ошибка при проверке статуса пробного периода для %s: %s", telegram_id, e)
        return {"has_used_trial": False}

# ── GET /get-user-subscription ────────────────────────────────────────────────

@app.get("/get-user-subscription")
async def get_user_subscription(telegram_id: int):
    """
    Возвращает текущую активную подписку пользователя.
    """
    import db
    try:
        _, tier, sub_end, _ = await db.get_user_profile(telegram_id)
        return {"tier": tier, "end_date": sub_end}
    except Exception as e:
        logger.error("Ошибка при получении статуса подписки для %s: %s", telegram_id, e)
        return {"tier": "free", "end_date": None}

# ── POST /create-payment ──────────────────────────────────────────────────────

@app.post("/create-payment")
async def create_payment(data: PaymentRequest):
    """
    Создаёт платёж в ЮKassa или инвойс Telegram Stars и возвращает URL для редиректа.
    """
    logger.info(
        "Создание платежа: amount=%.2f, description=%s, telegram_id=%s, method=%s",
        data.amount, data.description, data.telegram_id, data.method,
    )

    # Проверка на повторное использование пробного периода (1 рубль)
    if int(data.amount) == 1 and data.telegram_id:
        if await db.check_trial_used(data.telegram_id):
            logger.warning("Пользователь %s попытался повторно оформить пробный период.", data.telegram_id)
            raise HTTPException(status_code=400, detail="Вы уже использовали пробный период.")

    try:
        # Обработка Telegram Stars
        if data.method == "stars" and data.telegram_id:
            from aiogram import Bot
            from aiogram.types import LabeledPrice
            BOT_TOKEN = os.getenv("BOT_TOKEN")
            if not BOT_TOKEN:
                raise HTTPException(status_code=500, detail="BOT_TOKEN not configured")
            
            bot = Bot(token=BOT_TOKEN)
            amount_stars = int(data.amount)
            tokens_to_add, tier_name = _resolve_tier(data.amount, data.description)
            
            invoice_url = await bot.create_invoice_link(
                title="Пополнение баланса / Подписка",
                description=data.description,
                payload=f"stars_{data.telegram_id}_{tokens_to_add}_{amount_stars}",
                provider_token="", 
                currency="XTR",
                prices=[LabeledPrice(label="Stars", amount=amount_stars)],
                subscription_period=2592000
            )
            await bot.session.close()
            
            logger.info("Инвойс Stars создан: url=%s", invoice_url)
            return {
                "payment_url": invoice_url,
                "payment_id": f"stars_{uuid.uuid4()}",
            }

        # Обработка CryptoBot
        if data.method == "cryptobot" and data.telegram_id:
            CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN")
            if not CRYPTOBOT_TOKEN:
                raise HTTPException(status_code=500, detail="CRYPTOBOT_TOKEN not configured")
            
            tokens_to_add, tier_name = _resolve_tier(data.amount, data.description)
            
            url = "https://pay.crypt.bot/api/createInvoice"
            headers = {
                "Crypto-Pay-API-Token": CRYPTOBOT_TOKEN
            }
            # Конвертируем рубли в инвойс RUB
            payload_api = {
                "amount": str(data.amount),
                "currency_type": "fiat",
                "fiat": "RUB",
                "description": data.description,
                "payload": f"cryptobot_{data.telegram_id}_{tokens_to_add}"
            }
            
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=15.0)) as client:
                resp = await client.post(url, headers=headers, json=payload_api)
                resp_data = resp.json()
                
            if resp_data.get("ok"):
                bot_invoice_url = resp_data["result"]["bot_invoice_url"]
                logger.info("CryptoBot инвойс создан: url=%s", bot_invoice_url)
                return {
                    "payment_url": bot_invoice_url,
                    "payment_id": f"cryptobot_{uuid.uuid4()}"
                }
            else:
                logger.error(f"Ошибка CryptoBot: {resp_data}")
                raise HTTPException(status_code=500, detail="Failed to create CryptoBot invoice")

        # Обработка ЮKassa (и других методов)
        payload: dict = {
            "amount": {
                "value": f"{data.amount:.2f}",
                "currency": "RUB",
            },
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/BananaGenerationBot",
            },
            "capture": True,
            "description": data.description,
        }

        # Сохранение карты для рекуррентных платежей (подписок)
        if int(data.amount) in (1, 230, 480, 890):
            payload["save_payment_method"] = True

        # Сохраняем telegram_id в метаданных для вебхука (опционально)
        if data.telegram_id:
            payload["metadata"] = {"telegram_id": str(data.telegram_id)}

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Idempotence-Key": str(uuid.uuid4()),
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=15.0)) as client:
            resp = await client.post(
                "https://api.yookassa.ru/v3/payments",
                auth=(SHOP_ID, SECRET_KEY),
                headers=headers,
                json=payload
            )
            if resp.status_code != 200:
                logger.error("Ошибка ЮKassa API (%d): %s", resp.status_code, resp.text)
                raise HTTPException(status_code=500, detail=f"Ошибка ЮKassa ({resp.status_code}): {resp.text}")
            resp_data = resp.json()
            confirmation_url = resp_data.get("confirmation", {}).get("confirmation_url")
            payment_id = resp_data.get("id")
            if not confirmation_url or not payment_id:
                raise HTTPException(status_code=500, detail="ЮKassa не вернула ссылку на оплату")

    except HTTPException:
        raise
    except httpx.ConnectTimeout:
        logger.error("Таймаут подключения к ЮKassa API")
        raise HTTPException(status_code=504, detail="Таймаут подключения к ЮKassa. Попробуйте ещё раз.")
    except httpx.TimeoutException:
        logger.error("Таймаут ответа от ЮKassa API")
        raise HTTPException(status_code=504, detail="Таймаут ответа от ЮKassa. Попробуйте ещё раз.")
    except Exception as e:
        err_msg = str(e) or repr(e)
        logger.exception("Ошибка создания платежа: %s", err_msg)
        raise HTTPException(status_code=500, detail=f"Ошибка сервера платежей: {err_msg}")

    logger.info("Платёж создан: id=%s, url=%s", payment_id, confirmation_url)

    return {
        "payment_url": confirmation_url,
        "payment_id": payment_id,
    }

# ── Тарифы: (мин_сумма, макс_сумма) → (токены, название) ────────────────────
# Корректируй суммы и токены под свои реальные тарифы.

TIERS: list[tuple[float, float, int, str]] = [
    # (от,    до,    токены, название)
    ( 220,   300,   280, "Старт"),
    ( 400,   600,   530, "Оптимальный"),
    ( 800,  1000,  1100, "Про"),
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
import json

async def update_user_balance(
    telegram_id: int, 
    tokens_to_add: int, 
    new_tier: str, 
    is_subscription: bool = False, 
    sub_tier_code: str = 'free', 
    days: int = 30, 
    payment_method_id: str = None,
    is_recurrent: bool = False,
    amount: float = 0.0
) -> None:
    """
    Реальное начисление токенов в базу и уведомление пользователя.
    """
    try:
        # ── ШАГ 1: Обновляем базу данных ─────────────────────────────────────
        desc = f"Подписка {sub_tier_code.capitalize()}" if is_subscription else f"Покупка {tokens_to_add} 🍌"
        await db.add_balance(telegram_id, tokens_to_add, is_subscription=is_subscription, tier=sub_tier_code, days=days, payment_method_id=payment_method_id, description=desc)
        new_balance = await db.get_balance(telegram_id)
        
        logger.info(
            "УСПЕХ: telegram_id=%s | +%d токенов зачислено | тариф=%s | новый баланс=%d",
            telegram_id, tokens_to_add, new_tier, new_balance
        )

        # ── ШАГ 2: Отправляем сообщение пользователю через Bot API ──────────
        BOT_TOKEN = os.getenv("BOT_TOKEN")
        
        if BOT_TOKEN:
            if is_recurrent:
                text = (
                    f"✅ *Ваша подписка «{new_tier}» успешно продлена!*\n\n"
                    f"💳 Списано: `{amount:.0f} RUB`\n"
                    f"🍌 Начислено: `{tokens_to_add}` бананов\n"
                    f"Приятного пользования!"
                )
            else:
                text = (
                    f"✅ *Оплата прошла успешно!*\n\n"
                    f"Начислено: `{tokens_to_add}` бананов 🍌\n"
                    f"Ваш текущий баланс: `{new_balance}` бананов 🍌\n"
                    f"Тариф: {new_tier}\n\n"
                    f"Приятного пользования!"
                )
            raw_keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "📷 Создать фото", "callback_data": "menu_photos"},
                        {"text": "🎬 Создать видео", "callback_data": "menu_videos"}
                    ]
                ]
            }
            reply_markup_json = json.dumps(raw_keyboard)

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    params={
                        "chat_id": telegram_id, 
                        "text": text, 
                        "parse_mode": "Markdown",
                        "reply_markup": reply_markup_json
                    }
                )
                response.raise_for_status()

    except Exception as e:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА при зачислении баланса: %s", e)


# ── POST /yookassa-webhook ────────────────────────────────────────────────────

import ipaddress

# Официальные подсети ЮKassa (для фильтрации левых запросов)
YOOKASSA_SUBNETS = [
    ipaddress.ip_network("185.71.76.0/22", strict=False),
    ipaddress.ip_network("77.75.152.0/20", strict=False),
]


@app.post("/yookassa-webhook", status_code=200)
async def yookassa_webhook(request: Request):
    """
    Вебхук от ЮKassa. Ловит событие payment.succeeded,
    определяет тариф и начисляет токены пользователю.
    БЕССМЕРТНЫЙ ЭНДПОИНТ: всегда возвращает 200, даже при внутренних ошибках.
    """
    # ── Проверка IP-адреса ЮKassa ─────────────────────────────────────────────
    client_ip = request.headers.get("x-forwarded-for")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    else:
        client_ip = request.headers.get("x-real-ip")
        if not client_ip:
            client_ip = request.client.host if request.client else None

    logger.info("Вебхук от IP: %s", client_ip)

    ALLOWED_LOCAL_IPS = {"127.0.0.1", "::1", "localhost"}
    is_valid_ip = False
    if client_ip in ALLOWED_LOCAL_IPS:
        is_valid_ip = True
    else:
        try:
            ip = ipaddress.ip_address(client_ip)
            for subnet in YOOKASSA_SUBNETS:
                if ip in subnet:
                    is_valid_ip = True
                    break
        except Exception:
            pass

    if not is_valid_ip:
        logger.warning("Попытка несанкционированного доступа к вебхуку с IP: %s", client_ip)
        raise HTTPException(status_code=403, detail="Access denied")

    # ── Парсим тело ───────────────────────────────────────────────────────────
    try:
        body = await request.json()
    except Exception as e:
        print(f"WEBHOOK ERROR (parse): {e}")
        return {"status": "parse_error"}

    event = body.get("event", "")
    if event != "payment.succeeded":
        return {"status": "ignored"}

    # ── Всё остальное — в одном глухом try/except ─────────────────────────────
    try:
        payment_obj = body.get("object", {})
        yookassa_payment_id = payment_obj.get("id")

        print(f"=== Получен вебхук для payment_id: {yookassa_payment_id} ===")

        # ── Идемпотентность ───────────────────────────────────────────────────
        print("Проверка на дубль...")
        await db.init_db()
        if yookassa_payment_id and await db.is_payment_processed(yookassa_payment_id):
            print("ДУБЛЬ! Отклоняем.")
            logger.warning("Дубль вебхука! payment_id=%s уже обработан.", yookassa_payment_id)
            return {"status": "already_processed"}

        # ── Сумма ─────────────────────────────────────────────────────────────
        try:
            amount = float(payment_obj.get("amount", {}).get("value", 0))
        except (TypeError, ValueError):
            amount = 0.0

        description = payment_obj.get("description", "")

        # ── telegram_id из metadata ───────────────────────────────────────────
        metadata = payment_obj.get("metadata", {})
        raw_tg_id = metadata.get("telegram_id")
        is_recurrent = metadata.get("is_recurrent") == "true"

        if not raw_tg_id:
            logger.warning("payment.succeeded без telegram_id! payment_id=%s", yookassa_payment_id)
            return {"status": "no_telegram_id"}

        try:
            telegram_id = int(raw_tg_id)
        except (TypeError, ValueError):
            logger.error("Некорректный telegram_id=%s", raw_tg_id)
            return {"status": "bad_telegram_id"}

        # ── payment_method.id для рекуррентных платежей ───────────────────────
        payment_method_id = payment_obj.get("payment_method", {}).get("id")

        # ── Определяем тариф ──────────────────────────────────────────────────
        tokens_to_add, tier_name = _resolve_tier(amount, description)

        sub_tier = 'free'
        if int(amount) == 1:
            tokens_to_add = 150
            tier_name = "Оптимальный (Пробный)"
            sub_tier = 'optimal_trial'
        elif tier_name == "Старт":
            sub_tier = 'start'
        elif tier_name == "Оптимальный":
            sub_tier = 'optimal'
        elif tier_name == "Про":
            sub_tier = 'pro'

        logger.info(
            "Платёж принят: telegram_id=%s, amount=%.2f, тариф=%s, токены=%d, sub_tier=%s, is_recurrent=%s",
            telegram_id, amount, tier_name, tokens_to_add, sub_tier, is_recurrent
        )

        if is_recurrent:
            await send_admin_log(
                f"🔄 Автопродление сработало!\n"
                f"Пользователь: {telegram_id}\n"
                f"Тариф: {tier_name}\n"
                f"Сумма: {int(amount)} RUB"
            )
        else:
            await send_admin_log(
                f"💰 Успешная оплата!\n"
                f"Пользователь: {telegram_id}\n"
                f"Тариф: {tier_name}\n"
                f"Сумма: {int(amount)} RUB"
            )

        # ── Записываем лог платежа сразу для защиты от параллельных дублей ────
        if yookassa_payment_id:
            await db.log_payment(telegram_id, amount, 'RUB', 'yookassa', yookassa_payment_id)

        # ── Начисляем токены и обновляем подписку ──────────────────────────────
        is_sub = sub_tier != 'free'
        days = 1 if int(amount) == 1 else 7
        
        await update_user_balance(
            telegram_id,
            tokens_to_add,
            tier_name,
            is_subscription=is_sub,
            sub_tier_code=sub_tier,
            days=days,
            payment_method_id=payment_method_id,
            is_recurrent=is_recurrent,
            amount=amount
        )

        # Отмечаем, что пользователь использовал пробный период и блокируем первые 150 бананов для видео на 1 день
        if int(amount) == 1:
            await db.set_trial_used(telegram_id)
            await db.set_trial_activated(telegram_id)
            logger.info("Пользователь %s успешно использовал пробный период (150 бананов заблокированы для видео на 1-й день).", telegram_id)
        elif amount >= 220 and sub_tier in ('start', 'optimal', 'pro'):
            # Сбрасываем ограничение только при покупке полноценной подписки (от 220 ₽)
            await db.clear_trial_activated(telegram_id)

        return {"status": "ok"}

    except Exception as e:
        print(f"WEBHOOK ERROR: {e}")
        logger.exception("Необработанная ошибка в вебхуке: %s", e)
        # Всегда возвращаем 200, чтобы ЮKassa не повторяла хук
        return {"status": "internal_error"}


# ── Запуск ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("payment_server:app", host="0.0.0.0", port=8000, reload=False)
