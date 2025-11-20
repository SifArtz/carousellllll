import sqlite3

DB_PATH = "bot.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ---------------- ACCOUNTS ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            email TEXT,
            app_password TEXT,
            name TEXT,
            proxy TEXT
        )
    """)

    # ---------------- SETTINGS ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            user_id INTEGER PRIMARY KEY,
            ai_token TEXT DEFAULT '',
            send_delay INTEGER DEFAULT 1,
            ai_prompt TEXT DEFAULT ''
        )
    """)

    # Создаем строку настроек для существующих пользователей позже через модели

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
            incoming_checker_enabled INTEGER DEFAULT 1,
            user_id INTEGER,
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
            user_id INTEGER,
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
            body_full TEXT,
            received_at TEXT,
            user_id INTEGER,
            FOREIGN KEY(account_id) REFERENCES accounts(id)
        )
    """)

    # Колонки для обратной совместимости
    try:
        cur.execute("ALTER TABLE incoming_messages ADD COLUMN body_full TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE incoming_messages ADD COLUMN received_at TEXT")
    except sqlite3.OperationalError:
        pass

    # ---------------- CONVERSATION LOG ----------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversation_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            email TEXT,
            direction TEXT,
            subject TEXT,
            body TEXT,
            adlink TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            message_id TEXT,
            user_id INTEGER,
            FOREIGN KEY(account_id) REFERENCES accounts(id)
        )
    """)

    # Дополнительные колонки для обратной совместимости
    for table, column in [
        ("accounts", "user_id"),
        ("settings", "user_id"),
        ("tasks", "user_id"),
        ("logs", "user_id"),
        ("incoming_messages", "user_id"),
        ("conversation_messages", "user_id"),
    ]:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER")
        except sqlite3.OperationalError:
            pass

    try:
        cur.execute("ALTER TABLE tasks ADD COLUMN incoming_checker_enabled INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE settings ADD COLUMN ai_prompt TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()
