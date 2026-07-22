"""
Скрипт автосписания (рекуррентные платежи) для проекта Banana.
"""

import sys
import os
import logging
import asyncio
import hashlib
from datetime import datetime

from dotenv import load_dotenv
import aiosqlite
from yookassa import Configuration, Payment
import httpx
from utils import send_admin_log


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("checker")

# Загрузка env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")

if not all([BOT_TOKEN, SHOP_ID, SECRET_KEY]):
    logger.error("Не найдены переменные окружения BOT_TOKEN, YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY")
    sys.exit(1)

Configuration.account_id = SHOP_ID
Configuration.secret_key = SECRET_KEY

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "database.sqlite"))

TIERS_MAP = {
    'start': {'amount': 230, 'tokens': 280, 'name': "Старт"},
    'optimal': {'amount': 480, 'tokens': 530, 'name': "Оптимальный"},
    'optimal_trial': {'amount': 480, 'tokens': 530, 'name': "Оптимальный"},
    'pro': {'amount': 890, 'tokens': 1100, 'name': "Про"}
}

import db
from payment_server import update_user_balance

async def send_telegram_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения пользователю {chat_id}: {e}")

async def main():
    logger.info("Запуск проверки рекуррентных платежей...")
    now_iso = datetime.now().isoformat()
    await db.init_db()
    
    async with aiosqlite.connect(DB_PATH, timeout=10.0) as conn:
        await conn.execute("PRAGMA busy_timeout = 10000;")
        async with conn.execute('''
            SELECT telegram_id, subscription_tier, payment_method_id, subscription_end_date, username 
            FROM users 
            WHERE subscription_end_date <= ? AND payment_method_id IS NOT NULL
        ''', (now_iso,)) as cursor:
            users_to_charge = await cursor.fetchall()
            
        if not users_to_charge:
            logger.info("Нет пользователей для автопродления.")
            return

        logger.info(f"Найдено пользователей для автопродления: {len(users_to_charge)}")
        
        for row in users_to_charge:
            telegram_id, sub_tier, payment_method_id, sub_end, username = row
            
            tier_info = TIERS_MAP.get(sub_tier)
            if not tier_info:
                logger.warning(f"Неизвестный тариф '{sub_tier}' для пользователя {telegram_id}. Пропуск.")
                continue
                
            amount = tier_info['amount']
            tier_name = tier_info['name']
            target_sub_tier = 'optimal' if sub_tier == 'optimal_trial' else sub_tier
            
            logger.info(f"Попытка списания {amount} RUB с пользователя {telegram_id} (тариф {sub_tier})")
            
            # Генерация стабильного и детерминированного idempotency_key
            key_source = f"recurrent_{telegram_id}_{sub_end}"
            idempotency_key = hashlib.md5(key_source.encode('utf-8')).hexdigest()
            
            # 1. Запрос к ЮKassa (асинхронный обёрткой с таймаутом 30с)
            try:
                payment_payload = {
                    "amount": {
                        "value": f"{amount}.00",
                        "currency": "RUB"
                    },
                    "capture": True,
                    "payment_method_id": payment_method_id,
                    "description": f"Автопродление тарифа {tier_name}",
                    "metadata": {
                        "telegram_id": str(telegram_id),
                        "is_recurrent": "true"
                    }
                }
                payment = await asyncio.wait_for(
                    asyncio.to_thread(Payment.create, payment_payload, idempotency_key=idempotency_key),
                    timeout=30.0
                )
            except Exception as e:
                logger.error(f"Ошибка Yookassa при списании для {telegram_id}: {e}")
                continue

            status = payment.status
            payment_id = payment.id
            logger.info(f"Статус платежа для {telegram_id}: {status} (payment_id={payment_id})")

            if status == "succeeded":
                # Успешное списание: проверяем идемпотентность и начисляем подписку
                if not await db.is_payment_processed(payment_id):
                    tokens_to_add = tier_info['tokens']
                    await update_user_balance(
                        telegram_id,
                        tokens_to_add,
                        tier_name,
                        is_subscription=True,
                        sub_tier_code=target_sub_tier,
                        days=7,
                        payment_method_id=payment_method_id,
                        is_recurrent=True,
                        amount=float(amount)
                    )
                    await db.log_payment(telegram_id, float(amount), 'RUB', 'yookassa', payment_id)
                    await db.clear_trial_activated(telegram_id)
                    logger.info(f"[{telegram_id}] Продление подписки «{tier_name}» начислено в БД (payment_id={payment_id}).")
                else:
                    logger.info(f"[{telegram_id}] Продление подписки уже обработано вебхуком (payment_id={payment_id}).")
                
            elif status == "canceled":
                # Ошибка основного списания. Проверяем возможность каскадного списания (480 RUB -> 230 RUB)
                fb_succeeded = False
                if amount == 480:
                    logger.info(f"[{telegram_id}] Списание 480 RUB не удалось (canceled). Пробуем каскадное списание 230 RUB (тариф Старт)...")
                    fb_tier_info = TIERS_MAP['start']
                    fb_amount = fb_tier_info['amount']
                    fb_tokens = fb_tier_info['tokens']
                    fb_tier_name = fb_tier_info['name']

                    fb_key_source = f"recurrent_fallback_{telegram_id}_{sub_end}"
                    fb_idempotency_key = hashlib.md5(fb_key_source.encode('utf-8')).hexdigest()

                    fb_payload = {
                        "amount": {
                            "value": f"{fb_amount}.00",
                            "currency": "RUB"
                        },
                        "capture": True,
                        "payment_method_id": payment_method_id,
                        "description": f"Автопродление тарифа {fb_tier_name} (каскадное списание)",
                        "metadata": {
                            "telegram_id": str(telegram_id),
                            "is_recurrent": "true"
                        }
                    }

                    try:
                        fb_payment = await asyncio.wait_for(
                            asyncio.to_thread(Payment.create, fb_payload, idempotency_key=fb_idempotency_key),
                            timeout=30.0
                        )
                        fb_status = fb_payment.status
                        fb_payment_id = fb_payment.id
                        logger.info(f"Статус каскадного платежа для {telegram_id}: {fb_status} (payment_id={fb_payment_id})")

                        if fb_status == "succeeded":
                            fb_succeeded = True
                            if not await db.is_payment_processed(fb_payment_id):
                                await update_user_balance(
                                    telegram_id,
                                    fb_tokens,
                                    fb_tier_name,
                                    is_subscription=True,
                                    sub_tier_code='start',
                                    days=7,
                                    payment_method_id=payment_method_id,
                                    is_recurrent=True,
                                    amount=float(fb_amount)
                                )
                                await db.log_payment(telegram_id, float(fb_amount), 'RUB', 'yookassa', fb_payment_id)
                                await db.clear_trial_activated(telegram_id)
                                logger.info(f"[{telegram_id}] Каскадное продление по тарифу «{fb_tier_name}» (230 RUB) успешно (payment_id={fb_payment_id}).")

                            username_str = f"@{username}" if username else "не указан"
                            await send_admin_log(
                                f"⚡ <b>Каскадное списание сработало!</b>\n"
                                f"👤 <b>Пользователь:</b> {username_str}\n"
                                f"🆔 <b>ID:</b> <code>{telegram_id}</code>\n"
                                f"💳 <b>Не удалось 480 RUB ➔ Списано 230 RUB ({fb_tier_name})</b>"
                            )

                            fb_msg_text = (
                                f"⚠️ <b>Не удалось списать полную стоимость (480 ₽).</b>\n"
                                f"Мы перевели вас на уменьшенный тариф «{fb_tier_name}».\n\n"
                                f"💳 Списано: <code>{fb_amount} RUB</code>\n"
                                f"🍌 Начислено: <code>{fb_tokens}</code> бананов на 7 дней.\n"
                                f"Приятного пользования!"
                            )
                            await send_telegram_message(telegram_id, fb_msg_text)
                    except Exception as fb_err:
                        logger.error(f"Ошибка при каскадном списании для {telegram_id}: {fb_err}")

                if not fb_succeeded:
                    # Ошибка списания / нет денег на обеих попытках
                    username_str = f"@{username}" if username else "не указан"
                    await send_admin_log(
                        f"❌ <b>Отвал подписки (не удалось списать средства)</b>\n"
                        f"👤 <b>Пользователь:</b> {username_str}\n"
                        f"🆔 <b>ID:</b> <code>{telegram_id}</code>\n"
                        f"📦 <b>Тариф:</b> {tier_name}"
                    )
                    await conn.execute('''
                        UPDATE users 
                        SET subscription_tier = 'free',
                            payment_method_id = NULL,
                            subscription_end_date = NULL,
                            subscription_balance = 0
                        WHERE telegram_id = ?
                    ''', (telegram_id,))
                    await conn.commit()
                    
                    logger.info(f"[{telegram_id}] Продление не удалось. Подписка отменена (canceled).")
                    
                    # Уведомление
                    msg_text = "⚠️ <b>Не удалось продлить подписку.</b>\nПожалуйста, пополните карту или переоформите подписку в меню."
                    await send_telegram_message(telegram_id, msg_text)
                
            else:
                logger.info(f"[{telegram_id}] Платеж в статусе {status}. Ожидает завершения.")
                
if __name__ == "__main__":
    asyncio.run(main())
