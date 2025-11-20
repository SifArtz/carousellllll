import sqlite3

DB_PATH = "bot.db"


def db():
    return sqlite3.connect(DB_PATH)


# ==========================================================
# ACCOUNTS
# ==========================================================
def add_account(user_id, email, app_password, name, proxy):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO accounts (user_id, email, app_password, name, proxy) VALUES (?, ?, ?, ?, ?)",
        (user_id, email, app_password, name, proxy)
    )
    conn.commit()
    conn.close()


def get_accounts(user_id=None):
    conn = db()
    cur = conn.cursor()
    if user_id is None:
        cur.execute("SELECT * FROM accounts")
    else:
        cur.execute("SELECT * FROM accounts WHERE user_id=?", (user_id,))
    rows = cur.fetchall()
    conn.close()

    return [
        {
            "id": r[0],
            "email": r[2],
            "app_password": r[3],
            "name": r[4],
            "proxy": r[5],
            "user_id": r[1],
        }
        for r in rows
    ]


def get_account(acc_id, user_id=None):
    conn = db()
    cur = conn.cursor()
    if user_id is None:
        cur.execute("SELECT * FROM accounts WHERE id=?", (acc_id,))
    else:
        cur.execute("SELECT * FROM accounts WHERE id=? AND user_id=?", (acc_id, user_id))
    r = cur.fetchone()
    conn.close()
    if not r:
        return None

    return {
        "id": r[0],
        "email": r[2],
        "app_password": r[3],
        "name": r[4],
        "proxy": r[5],
        "user_id": r[1],
    }


def delete_account(acc_id, user_id=None):
    conn = db()
    cur = conn.cursor()
    if user_id is None:
        cur.execute("DELETE FROM accounts WHERE id=?", (acc_id,))
    else:
        cur.execute("DELETE FROM accounts WHERE id=? AND user_id=?", (acc_id, user_id))
    conn.commit()
    conn.close()


# ==========================================================
# SETTINGS
# ==========================================================
def _ensure_settings_row(user_id):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO settings (user_id) VALUES (?)",
        (user_id,)
    )
    conn.commit()
    conn.close()


def set_ai_token(user_id, token):
    _ensure_settings_row(user_id)
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE settings SET ai_token=? WHERE user_id=?", (token, user_id))
    conn.commit()
    conn.close()


def set_delay(user_id, delay):
    _ensure_settings_row(user_id)
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE settings SET send_delay=? WHERE user_id=?", (delay, user_id))
    conn.commit()
    conn.close()


def get_settings(user_id):
    _ensure_settings_row(user_id)
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT ai_token, send_delay FROM settings WHERE user_id=?", (user_id,))
    r = cur.fetchone()
    conn.close()

    return {"ai_token": r[0], "send_delay": r[1]}


# ==========================================================
# TASKS
# ==========================================================
def create_task(acc_id, total, user_id):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO tasks (account_id, total_sellers, status, user_id) VALUES (?, ?, 'running', ?)",
        (acc_id, total, user_id)
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


def get_tasks(user_id=None):
    conn = db()
    cur = conn.cursor()
    if user_id is None:
        cur.execute("SELECT * FROM tasks ORDER BY id DESC")
    else:
        cur.execute("SELECT * FROM tasks WHERE user_id=? ORDER BY id DESC", (user_id,))
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
            "log_file_path": r[6],
            "user_id": r[7],
        }
        for r in rows
    ]


def get_task(task_id, user_id=None):
    conn = db()
    cur = conn.cursor()
    if user_id is None:
        cur.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
    else:
        cur.execute("SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
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
        "log_file_path": r[6],
        "user_id": r[7],
    }


# ==========================================================
# LOG ITEMS (EMAIL LOG)
# ==========================================================
def log_item(task_id, email, title, price, img_url, adlink, user_id):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO logs (task_id, email, title, price, img_url, adlink, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (task_id, email, title, price, img_url, adlink, user_id)
    )
    conn.commit()
    conn.close()


# ==========================================================
# INCOMING EMAILS
# ==========================================================
def incoming_exists(message_id, user_id=None):
    conn = db()
    cur = conn.cursor()
    if user_id is None:
        cur.execute("SELECT 1 FROM incoming_messages WHERE message_id=?", (message_id,))
    else:
        cur.execute("SELECT 1 FROM incoming_messages WHERE message_id=? AND user_id=?", (message_id, user_id))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def add_incoming_message(account_id, message_id, from_email, subject, body_preview, body_full=None, received_at=None, user_id=None):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO incoming_messages
        (account_id, message_id, from_email, subject, body_preview, body_full, received_at, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (account_id, message_id, from_email, subject, body_preview, body_full, received_at, user_id)
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def get_incoming(incoming_id, user_id=None):
    conn = db()
    cur = conn.cursor()
    if user_id is None:
        cur.execute("SELECT * FROM incoming_messages WHERE id=?", (incoming_id,))
    else:
        cur.execute("SELECT * FROM incoming_messages WHERE id=? AND user_id=?", (incoming_id, user_id))
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
        "user_id": r[8],
    }


def get_latest_incoming(user_id, limit=6, offset=0):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT im.id, im.account_id, im.from_email, im.subject, COALESCE(im.body_full, im.body_preview), im.received_at
        FROM incoming_messages im
        JOIN (
            SELECT from_email, MAX(COALESCE(received_at, '')) as max_received, MAX(id) as max_id
            FROM incoming_messages
            WHERE user_id=?
            GROUP BY from_email
        ) last ON im.id = last.max_id
        WHERE im.user_id=?
        ORDER BY datetime(COALESCE(im.received_at, '1970-01-01')) DESC, im.id DESC
        LIMIT ? OFFSET ?
        """,
        (user_id, user_id, limit, offset)
    )
    rows = cur.fetchall()
    conn.close()

    return [
        {
            "incoming_id": r[0],
            "account_id": r[1],
            "from_email": r[2],
            "subject": r[3],
            "body": r[4],
            "received_at": r[5],
        }
        for r in rows
    ]


def count_unique_senders(user_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(DISTINCT from_email) FROM incoming_messages WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0


# ==========================================================
# CONVERSATION LOG
# ==========================================================
def add_conversation_message(account_id, email, direction, subject, body, adlink=None, message_id=None, created_at=None, user_id=None):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO conversation_messages
        (account_id, email, direction, subject, body, adlink, created_at, message_id, user_id)
        VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), ?, ?)
        """,
        (account_id, email, direction, subject, body, adlink, created_at, message_id, user_id)
    )
    conn.commit()
    conn.close()


def get_conversation(email, user_id, limit=10):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT email, direction, subject, body, adlink, created_at
        FROM conversation_messages
        WHERE email=? AND user_id=?
        ORDER BY datetime(created_at) ASC, id ASC
        """,
        (email, user_id)
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


def last_adlink_by_email(email, user_id):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT adlink FROM conversation_messages
        WHERE email=? AND user_id=? AND adlink IS NOT NULL AND adlink != ''
        ORDER BY datetime(created_at) DESC, id DESC
        LIMIT 1
        """,
        (email, user_id)
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return row[0]

    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT adlink FROM logs WHERE email=? AND user_id=? ORDER BY id DESC LIMIT 1",
        (email, user_id)
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else ""
