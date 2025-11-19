import sqlite3

DB_PATH = "bot.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ---------------- ACCOUNTS ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,
            app_password TEXT,
            name TEXT,
            proxy TEXT
        )
    """)

    # ---------------- SETTINGS ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            ai_token TEXT DEFAULT '',
            send_delay INTEGER DEFAULT 1
        )
    """)

    # Создаем единственную строку настроек если нет
    cur.execute("INSERT OR IGNORE INTO settings (id) VALUES (1)")

    # ---------------- TASKS ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            total_sellers INTEGER,
            valid_emails INTEGER DEFAULT 0,
            sent_emails INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running',
            log_file_path TEXT,
            FOREIGN KEY(account_id) REFERENCES accounts(id)
        )
    """)

    # ---------------- LOGS ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            email TEXT,
            title TEXT,
            price TEXT,
            img_url TEXT,
            adlink TEXT,
            FOREIGN KEY(task_id) REFERENCES tasks(id)
        )
    """)

    # ---------------- INCOMING EMAILS ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS incoming_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            message_id TEXT UNIQUE,
            from_email TEXT,
            subject TEXT,
            body_preview TEXT,
            FOREIGN KEY(account_id) REFERENCES accounts(id)
        )
    """)

    conn.commit()
    conn.close()
