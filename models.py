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
