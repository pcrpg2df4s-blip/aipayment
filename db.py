import sqlite3
import aiosqlite
import os
from datetime import datetime, timedelta

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "database.sqlite"))

# Асинхронная инициализация БД
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        
        # Создание базовой таблицы, если ее вообще нет
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0
            )
        ''')

        # Миграции (добавление новых колонок).
        migrations = [
            "ALTER TABLE users ADD COLUMN username TEXT DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN created_at TEXT DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN generations_count INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0",
            
            # Новые колонки для разделения баланса
            "ALTER TABLE users ADD COLUMN permanent_balance INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN subscription_balance INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN subscription_tier TEXT DEFAULT 'free'",
            "ALTER TABLE users ADD COLUMN subscription_end_date TEXT DEFAULT NULL",
        ]
        for sql in migrations:
            try:
                await db.execute(sql)
            except aiosqlite.OperationalError:
                pass  # колонка уже существует
                
        # Переносим старый баланс в permanent_balance
        # Будет выполнено один раз (так как balance обнулится)
        try:
            await db.execute('''
                UPDATE users
                SET permanent_balance = balance, balance = 0
                WHERE balance > 0
            ''')
        except Exception:
            pass

        # Индексы
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at)")

        await db.commit()

async def get_balance(telegram_id: int) -> int:
    """Возвращает общий баланс (постоянный + подписка) с учетом ленивого сгорания."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT permanent_balance, subscription_balance, subscription_end_date "
            "FROM users WHERE telegram_id = ?", (int(telegram_id),)
        ) as cursor:
            row = await cursor.fetchone()
            
        if not row:
            return 0
            
        perm_bal, sub_bal, sub_end = row
        
        # Ленивая проверка истечения подписки
        if sub_bal > 0 and sub_end:
            end_date = datetime.fromisoformat(sub_end)
            if datetime.now() > end_date:
                sub_bal = 0
                await db.execute(
                    "UPDATE users SET subscription_balance = 0, subscription_tier = 'free', subscription_end_date = NULL "
                    "WHERE telegram_id = ?", (int(telegram_id),)
                )
                await db.commit()
                
        return perm_bal + sub_bal

async def add_user(telegram_id: int, username: str = None) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "INSERT OR IGNORE INTO users (telegram_id, permanent_balance, username, created_at, generations_count) "
            "VALUES (?, 15, ?, date('now'), 0)",
            (int(telegram_id), username)
        ) as cursor:
            await db.commit()
            return cursor.rowcount > 0

async def spend_tokens(telegram_id: int, tokens: int) -> bool:
    """Атомарное списание токенов с учетом подписки и постоянного баланса.
    Использует эксклюзивную транзакцию для предотвращения Race Condition."""
    async with aiosqlite.connect(DB_PATH, isolation_level=None) as db:
        await db.execute("BEGIN EXCLUSIVE")
        try:
            async with db.execute(
                "SELECT permanent_balance, subscription_balance, subscription_end_date "
                "FROM users WHERE telegram_id = ?", (int(telegram_id),)
            ) as cursor:
                row = await cursor.fetchone()
                
            if not row:
                await db.rollback()
                return False
                
            perm_bal, sub_bal, sub_end = row
            
            # Ленивое сгорание
            if sub_bal > 0 and sub_end:
                end_date = datetime.fromisoformat(sub_end)
                if datetime.now() > end_date:
                    sub_bal = 0
                    await db.execute(
                        "UPDATE users SET subscription_balance = 0, subscription_tier = 'free', subscription_end_date = NULL "
                        "WHERE telegram_id = ?", (int(telegram_id),)
                    )

            if (perm_bal + sub_bal) < tokens:
                await db.commit() # Сохраняем обнуление подписки (если было)
                return False
                
            new_sub_bal = sub_bal
            new_perm_bal = perm_bal
            remaining = tokens
            
            # Сначала списываем из подписки
            if new_sub_bal >= remaining:
                new_sub_bal -= remaining
                remaining = 0
            else:
                remaining -= new_sub_bal
                new_sub_bal = 0
                
            # Остаток списываем из постоянного баланса
            if remaining > 0:
                new_perm_bal -= remaining
                
            await db.execute(
                "UPDATE users SET permanent_balance = ?, subscription_balance = ?, generations_count = generations_count + 1 "
                "WHERE telegram_id = ?", (new_perm_bal, new_sub_bal, int(telegram_id))
            )
            await db.commit()
            return True
            
        except Exception:
            await db.rollback()
            raise

async def get_all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id FROM users") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def add_balance(telegram_id: int, amount: int, is_subscription: bool = False, tier: str = 'free', days: int = 30) -> bool:
    """Начисление токенов: либо на постоянный, либо на подписку."""
    async with aiosqlite.connect(DB_PATH, isolation_level=None) as db:
        await db.execute("BEGIN EXCLUSIVE")
        try:
            if not is_subscription:
                await db.execute(
                    "UPDATE users SET permanent_balance = permanent_balance + ? WHERE telegram_id = ?", 
                    (amount, telegram_id)
                )
            else:
                async with db.execute("SELECT subscription_end_date FROM users WHERE telegram_id = ?", (int(telegram_id),)) as cursor:
                    row = await cursor.fetchone()
                    
                if not row:
                    await db.rollback()
                    return False
                    
                sub_end_str = row[0]
                now = datetime.now()
                
                # Расчет новой даты (стакаем, если активна)
                if sub_end_str:
                    current_end = datetime.fromisoformat(sub_end_str)
                    if current_end > now:
                        new_end = current_end + timedelta(days=days)
                    else:
                        new_end = now + timedelta(days=days)
                else:
                    new_end = now + timedelta(days=days)
                    
                await db.execute(
                    "UPDATE users SET subscription_balance = subscription_balance + ?, subscription_tier = ?, subscription_end_date = ? "
                    "WHERE telegram_id = ?",
                    (amount, tier, new_end.isoformat(), int(telegram_id))
                )
                
            await db.commit()
            return True
            
        except Exception:
            await db.rollback()
            raise

async def get_stats() -> tuple[int, int, int]:
    """Возвращает (всего юзеров, новых сегодня, всего генераций)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE created_at = date('now')"
        ) as cur:
            today = (await cur.fetchone())[0]
        async with db.execute("SELECT COALESCE(SUM(generations_count), 0) FROM users") as cur:
            gens = (await cur.fetchone())[0]
    return total, today, gens

async def get_all_users() -> list[tuple[int, str | None, int]]:
    """Возвращает список (telegram_id, username, total_balance) для всех пользователей."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Для админки просто складываем два баланса (без ленивого сброса, так как это тяжелый запрос)
        async with db.execute(
            "SELECT telegram_id, username, (permanent_balance + subscription_balance) as tot_bal "
            "FROM users ORDER BY telegram_id"
        ) as cursor:
            return await cursor.fetchall()

async def get_user_by_id_or_username(identifier: str) -> tuple[int, str | None, int] | None:
    identifier = identifier.strip()
    if identifier.startswith("@"):
        identifier = identifier[1:]
        
    async with aiosqlite.connect(DB_PATH) as db:
        query = "SELECT telegram_id, username, is_banned FROM users WHERE "
        param = identifier
        if identifier.isdigit():
            query += "telegram_id = ?"
            param = int(identifier)
        else:
            query += "username = ?"
            
        async with db.execute(query, (param,)) as cursor:
            return await cursor.fetchone()

async def toggle_user_ban(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_banned FROM users WHERE telegram_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return 0
            new_status = 0 if row[0] else 1
            await db.execute("UPDATE users SET is_banned = ? WHERE telegram_id = ?", (new_status, user_id))
            await db.commit()
            return new_status

async def is_user_banned(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            async with db.execute("SELECT is_banned FROM users WHERE telegram_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                return bool(row[0]) if row else False
        except Exception:
            return False
