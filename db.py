import sqlite3
import aiosqlite
import os

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "database.sqlite"))

# Асинхронная инициализация БД
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        # NOTE: PRAGMA synchronous is per-connection so it is set in connect() calls
        # that actually need it, rather than here where it would have no lasting effect.

        # Создание базовой таблицы, если ее вообще нет
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0
            )
        ''')

        # Миграции (добавление новых колонок).
        # Ловим только aiosqlite.OperationalError (колонка уже существует).
        # Любая другая ошибка (например, Read-Only FS) пробрасывается, чтобы
        # бот не запустился с повреждённой БД, скрыв проблему.
        migrations = [
            "ALTER TABLE users ADD COLUMN username TEXT DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN created_at TEXT DEFAULT NULL",
            "ALTER TABLE users ADD COLUMN generations_count INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0",
        ]
        for sql in migrations:
            try:
                await db.execute(sql)
            except aiosqlite.OperationalError:
                pass  # колонка уже существует — это нормально
            # все остальные исключения всплывают наверх

        # Индексы для ускорения поиска по username и created_at
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at)"
        )

        await db.commit()

async def get_balance(telegram_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE telegram_id = ?", (int(telegram_id),)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def add_user(telegram_id: int, username: str = None) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "INSERT OR IGNORE INTO users (telegram_id, balance, username, created_at, generations_count) "
            "VALUES (?, 15, ?, date('now'), 0)",
            (int(telegram_id), username)
        ) as cursor:
            await db.commit()
            return cursor.rowcount > 0

# add_tokens удалена — не используется. Для начисления баланса используйте add_balance.

async def spend_tokens(telegram_id: int, tokens: int) -> bool:
    """Атомарное списание токенов: обновление происходит только если balance >= tokens.
    Возвращает True если списание прошло успешно, False если средств не хватило.
    Исключает Race Condition при параллельных запросах одного пользователя.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "UPDATE users SET balance = balance - ?, generations_count = generations_count + 1 "
            "WHERE telegram_id = ? AND balance >= ?",
            (tokens, int(telegram_id), tokens)
        ) as cursor:
            await db.commit()
            # rowcount == 1 → обновление прошло; 0 → баланса не хватило или юзера нет
            return cursor.rowcount == 1

# get_users_count удалена — не используется. Статистика доступна через get_stats().

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
    """Возвращает список (telegram_id, username, balance) для всех пользователей."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id, username, balance FROM users ORDER BY telegram_id") as cursor:
            return await cursor.fetchall()

async def get_user_by_id_or_username(identifier: str) -> tuple[int, str | None, int] | None:
    identifier = identifier.strip()
    if identifier.startswith("@"):
        identifier = identifier[1:]
        
    async with aiosqlite.connect(DB_PATH) as db:
        if identifier.isdigit():
            async with db.execute("SELECT telegram_id, username, is_banned FROM users WHERE telegram_id = ?", (int(identifier),)) as cursor:
                return await cursor.fetchone()
        else:
            async with db.execute("SELECT telegram_id, username, is_banned FROM users WHERE username = ?", (identifier,)) as cursor:
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
