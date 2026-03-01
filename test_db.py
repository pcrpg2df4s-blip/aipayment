import sqlite3
import os

DB_PATH = "test_db.sqlite"
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

conn = sqlite3.connect(DB_PATH)
conn.execute('''
    CREATE TABLE users (
        telegram_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0
    )
''')
conn.commit()

conn.execute("INSERT INTO users (telegram_id, balance) VALUES (?, ?)", (1, 11580))
conn.commit()

tokens = 1100
conn.execute('''
    INSERT INTO users (telegram_id, balance) 
    VALUES (?, ?)
    ON CONFLICT(telegram_id) 
    DO UPDATE SET balance = balance + ?
''', (1, tokens, tokens))
conn.commit()

cursor = conn.execute("SELECT balance FROM users WHERE telegram_id = 1")
print(f"Final balance: {cursor.fetchone()[0]}")
