"""
Скрипт автосписания (рекуррентные платежи) для проекта Banana.
"""

import sys
import os
import uuid
import logging
import asyncio
from datetime import datetime, timedelta

from dotenv import load_dotenv
import aiosqlite
from yookassa import Configuration, Payment
import httpx

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
    'pro': {'amount': 890, 'tokens': 1100, 'name': "Про"}
}

async def send_telegram_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
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
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('''
            SELECT telegram_id, subscription_tier, payment_method_id 
            FROM users 
            WHERE subscription_end_date <= ? AND payment_method_id IS NOT NULL
        ''', (now_iso,)) as cursor:
            users_to_charge = await cursor.fetchall()
            
        if not users_to_charge:
            logger.info("Нет пользователей для автопродления.")
            return

        logger.info(f"Найдено пользователей для автопродления: {len(users_to_charge)}")
        
        for row in users_to_charge:
            telegram_id, sub_tier, payment_method_id = row
            
            tier_info = TIERS_MAP.get(sub_tier)
            if not tier_info:
                logger.warning(f"Неизвестный тариф '{sub_tier}' для пользователя {telegram_id}. Пропуск.")
                continue
                
            amount = tier_info['amount']
            tokens = tier_info['tokens']
            tier_name = tier_info['name']
            
            logger.info(f"Попытка списания {amount} RUB с пользователя {telegram_id} (тариф {sub_tier})")
            
            # 1. Запрос к ЮKassa
            try:
                payment = Payment.create({
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
                }, idempotency_key=str(uuid.uuid4()))
            except Exception as e:
                logger.error(f"Ошибка Yookassa при списании для {telegram_id}: {e}")
                continue

            status = payment.status
            logger.info(f"Статус платежа для {telegram_id}: {status}")

            if status == "succeeded":
                # Успех
                new_end_date = (datetime.now() + timedelta(days=30)).isoformat()
                
                await db.execute('''
                    UPDATE users 
                    SET subscription_end_date = ?, 
                        subscription_balance = subscription_balance + ?
                    WHERE telegram_id = ?
                ''', (new_end_date, tokens, telegram_id))
                await db.commit()
                
                logger.info(f"[{telegram_id}] Подписка продлена. Начислено {tokens} токенов.")
                
                # Уведомление
                msg_text = (
                    f"✅ *Ваша подписка «{tier_name}» успешно продлена!*\n\n"
                    f"💳 Списано: `{amount} RUB`\n"
                    f"🍌 Начислено: `{tokens}` бананов\n"
                    f"Приятного пользования!"
                )
                await send_telegram_message(telegram_id, msg_text)
                
            elif status == "canceled":
                # Ошибка списания / нет денег
                await db.execute('''
                    UPDATE users 
                    SET subscription_tier = 'free',
                        payment_method_id = NULL,
                        subscription_end_date = NULL,
                        subscription_balance = 0
                    WHERE telegram_id = ?
                ''', (telegram_id,))
                await db.commit()
                
                logger.info(f"[{telegram_id}] Продление не удалось. Подписка отменена (canceled).")
                
                # Уведомление
                msg_text = "Не удалось продлить подписку. Пожалуйста, пополните карту или оплатите тариф заново в меню."
                await send_telegram_message(telegram_id, msg_text)
                
            else:
                logger.info(f"[{telegram_id}] Платеж в статусе {status}. Требуется обновить позже.")
                
if __name__ == "__main__":
    asyncio.run(main())
