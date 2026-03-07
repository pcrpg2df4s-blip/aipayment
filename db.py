import sqlite3
import aiosqlite
import os
from datetime import datetime, timedelta

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "database.sqlite"))

_connection = None

# Асинхронная инициализация БД
async def init_db():
    global _connection
    if _connection is None:
        _connection = await aiosqlite.connect(DB_PATH)
        await _connection.execute("PRAGMA journal_mode=WAL;")
        await _connection.execute("PRAGMA synchronous=NORMAL;")
        
        # Создание базовой таблицы, если ее вообще нет
        await _connection.execute('''
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0
            )
        ''')

        # Таблица промокодов
        await _connection.execute('''
            CREATE TABLE IF NOT EXISTS promocodes (
                code TEXT UNIQUE,
                reward INTEGER,
                max_activations INTEGER,
                current_activations INTEGER DEFAULT 0
            )
        ''')

        # История активаций промокодов
        await _connection.execute('''
            CREATE TABLE IF NOT EXISTS promocode_activations (
                user_id INTEGER,
                code TEXT,
                activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Таблица логов оплат
        await _connection.execute('''
            CREATE TABLE IF NOT EXISTS payment_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                currency TEXT,
                method TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                await _connection.execute(sql)
            except aiosqlite.OperationalError:
                pass  # колонка уже существует
                
        # Переносим старый баланс в permanent_balance
        # переносим старый баланс в permanent_balance
        try:
            await _connection.execute('''
                UPDATE users
                SET permanent_balance = balance, balance = 0
                WHERE balance > 0
            ''')
        except Exception:
            pass

        # Индексы
        await _connection.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        await _connection.execute("CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at)")

        await _connection.commit()

async def get_balance(telegram_id: int) -> int:
    """Возвращает общий баланс (постоянный + подписка) с учетом ленивого сгорания."""
    global _connection
    async with _connection.execute(
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
            await _connection.execute(
                "UPDATE users SET subscription_balance = 0, subscription_tier = 'free', subscription_end_date = NULL "
                "WHERE telegram_id = ?", (int(telegram_id),)
            )
            await _connection.commit()
            
    return perm_bal + sub_bal

async def get_user_profile(telegram_id: int) -> tuple[int, str, str | None, str | None]:
    """Возвращает (общий баланс, уровень подписки, дата окончания, payment_method_id) с учетом ленивого сгорания."""
    global _connection
    async with _connection.execute(
        "SELECT permanent_balance, subscription_balance, subscription_tier, subscription_end_date, payment_method_id "
        "FROM users WHERE telegram_id = ?", (int(telegram_id),)
    ) as cursor:
        row = await cursor.fetchone()
        
    if not row:
        return 0, 'free', None, None
        
    perm_bal, sub_bal, tier, sub_end, payment_method_id = row
    
    # Ленивая проверка истечения подписки
    if sub_bal > 0 and sub_end:
        end_date = datetime.fromisoformat(sub_end)
        if datetime.now() > end_date:
            sub_bal = 0
            tier = 'free'
            sub_end = None
            payment_method_id = None
            await _connection.execute(
                "UPDATE users SET subscription_balance = 0, subscription_tier = 'free', subscription_end_date = NULL, payment_method_id = NULL "
                "WHERE telegram_id = ?", (int(telegram_id),)
            )
            await _connection.commit()
            
    return perm_bal + sub_bal, tier, sub_end, payment_method_id

async def add_user(telegram_id: int, username: str = None) -> bool:
    global _connection
    async with _connection.execute(
        "INSERT OR IGNORE INTO users (telegram_id, permanent_balance, username, created_at, generations_count) "
        "VALUES (?, 30, ?, date('now', 'localtime'), 0)",
        (int(telegram_id), username)
    ) as cursor:
        await _connection.commit()
        return cursor.rowcount > 0

async def spend_tokens(telegram_id: int, tokens: int) -> bool:
    """Атомарное списание токенов с учетом подписки и постоянного баланса.
    Использует эксклюзивную транзакцию для предотвращения Race Condition."""
    global _connection
    await _connection.execute("BEGIN EXCLUSIVE")
    try:
        async with _connection.execute(
            "SELECT permanent_balance, subscription_balance, subscription_end_date "
            "FROM users WHERE telegram_id = ?", (int(telegram_id),)
        ) as cursor:
            row = await cursor.fetchone()
            
        if not row:
            await _connection.rollback()
            return False
            
        perm_bal, sub_bal, sub_end = row
        
        # Ленивое сгорание
        if sub_bal > 0 and sub_end:
            end_date = datetime.fromisoformat(sub_end)
            if datetime.now() > end_date:
                sub_bal = 0
                await _connection.execute(
                    "UPDATE users SET subscription_balance = 0, subscription_tier = 'free', subscription_end_date = NULL "
                    "WHERE telegram_id = ?", (int(telegram_id),)
                )

        if (perm_bal + sub_bal) < tokens:
            await _connection.commit() # Сохраняем обнуление подписки (если было)
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
            
        await _connection.execute(
            "UPDATE users SET permanent_balance = ?, subscription_balance = ?, generations_count = generations_count + 1 "
            "WHERE telegram_id = ?", (new_perm_bal, new_sub_bal, int(telegram_id))
        )
        await _connection.commit()
        return True
        
    except Exception:
        await _connection.rollback()
        raise

async def get_all_user_ids() -> list[int]:
    global _connection
    async with _connection.execute("SELECT telegram_id FROM users") as cursor:
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
    global _connection
    async with _connection.execute("SELECT COUNT(*) FROM users") as cur:
        total = (await cur.fetchone())[0]
    async with _connection.execute(
        "SELECT COUNT(*) FROM users WHERE created_at = date('now', 'localtime')"
    ) as cur:
        today = (await cur.fetchone())[0]
    async with _connection.execute("SELECT COALESCE(SUM(generations_count), 0) FROM users") as cur:
        gens = (await cur.fetchone())[0]
    return total, today, gens

async def get_all_users() -> list[tuple[int, str | None, int]]:
    """Возвращает список (telegram_id, username, total_balance) для всех пользователей."""
    global _connection
    # Для админки просто складываем два баланса (без ленивого сброса, так как это тяжелый запрос)
    async with _connection.execute(
        "SELECT telegram_id, username, (permanent_balance + subscription_balance) as tot_bal "
        "FROM users ORDER BY telegram_id"
    ) as cursor:
        return await cursor.fetchall()

async def get_users_by_filter(filter_type: str) -> list[tuple[int, str | None, int]]:
    """Возвращает список пользователей по временному фильтру или VIP-статусу."""
    global _connection
    query = "SELECT telegram_id, username, (permanent_balance + subscription_balance) as tot_bal FROM users"
    
    if filter_type == "day":
        query += " WHERE created_at >= date('now', 'localtime', '-1 day')"
    elif filter_type == "week":
        query += " WHERE created_at >= date('now', 'localtime', '-7 days')"
    elif filter_type == "month":
        query += " WHERE created_at >= date('now', 'localtime', '-1 month')"
    elif filter_type == "vip":
        query += " WHERE subscription_end_date > datetime('now', 'localtime')"
    
    query += " ORDER BY telegram_id"
    
    async with _connection.execute(query) as cursor:
        return await cursor.fetchall()

async def get_user_by_id_or_username(identifier: str) -> tuple[int, str | None, int] | None:
    identifier = identifier.strip()
    if identifier.startswith("@"):
        identifier = identifier[1:]
        
    global _connection
    query = "SELECT telegram_id, username, is_banned FROM users WHERE "
    param = identifier
    if identifier.isdigit():
        query += "telegram_id = ?"
        param = int(identifier)
    else:
        query += "username = ?"
        
    async with _connection.execute(query, (param,)) as cursor:
        return await cursor.fetchone()

async def toggle_user_ban(user_id: int) -> int:
    global _connection
    async with _connection.execute("SELECT is_banned FROM users WHERE telegram_id = ?", (user_id,)) as cursor:
        row = await cursor.fetchone()
        if not row:
            return 0
        new_status = 0 if row[0] else 1
        await _connection.execute("UPDATE users SET is_banned = ? WHERE telegram_id = ?", (new_status, user_id))
        await _connection.commit()
        return new_status

async def is_user_banned(user_id: int) -> bool:
    global _connection
    try:
        async with _connection.execute("SELECT is_banned FROM users WHERE telegram_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return bool(row[0]) if row else False
    except Exception:
        return False

async def add_promocode(code: str, reward: int, limit: int) -> bool:
    global _connection
    try:
        await _connection.execute(
            "INSERT INTO promocodes (code, reward, max_activations, current_activations) VALUES (?, ?, ?, 0)",
            (code, reward, limit)
        )
        await _connection.commit()
        return True
    except aiosqlite.IntegrityError:
        return False
            
async def activate_promocode(user_id: int, code: str) -> tuple[bool, str | int]:
    global _connection
    await _connection.execute("BEGIN EXCLUSIVE")
    try:
        async with _connection.execute(
            "SELECT reward, max_activations, current_activations FROM promocodes WHERE code = ?",
            (code,)
        ) as cursor:
            promo = await cursor.fetchone()
            
        if not promo:
            await _connection.rollback()
            return False, "Промокод не найден."
            
        reward, max_act, curr_act = promo
        
        if curr_act >= max_act:
            await _connection.rollback()
            return False, "Лимит активаций этого промокода исчерпан."
            
        async with _connection.execute(
            "SELECT 1 FROM promocode_activations WHERE user_id = ? AND code = ?",
            (user_id, code)
        ) as cursor:
            activation = await cursor.fetchone()
            
        if activation:
            await _connection.rollback()
            return False, "Вы уже активировали этот промокод."
            
        await _connection.execute(
            "UPDATE promocodes SET current_activations = current_activations + 1 WHERE code = ?",
            (code,)
        )
        await _connection.execute(
            "INSERT INTO promocode_activations (user_id, code) VALUES (?, ?)",
            (user_id, code)
        )
        
        await _connection.execute(
            "UPDATE users SET permanent_balance = permanent_balance + ? WHERE telegram_id = ?",
            (reward, user_id)
        )
        
        await _connection.commit()
        return True, reward
        
    except Exception as e:
        await _connection.rollback()
        return False, f"Внутренняя ошибка: {e}"

async def log_payment(user_id: int, amount: float, currency: str, method: str):
    global _connection
    await _connection.execute(
        "INSERT INTO payment_logs (user_id, amount, currency, method) VALUES (?, ?, ?, ?)",
        (user_id, amount, currency, method)
    )
    await _connection.commit()

async def cancel_subscription(telegram_id: int) -> bool:
    """Отменяет автопродление подписки, обнуляя payment_method_id."""
    global _connection
    async with _connection.execute(
        "UPDATE users SET payment_method_id = NULL WHERE telegram_id = ?",
        (int(telegram_id),)
    ) as cursor:
        await _connection.commit()
        return cursor.rowcount > 0

async def activate_stars_subscription(telegram_id: int, days: int) -> bool:
    """Атомарно продлевает или активирует подписку за Stars."""
    global _connection
    await _connection.execute("BEGIN EXCLUSIVE")
    try:
        async with _connection.execute("SELECT subscription_end_date FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            row = await cursor.fetchone()
            
        now = datetime.now()
        current_end = None
        if row and row[0]:
            try:
                current_end = datetime.fromisoformat(row[0])
            except ValueError:
                pass
        
        if current_end and current_end > now:
            new_end = current_end + timedelta(days=days)
        else:
            new_end = now + timedelta(days=days)
            
        await _connection.execute(
            "UPDATE users SET subscription_end_date = ? WHERE telegram_id = ?",
            (new_end.isoformat(), telegram_id)
        )
        await _connection.commit()
        return True
    except Exception:
        await _connection.rollback()
        raise

async def close_db():
    global _connection
    if _connection:
        await _connection.close()
        _connection = None
