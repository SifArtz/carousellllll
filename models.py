import sqlite3

DB_PATH = "bot.db"


def db():
    return sqlite3.connect(DB_PATH)


# ==========================================================
# ACCOUNTS
# ==========================================================
def add_account(email, app_password, name, proxy):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO accounts (email, app_password, name, proxy) VALUES (?, ?, ?, ?)",
        (email, app_password, name, proxy)
    )
    conn.commit()
    conn.close()


def get_accounts():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM accounts")
    rows = cur.fetchall()
    conn.close()

    return [
        {"id": r[0], "email": r[1], "app_password": r[2], "name": r[3], "proxy": r[4]}
        for r in rows
    ]


def get_account(acc_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM accounts WHERE id=?", (acc_id,))
    r = cur.fetchone()
    conn.close()

    return {"id": r[0], "email": r[1], "app_password": r[2], "name": r[3], "proxy": r[4]}


def delete_account(acc_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM accounts WHERE id=?", (acc_id,))
    conn.commit()
    conn.close()


# ==========================================================
# SETTINGS
# ==========================================================
def set_ai_token(token):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE settings SET ai_token=?", (token,))
    conn.commit()
    conn.close()


def set_delay(delay):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE settings SET send_delay=?", (delay,))
    conn.commit()
    conn.close()


def get_settings():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT ai_token, send_delay FROM settings WHERE id=1")
    r = cur.fetchone()
    conn.close()

    return {"ai_token": r[0], "send_delay": r[1]}


# ==========================================================
# TASKS
# ==========================================================
def create_task(acc_id, total):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO tasks (account_id, total_sellers, status) VALUES (?, ?, 'running')",
        (acc_id, total)
    )
    conn.commit()
    task_id = cur.lastrowid
    conn.close()
    return task_id


def update_valid(task_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET valid_emails = valid_emails + 1 WHERE id=?", (task_id,))
    conn.commit()
    conn.close()


def update_sent(task_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET sent_emails = sent_emails + 1 WHERE id=?", (task_id,))
    conn.commit()
    conn.close()


def finish_task(task_id, log_path):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE tasks SET status='finished', log_file_path=? WHERE id=?",
        (log_path, task_id)
    )
    conn.commit()
    conn.close()


def get_tasks():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()

    return [
        {
            "id": r[0],
            "account_id": r[1],
            "total_sellers": r[2],
            "valid_emails": r[3],
            "sent_emails": r[4],
            "status": r[5],
            "log_file_path": r[6]
        }
        for r in rows
    ]


def get_task(task_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
    r = cur.fetchone()
    conn.close()
    if not r:
        return None

    return {
        "id": r[0],
        "account_id": r[1],
        "total_sellers": r[2],
        "valid_emails": r[3],
        "sent_emails": r[4],
        "status": r[5],
        "log_file_path": r[6]
    }


# ==========================================================
# LOG ITEMS (EMAIL LOG)
# ==========================================================
def log_item(task_id, email, title, price, img_url, adlink):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO logs (task_id, email, title, price, img_url, adlink) VALUES (?, ?, ?, ?, ?, ?)",
        (task_id, email, title, price, img_url, adlink)
    )
    conn.commit()
    conn.close()


# ==========================================================
# INCOMING EMAILS
# ==========================================================
def incoming_exists(message_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM incoming_messages WHERE message_id=?", (message_id,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def add_incoming_message(account_id, message_id, from_email, subject, body_preview, body_full=None, received_at=None):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO incoming_messages
        (account_id, message_id, from_email, subject, body_preview, body_full, received_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (account_id, message_id, from_email, subject, body_preview, body_full, received_at)
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def get_incoming(incoming_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM incoming_messages WHERE id=?", (incoming_id,))
    r = cur.fetchone()
    conn.close()
    if not r:
        return None

    return {
        "id": r[0],
        "account_id": r[1],
        "message_id": r[2],
        "from_email": r[3],
        "subject": r[4],
        "body_preview": r[5],
        "body_full": r[6],
        "received_at": r[7],
    }


# ==========================================================
# CONVERSATION LOG
# ==========================================================
def add_conversation_message(account_id, email, direction, subject, body, adlink=None, message_id=None, created_at=None):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO conversation_messages
        (account_id, email, direction, subject, body, adlink, created_at, message_id)
        VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), ?)
        """,
        (account_id, email, direction, subject, body, adlink, created_at, message_id)
    )
    conn.commit()
    conn.close()


def get_conversation(email, limit=10):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT email, direction, subject, body, adlink, created_at
        FROM conversation_messages
        WHERE email=?
        ORDER BY datetime(created_at) ASC, id ASC
        """,
        (email,)
    )
    rows = cur.fetchall()
    conn.close()

    items = [
        {
            "email": r[0],
            "direction": r[1],
            "subject": r[2],
            "body": r[3],
            "adlink": r[4],
            "created_at": r[5],
        }
        for r in rows
    ]

    if limit:
        return items[-limit:]

    return items


def last_adlink_by_email(email):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT adlink FROM conversation_messages
        WHERE email=? AND adlink IS NOT NULL AND adlink != ''
        ORDER BY datetime(created_at) DESC, id DESC
        LIMIT 1
        """,
        (email,)
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return row[0]

    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT adlink FROM logs WHERE email=? ORDER BY id DESC LIMIT 1",
        (email,)
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else ""
