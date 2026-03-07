import asyncio
import aiosqlite
from datetime import datetime, timedelta
import db
from utils import send_admin_log

async def run_daily_report():
    async with aiosqlite.connect(db.DB_PATH) as conn:
        # Новые юзеры за вчера
        async with conn.execute("SELECT COUNT(*) FROM users WHERE created_at = date('now', '-1 day', 'localtime')") as cursor:
            new_users = (await cursor.fetchone())[0] or 0

        # Доход RUB (ЮKassa) за вчера
        async with conn.execute("SELECT SUM(amount) FROM payment_logs WHERE currency = 'RUB' AND date(created_at, 'localtime') = date('now', '-1 day', 'localtime')") as cursor:
            revenue_rub = (await cursor.fetchone())[0] or 0.0

        # Доход XTR (Stars) за вчера
        async with conn.execute("SELECT SUM(amount) FROM payment_logs WHERE currency = 'XTR' AND date(created_at, 'localtime') = date('now', '-1 day', 'localtime')") as cursor:
            revenue_xtr = (await cursor.fetchone())[0] or 0.0

        # Активировано промокодов за вчера
        async with conn.execute("SELECT COUNT(*) FROM promocode_activations WHERE date(activated_at, 'localtime') = date('now', '-1 day', 'localtime')") as cursor:
            promocodes_activated = (await cursor.fetchone())[0] or 0

    # Получаем вчерашнюю дату для текста отчета
    target_date_str = (datetime.now() - timedelta(days=1)).strftime("%d.%m.%Y")
    
    report_text = (
        f"📊 <b>ОТЧЕТ ЗА СУТКИ (MSK)</b> {target_date_str}\n\n"
        f"📈 Новых юзеров: {new_users}\n"
        f"💰 Доход: {int(revenue_rub)} RUB / {int(revenue_xtr)} XTR\n"
        f"🎟 Активировано промокодов: {promocodes_activated}"
    )

    await send_admin_log(report_text)
    print(f"Отчет за {target_date_str} успешно отправлен в админ-канал.")

if __name__ == "__main__":
    asyncio.run(run_daily_report())
