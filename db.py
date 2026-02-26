import sqlite3
import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "database.sqlite")

# Синхронная функция: мгновенно создает файл и таблицу при первом запуске
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0
            )
        ''')
        conn.commit()

# Автоматически вызываем при старте
init_db()

async def get_balance(telegram_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def add_user(telegram_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("INSERT OR IGNORE INTO users (telegram_id, balance) VALUES (?, 15)", (telegram_id,)) as cursor:
            await db.commit()
            return cursor.rowcount > 0

async def add_tokens(telegram_id: int, tokens: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO users (telegram_id, balance) 
            VALUES (?, ?)
            ON CONFLICT(telegram_id) 
            DO UPDATE SET balance = balance + ?
        ''', (telegram_id, tokens, tokens))
        await db.commit()
        
        # Возвращаем новый баланс
        async with db.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0]

async def spend_tokens(telegram_id: int, tokens: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            row = await cursor.fetchone()
            
            # Если юзера нет или денег не хватает
            if not row or row[0] < tokens:
                return False
            
        # Если хватает — списываем
        await db.execute("UPDATE users SET balance = balance - ? WHERE telegram_id = ?", (tokens, telegram_id))
        await db.commit()
        return True

async def get_users_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(telegram_id) FROM users") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def get_all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id FROM users") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def add_balance(telegram_id: int, amount: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            UPDATE users SET balance = balance + ? WHERE telegram_id = ?
        ''', (amount, telegram_id))
        await db.commit()
        return True
