import aiosqlite
import os
from datetime import datetime, timedelta

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "database.sqlite"))

_connection = None

async def get_db():
    global _connection
    if _connection is None:
        await init_db()
    return _connection

async def close_db():
    global _connection
    if _connection is not None:
        try:
            await _connection.close()
        except Exception:
            pass
        _connection = None

# Асинхронная инициализация БД
async def init_db():
    global _connection
    if _connection is None:
        _connection = await aiosqlite.connect(DB_PATH, timeout=15.0)
        await _connection.execute("PRAGMA journal_mode=WAL;")
        await _connection.execute("PRAGMA synchronous=NORMAL;")
        await _connection.execute("PRAGMA wal_autocheckpoint=50;")
        await _connection.execute("PRAGMA busy_timeout = 15000;")
        
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

            # Идемпотентность: уникальный ID платежа в логах
            "ALTER TABLE payment_logs ADD COLUMN payment_id TEXT DEFAULT NULL",

            # Источник трафика (deep link аргумент /start)
            "ALTER TABLE users ADD COLUMN source TEXT DEFAULT NULL",

            # Использовал ли пользователь пробный период
            "ALTER TABLE users ADD COLUMN has_used_trial INTEGER DEFAULT 0",

            # Время последнего получения ежедневного бонуса
            "ALTER TABLE users ADD COLUMN last_daily_bonus_claim TEXT DEFAULT NULL",

            # Просмотрел ли пользователь видео-инструкцию для ИИ поиска
            "ALTER TABLE users ADD COLUMN has_seen_ai_search_video INTEGER DEFAULT 0",

            # Время активации подписки за 1 рубль (для ограничения видео на 1 день)
            "ALTER TABLE users ADD COLUMN trial_activated_at TEXT DEFAULT NULL",
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
        await _connection.execute("CREATE INDEX IF NOT EXISTS idx_payment_logs_payment_id ON payment_logs(payment_id)")
        await _connection.execute("CREATE INDEX IF NOT EXISTS idx_users_sub_end ON users(subscription_end_date, payment_method_id)")

        # Таблица транзакций (история изменений баланса)
        await _connection.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                description TEXT,
                created_at TEXT
            )
        ''')
        await _connection.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id)")

        # Backfill promocode activations if transactions table is empty
        try:
            async with _connection.execute("SELECT COUNT(*) FROM transactions") as cursor:
                row = await cursor.fetchone()
                count = row[0] if row else 0
            if count == 0:
                await _connection.execute('''
                    INSERT INTO transactions (user_id, amount, description, created_at)
                    SELECT pa.user_id, p.reward, 'Промокод: ' || pa.code, pa.activated_at
                    FROM promocode_activations pa
                    JOIN promocodes p ON pa.code = p.code
                ''')
        except Exception:
            pass

        await _connection.commit()

async def get_balance(telegram_id: int) -> int:
    """Возвращает общий баланс (постоянный + подписка) с учетом ленивого сгорания."""
    conn = await get_db()
    async with conn.execute(
        "SELECT permanent_balance, subscription_balance, subscription_end_date, payment_method_id "
        "FROM users WHERE telegram_id = ?", (int(telegram_id),)
    ) as cursor:
        row = await cursor.fetchone()
        
    if not row:
        return 0
        
    perm_bal, sub_bal, sub_end, payment_method_id = row
    
    # Ленивая проверка истечения подписки
    if sub_end:
        end_date = datetime.fromisoformat(sub_end)
        if datetime.now() > end_date:
            sub_bal = 0
            if payment_method_id is None:
                # Подписка отменена и закончилась: очищаем всё полностью
                await conn.execute(
                    "UPDATE users SET subscription_balance = 0, subscription_tier = 'free', subscription_end_date = NULL "
                    "WHERE telegram_id = ?", (int(telegram_id),)
                )
            else:
                # Подписка активна (ждет автопродления): сгорает только баланс токенов подписки
                await conn.execute(
                    "UPDATE users SET subscription_balance = 0 "
                    "WHERE telegram_id = ?", (int(telegram_id),)
                )
            await conn.commit()
            
    return perm_bal + sub_bal

async def get_user_profile(telegram_id: int) -> tuple[int, str, str | None, str | None]:
    """Возвращает (общий баланс, уровень подписки, дата окончания, payment_method_id) с учетом ленивого сгорания."""
    conn = await get_db()
    async with conn.execute(
        "SELECT permanent_balance, subscription_balance, subscription_tier, subscription_end_date, payment_method_id "
        "FROM users WHERE telegram_id = ?", (int(telegram_id),)
    ) as cursor:
        row = await cursor.fetchone()
        
    if not row:
        return 0, 'free', None, None
        
    perm_bal, sub_bal, tier, sub_end, payment_method_id = row
    
    # Ленивая проверка истечения подписки
    if sub_end:
        end_date = datetime.fromisoformat(sub_end)
        if datetime.now() > end_date:
            sub_bal = 0
            if payment_method_id is None:
                # Подписка отменена и закончилась: очищаем всё полностью
                tier = 'free'
                sub_end = None
                await conn.execute(
                    "UPDATE users SET subscription_balance = 0, subscription_tier = 'free', subscription_end_date = NULL "
                    "WHERE telegram_id = ?", (int(telegram_id),)
                )
            else:
                # Подписка активна (ждет автопродления): сгорает только баланс токенов подписки,
                # сохраняем tier и end_date для checker.py.
                await conn.execute(
                    "UPDATE users SET subscription_balance = 0 "
                    "WHERE telegram_id = ?", (int(telegram_id),)
                )
            await conn.commit()
            
    return perm_bal + sub_bal, tier, sub_end, payment_method_id

async def add_user(telegram_id: int, username: str = None, source: str = None) -> bool:
    global _connection
    async with _connection.execute(
        "INSERT OR IGNORE INTO users (telegram_id, permanent_balance, username, created_at, generations_count, source) "
        "VALUES (?, 30, ?, date('now', 'localtime'), 0, ?)",
        (int(telegram_id), username, source)
    ) as cursor:
        await _connection.commit()
        inserted = cursor.rowcount > 0
        
    if not inserted and username is not None:
        await _connection.execute(
            "UPDATE users SET username = ? WHERE telegram_id = ?",
            (username, int(telegram_id))
        )
        await _connection.commit()
        
    return inserted

async def spend_tokens(telegram_id: int, tokens: int, description: str = "Генерация") -> bool:
    """Атомарное списание токенов с учетом подписки и постоянного баланса.
    Использует эксклюзивную транзакцию для предотвращения Race Condition."""
    async with aiosqlite.connect(DB_PATH, isolation_level=None, timeout=10.0) as db:
        await db.execute("PRAGMA busy_timeout = 10000;")
        await db.execute("BEGIN EXCLUSIVE")
        try:
            async with db.execute(
                "SELECT permanent_balance, subscription_balance, subscription_end_date, payment_method_id "
                "FROM users WHERE telegram_id = ?", (int(telegram_id),)
            ) as cursor:
                row = await cursor.fetchone()
                
            if not row:
                try:
                    await db.execute("ROLLBACK")
                except Exception:
                    pass
                return False
                
            perm_bal, sub_bal, sub_end, payment_method_id = row
            
            # Ленивое сгорание
            if sub_end:
                end_date = datetime.fromisoformat(sub_end)
                if datetime.now() > end_date:
                    sub_bal = 0
                    if payment_method_id is None:
                        await db.execute(
                            "UPDATE users SET subscription_balance = 0, subscription_tier = 'free', subscription_end_date = NULL "
                            "WHERE telegram_id = ?", (int(telegram_id),)
                        )
                    else:
                        await db.execute(
                            "UPDATE users SET subscription_balance = 0 "
                            "WHERE telegram_id = ?", (int(telegram_id),)
                        )

            if (perm_bal + sub_bal) < tokens:
                await db.execute("COMMIT") # Сохраняем обнуление подписки (если было)
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
            
            # Логируем транзакцию списания
            await db.execute(
                "INSERT INTO transactions (user_id, amount, description, created_at) VALUES (?, ?, ?, ?)",
                (int(telegram_id), -tokens, description, datetime.now().isoformat())
            )
            
            await db.execute("COMMIT")
            return True
            
        except Exception:
            try:
                await db.execute("ROLLBACK")
            except Exception:
                pass
            raise

async def get_all_user_ids() -> list[int]:
    global _connection
    async with _connection.execute("SELECT telegram_id FROM users") as cursor:
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

async def add_balance(telegram_id: int, amount: int, is_subscription: bool = False, tier: str = 'free', days: int = 30, payment_method_id: str = None, description: str = "Пополнение баланса") -> bool:
    """Начисление токенов: либо на постоянный, либо на подписку."""
    async with aiosqlite.connect(DB_PATH, isolation_level=None, timeout=10.0) as db:
        await db.execute("PRAGMA busy_timeout = 10000;")
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
                    try:
                        await db.execute("ROLLBACK")
                    except Exception:
                        pass
                    return False
                    
                sub_end_str = row[0]
                now = datetime.now()
                
                # Расчет новой даты (стакаем, если активна)
                is_active = False
                if sub_end_str:
                    current_end = datetime.fromisoformat(sub_end_str)
                    if current_end > now:
                        new_end = current_end + timedelta(days=days)
                        is_active = True
                    else:
                        new_end = now + timedelta(days=days)
                else:
                    new_end = now + timedelta(days=days)
                    
                if is_active:
                    # Подписка еще активна: продлеваем и суммируем баланс
                    await db.execute(
                        "UPDATE users SET subscription_balance = subscription_balance + ?, subscription_tier = ?, subscription_end_date = ?, "
                        "payment_method_id = CASE WHEN ? IS NOT NULL THEN ? ELSE payment_method_id END "
                        "WHERE telegram_id = ?",
                        (amount, tier, new_end.isoformat(), payment_method_id, payment_method_id, int(telegram_id))
                    )
                else:
                    # Подписки не было или она истекла: старый баланс сгорает, устанавливаем новый
                    await db.execute(
                        "UPDATE users SET subscription_balance = ?, subscription_tier = ?, subscription_end_date = ?, "
                        "payment_method_id = CASE WHEN ? IS NOT NULL THEN ? ELSE payment_method_id END "
                        "WHERE telegram_id = ?",
                        (amount, tier, new_end.isoformat(), payment_method_id, payment_method_id, int(telegram_id))
                    )
                
            # Логируем транзакцию начисления
            await db.execute(
                "INSERT INTO transactions (user_id, amount, description, created_at) VALUES (?, ?, ?, ?)",
                (int(telegram_id), amount, description, datetime.now().isoformat())
            )
                
            await db.execute("COMMIT")
            return True
            
        except Exception:
            try:
                await db.execute("ROLLBACK")
            except Exception:
                pass
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
        # created_at хранится как DATE ('YYYY-MM-DD'), поэтому сравниваем точно с сегодня
        query += " WHERE created_at = date('now', 'localtime')"
    elif filter_type == "week":
        # -6 days → сегодня + 6 предыдущих дней = ровно 7 дней
        query += " WHERE created_at >= date('now', 'localtime', '-6 days')"
    elif filter_type == "month":
        # -29 days → сегодня + 29 предыдущих дней = ровно 30 дней
        query += " WHERE created_at >= date('now', 'localtime', '-29 days')"
    elif filter_type == "vip":
        query += " WHERE subscription_end_date > datetime('now', 'localtime')"
    # filter_type == "all" — без WHERE, возвращаем всех

    # Сортировка: новые пользователи сверху; VIP и все-время — тоже по дате регистрации
    if filter_type == "vip":
        query += " ORDER BY telegram_id"
    else:
        query += " ORDER BY created_at DESC, telegram_id DESC"

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

async def get_full_user_info(identifier: str) -> dict | None:
    identifier = identifier.strip()
    if identifier.startswith("@"):
        identifier = identifier[1:]
        
    global _connection
    query = (
        "SELECT telegram_id, username, created_at, generations_count, is_banned, "
        "permanent_balance, subscription_balance, subscription_tier, subscription_end_date, "
        "payment_method_id, source, has_used_trial, last_daily_bonus_claim "
        "FROM users WHERE "
    )
    if identifier.isdigit():
        query += "telegram_id = ?"
        param = int(identifier)
    else:
        query += "LOWER(username) = LOWER(?)"
        param = identifier
        
    async with _connection.execute(query, (param,)) as cursor:
        row = await cursor.fetchone()
        
    if not row:
        return None
        
    (
        telegram_id, username, created_at, generations_count, is_banned,
        perm_bal, sub_bal, tier, sub_end, payment_method_id, source,
        has_used_trial, last_daily_bonus_claim
    ) = row
    
    # Ленивая проверка истечения подписки
    if sub_end:
        try:
            end_date = datetime.fromisoformat(sub_end)
            if datetime.now() > end_date:
                sub_bal = 0
                if payment_method_id is None:
                    tier = 'free'
                    sub_end = None
                    await _connection.execute(
                        "UPDATE users SET subscription_balance = 0, subscription_tier = 'free', subscription_end_date = NULL "
                        "WHERE telegram_id = ?", (telegram_id,)
                    )
                else:
                    await _connection.execute(
                        "UPDATE users SET subscription_balance = 0 "
                        "WHERE telegram_id = ?", (telegram_id,)
                    )
                await _connection.commit()
        except Exception:
            pass

    pay_count = 0
    pay_sum = 0.0
    try:
        async with _connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM payment_logs WHERE user_id = ?",
            (telegram_id,)
        ) as cur:
            p_row = await cur.fetchone()
            if p_row:
                pay_count, pay_sum = p_row[0], float(p_row[1])
    except Exception:
        pass

    return {
        "telegram_id": telegram_id,
        "username": username,
        "created_at": created_at,
        "generations_count": generations_count or 0,
        "is_banned": bool(is_banned),
        "permanent_balance": perm_bal or 0,
        "subscription_balance": sub_bal or 0,
        "total_balance": (perm_bal or 0) + (sub_bal or 0),
        "subscription_tier": tier or 'free',
        "subscription_end_date": sub_end,
        "payment_method_id": payment_method_id,
        "source": source,
        "has_used_trial": bool(has_used_trial),
        "last_daily_bonus_claim": last_daily_bonus_claim,
        "payments_count": pay_count,
        "payments_sum": pay_sum,
    }

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
    async with aiosqlite.connect(DB_PATH, isolation_level=None, timeout=10.0) as db:
        await db.execute("PRAGMA busy_timeout = 10000;")
        await db.execute("BEGIN EXCLUSIVE")
        try:
            async with db.execute(
                "SELECT reward, max_activations, current_activations FROM promocodes WHERE code = ?",
                (code,)
            ) as cursor:
                promo = await cursor.fetchone()
                
            if not promo:
                try:
                    await db.execute("ROLLBACK")
                except Exception:
                    pass
                return False, "Промокод не найден."
                
            reward, max_act, curr_act = promo
            
            if curr_act >= max_act:
                try:
                    await db.execute("ROLLBACK")
                except Exception:
                    pass
                return False, "Лимит активаций этого промокода исчерпан."
                
            async with db.execute(
                "SELECT 1 FROM promocode_activations WHERE user_id = ? AND code = ?",
                (user_id, code)
            ) as cursor:
                activation = await cursor.fetchone()
                
            if activation:
                try:
                    await db.execute("ROLLBACK")
                except Exception:
                    pass
                return False, "Вы уже активировали этот промокод."
                
            await db.execute(
                "UPDATE promocodes SET current_activations = current_activations + 1 WHERE code = ?",
                (code,)
            )
            await db.execute(
                "INSERT INTO promocode_activations (user_id, code) VALUES (?, ?)",
                (user_id, code)
            )
            
            await db.execute(
                "UPDATE users SET permanent_balance = permanent_balance + ? WHERE telegram_id = ?",
                (reward, user_id)
            )
            
            # Логируем транзакцию промокода
            await db.execute(
                "INSERT INTO transactions (user_id, amount, description, created_at) VALUES (?, ?, ?, ?)",
                (user_id, reward, f"Промокод: {code}", datetime.now().isoformat())
            )
            
            await db.execute("COMMIT")
            return True, reward
            
        except Exception as e:
            try:
                await db.execute("ROLLBACK")
            except Exception:
                pass
            return False, f"Внутренняя ошибка: {e}"

async def log_payment(user_id: int, amount: float, currency: str, method: str, payment_id: str = None):
    conn = await get_db()
    await conn.execute(
        "INSERT INTO payment_logs (user_id, amount, currency, method, payment_id) VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, currency, method, payment_id)
    )
    await conn.commit()

async def is_payment_processed(payment_id: str) -> bool:
    """Возвращает True, если платеж с таким ID уже был обработан (защита от дублей)."""
    conn = await get_db()
    async with conn.execute(
        "SELECT 1 FROM payment_logs WHERE payment_id = ? LIMIT 1",
        (payment_id,)
    ) as cursor:
        row = await cursor.fetchone()
    return row is not None

async def cancel_subscription(telegram_id: int) -> bool:
    """Отменяет автопродление подписки, обнуляя payment_method_id."""
    async with aiosqlite.connect(DB_PATH, timeout=10.0) as db:
        await db.execute("PRAGMA busy_timeout = 10000;")
        async with db.execute(
            "UPDATE users SET payment_method_id = NULL WHERE telegram_id = ?",
            (int(telegram_id),)
        ) as cursor:
            await db.commit()
            return cursor.rowcount > 0

async def activate_stars_subscription(telegram_id: int, days: int) -> bool:
    """Атомарно продлевает или активирует подписку за Stars."""
    async with aiosqlite.connect(DB_PATH, isolation_level=None, timeout=10.0) as db:
        await db.execute("PRAGMA busy_timeout = 10000;")
        await db.execute("BEGIN EXCLUSIVE")
        try:
            async with db.execute("SELECT subscription_end_date FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
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
                
            await db.execute(
                "UPDATE users SET subscription_end_date = ? WHERE telegram_id = ?",
                (new_end.isoformat(), telegram_id)
            )
            await db.execute("COMMIT")
            return True
        except Exception:
            try:
                await db.execute("ROLLBACK")
            except Exception:
                pass
            raise

async def check_trial_used(telegram_id: int) -> bool:
    """Проверяет, использовал ли пользователь пробный период (1 рубль)."""
    global _connection
    if _connection is None:
        async with aiosqlite.connect(DB_PATH, timeout=10.0) as db:
            async with db.execute("SELECT has_used_trial FROM users WHERE telegram_id = ?", (int(telegram_id),)) as cursor:
                row = await cursor.fetchone()
                return bool(row and row[0])
    else:
        async with _connection.execute("SELECT has_used_trial FROM users WHERE telegram_id = ?", (int(telegram_id),)) as cursor:
            row = await cursor.fetchone()
            return bool(row and row[0])

async def set_trial_used(telegram_id: int) -> None:
    """Отмечает, что пользователь уже использовал пробный период."""
    global _connection
    if _connection is None:
        async with aiosqlite.connect(DB_PATH, timeout=10.0) as db:
            await db.execute("UPDATE users SET has_used_trial = 1 WHERE telegram_id = ?", (int(telegram_id),))
            await db.commit()
    else:
        await _connection.execute("UPDATE users SET has_used_trial = 1 WHERE telegram_id = ?", (int(telegram_id),))
        await _connection.commit()

async def set_trial_activated(telegram_id: int) -> None:
    """Записывает время активации подписки за 1 рубль для ограничения видео на первый день."""
    now_iso = datetime.now().isoformat()
    global _connection
    if _connection is None:
        async with aiosqlite.connect(DB_PATH, timeout=10.0) as db:
            await db.execute("UPDATE users SET trial_activated_at = ? WHERE telegram_id = ?", (now_iso, int(telegram_id)))
            await db.commit()
    else:
        await _connection.execute("UPDATE users SET trial_activated_at = ? WHERE telegram_id = ?", (now_iso, int(telegram_id)))
        await _connection.commit()

async def clear_trial_activated(telegram_id: int) -> None:
    """Сбрасывает ограничение генерации видео при полноценной оплате подписки."""
    global _connection
    if _connection is None:
        async with aiosqlite.connect(DB_PATH, timeout=10.0) as db:
            await db.execute("UPDATE users SET trial_activated_at = NULL WHERE telegram_id = ?", (int(telegram_id),))
            await db.commit()
    else:
        await _connection.execute("UPDATE users SET trial_activated_at = NULL WHERE telegram_id = ?", (int(telegram_id),))
        await _connection.commit()

async def can_generate_video(telegram_id: int, video_cost: int = 0) -> bool:
    """
    Проверяет, разрешена ли пользователю генерация видео на указанное количество токенов.
    При подписке за 1 рубль первые 150 триальных токенов и 30 приветственных токенов
    недоступны для генерации видео в первые 24 часа. Докупленные сверху токены использовать МОЖНО.
    """
    global _connection
    if _connection is None:
        async with aiosqlite.connect(DB_PATH, timeout=10.0) as db:
            async with db.execute(
                "SELECT trial_activated_at, permanent_balance, subscription_balance FROM users WHERE telegram_id = ?",
                (int(telegram_id),)
            ) as cursor:
                row = await cursor.fetchone()
    else:
        async with _connection.execute(
            "SELECT trial_activated_at, permanent_balance, subscription_balance FROM users WHERE telegram_id = ?",
            (int(telegram_id),)
        ) as cursor:
            row = await cursor.fetchone()

    if not row or not row[0]:
        return True

    trial_activated_str = row[0]
    perm_bal = row[1] if (len(row) > 1 and row[1] is not None) else 0
    sub_bal = row[2] if (len(row) > 2 and row[2] is not None) else 0

    try:
        trial_dt = datetime.fromisoformat(trial_activated_str)
        now = datetime.now()
        # Ограничение действует в день оформления подписки за 1 ₽ и первые 24 часа.
        if now.date() <= trial_dt.date() or (now - trial_dt).total_seconds() < 86400:
            extra_perm = max(0, perm_bal - 30)
            extra_sub = max(0, sub_bal - 150)
            available_for_video = extra_perm + extra_sub
            
            min_cost = video_cost if video_cost > 0 else 1
            return available_for_video >= min_cost
    except Exception:
        pass

    return True

async def check_ai_search_video_seen(telegram_id: int) -> bool:
    """Проверяет, получена ли пользователем видео-инструкция по ИИ поиску."""
    global _connection
    if _connection is None:
        async with aiosqlite.connect(DB_PATH, timeout=10.0) as db:
            async with db.execute("SELECT has_seen_ai_search_video FROM users WHERE telegram_id = ?", (int(telegram_id),)) as cursor:
                row = await cursor.fetchone()
                return bool(row and row[0])
    else:
        async with _connection.execute("SELECT has_seen_ai_search_video FROM users WHERE telegram_id = ?", (int(telegram_id),)) as cursor:
            row = await cursor.fetchone()
            return bool(row and row[0])

async def set_ai_search_video_seen(telegram_id: int) -> None:
    """Отмечает, что пользователь получил видео-инструкцию по ИИ поиску."""
    global _connection
    if _connection is None:
        async with aiosqlite.connect(DB_PATH, timeout=10.0) as db:
            await db.execute("UPDATE users SET has_seen_ai_search_video = 1 WHERE telegram_id = ?", (int(telegram_id),))
            await db.commit()
    else:
        await _connection.execute("UPDATE users SET has_seen_ai_search_video = 1 WHERE telegram_id = ?", (int(telegram_id),))
        await _connection.commit()


async def get_transaction_history(user_id: int, limit: int = 10, offset: int = 0) -> list[dict]:
    """Возвращает историю транзакций пользователя с пагинацией."""
    global _connection
    if _connection is None:
        async with aiosqlite.connect(DB_PATH, timeout=10.0) as db:
            async with db.execute(
                "SELECT amount, description, created_at FROM transactions "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (int(user_id), limit, offset)
            ) as cursor:
                rows = await cursor.fetchall()
    else:
        async with _connection.execute(
            "SELECT amount, description, created_at FROM transactions "
            "WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (int(user_id), limit, offset)
        ) as cursor:
            rows = await cursor.fetchall()
            
    history = []
    for row in rows:
        history.append({
            "amount": row[0],
            "description": row[1],
            "created_at": row[2]
        })
    return history

async def get_last_daily_bonus_claim(telegram_id: int) -> str | None:
    """Возвращает дату-время последнего получения ежедневного бонуса."""
    global _connection
    if _connection is None:
        async with aiosqlite.connect(DB_PATH, timeout=10.0) as db:
            async with db.execute(
                "SELECT last_daily_bonus_claim FROM users WHERE telegram_id = ?", (int(telegram_id),)
            ) as cursor:
                row = await cursor.fetchone()
    else:
        async with _connection.execute(
            "SELECT last_daily_bonus_claim FROM users WHERE telegram_id = ?", (int(telegram_id),)
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else None

async def claim_daily_bonus(telegram_id: int) -> tuple[bool, str | None]:
    """
    Попытка получить ежедневный бонус.
    Возвращает (success, message/time_remaining_str).
    """
    async with aiosqlite.connect(DB_PATH, isolation_level=None, timeout=10.0) as db:
        await db.execute("PRAGMA busy_timeout = 10000;")
        await db.execute("BEGIN EXCLUSIVE")
        try:
            async with db.execute(
                "SELECT last_daily_bonus_claim FROM users WHERE telegram_id = ?", (int(telegram_id),)
            ) as cursor:
                row = await cursor.fetchone()
            
            if not row:
                try:
                    await db.execute("ROLLBACK")
                except Exception:
                    pass
                return False, "Пользователь не найден"
                
            last_claim_str = row[0]
            now = datetime.now()
            
            if last_claim_str:
                last_claim = datetime.fromisoformat(last_claim_str)
                time_passed = now - last_claim
                if time_passed < timedelta(hours=24):
                    remaining = timedelta(hours=24) - time_passed
                    hours, remainder = divmod(remaining.seconds, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    
                    time_str = ""
                    if remaining.days > 0:
                        time_str += f"{remaining.days} д. "
                    if hours > 0:
                        time_str += f"{hours} ч. "
                    if minutes > 0:
                        time_str += f"{minutes} мин. "
                    if seconds > 0 or not time_str:
                        time_str += f"{seconds} сек."
                    
                    try:
                        await db.execute("ROLLBACK")
                    except Exception:
                        pass
                    return False, time_str.strip()
            
            await db.execute(
                "UPDATE users SET permanent_balance = permanent_balance + 1, last_daily_bonus_claim = ? WHERE telegram_id = ?",
                (now.isoformat(), int(telegram_id))
            )
            await db.execute(
                "INSERT INTO transactions (user_id, amount, description, created_at) VALUES (?, 1, ?, ?)",
                (int(telegram_id), "Ежедневный бонус 🍌", now.isoformat())
            )
            await db.execute("COMMIT")
            return True, None
        except Exception:
            try:
                await db.execute("ROLLBACK")
            except Exception:
                pass
            raise

async def close_db():
    global _connection
    if _connection:
        await _connection.close()
        _connection = None
