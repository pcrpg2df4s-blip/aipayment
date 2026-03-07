import os
import logging
import httpx
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_LOG_CHANNEL = os.getenv("ADMIN_LOG_CHANNEL")

async def send_admin_log(text: str):
    """Отправляет лог в админский канал."""
    if not BOT_TOKEN or not ADMIN_LOG_CHANNEL:
        logging.error("send_admin_log: не задан BOT_TOKEN или ADMIN_LOG_CHANNEL.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_LOG_CHANNEL,
        "text": text,
        "parse_mode": "HTML"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10.0)
            response.raise_for_status()
    except Exception as e:
        logging.error(f"send_admin_log: ошибка отправки в админ-канал: {e}")
