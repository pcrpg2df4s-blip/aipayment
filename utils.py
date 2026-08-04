import os
import logging
import httpx
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_LOG_CHANNEL = os.getenv("ADMIN_LOG_CHANNEL")
BACKUP_CHANNEL_ID = os.getenv("BACKUP_CHANNEL_ID")
PHOTO_LOG_CHANNEL = os.getenv("PHOTO_LOG_CHANNEL")

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

async def send_photo_log(media_url: str, media_type: str, caption: str):
    """Отправляет копию сгенерированного медиа в канал логов фото."""
    if not BOT_TOKEN or not PHOTO_LOG_CHANNEL:
        logging.info("send_photo_log: не задан BOT_TOKEN или PHOTO_LOG_CHANNEL.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/"
    if media_type == "video":
        url += "sendVideo"
        payload = {
            "chat_id": PHOTO_LOG_CHANNEL,
            "video": media_url,
            "caption": caption,
            "parse_mode": "HTML"
        }
    else:
        url += "sendPhoto"
        payload = {
            "chat_id": PHOTO_LOG_CHANNEL,
            "photo": media_url,
            "caption": caption,
            "parse_mode": "HTML"
        }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=15.0)
            response.raise_for_status()
    except Exception as e:
        logging.error(f"send_photo_log: ошибка отправки в фото-лог-канал: {e}")

async def send_backup_db(file_path: str):
    """Отправляет файл базы данных в канал бэкапа."""
    if not BOT_TOKEN or not BACKUP_CHANNEL_ID:
        logging.error("send_backup_db: не задан BOT_TOKEN или BACKUP_CHANNEL_ID.")
        return

    from datetime import datetime
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    try:
        filename = f"database_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite"
        async with httpx.AsyncClient() as client:
            with open(file_path, "rb") as f:
                files = {"document": (filename, f)}
                data = {
                    "chat_id": BACKUP_CHANNEL_ID,
                    "caption": f"📂 Daily Database Backup - {datetime.now().strftime('%d.%m.%Y')}"
                }
                response = await client.post(url, data=data, files=files, timeout=30.0)
                response.raise_for_status()
    except Exception as e:
        logging.error(f"send_backup_db: ошибка отправки бэкапа базы: {e}")

