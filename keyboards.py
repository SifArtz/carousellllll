from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("▶️ Запустить задачу", callback_data="start_task"))
    kb.add(InlineKeyboardButton("➕ Добавить почту", callback_data="add_account"))
    kb.add(InlineKeyboardButton("📊 Список задач", callback_data="tasks"))
    kb.add(InlineKeyboardButton("📥 Входящие письма", callback_data="inbox"))
    kb.add(InlineKeyboardButton("⚙️ Настройки", callback_data="settings"))
    return kb


def settings_menu():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔑 AI Token", callback_data="set_token"))
    kb.add(InlineKeyboardButton("⌛️ Задержка отправки", callback_data="set_delay"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back"))
    return kb


def _slice_page(items, page, per_page):
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end], page, total_pages


def accounts_menu(accounts, page=1, per_page=6):
    kb = InlineKeyboardMarkup()
    chunk, page, total_pages = _slice_page(accounts, page, per_page)
    for acc in chunk:
        kb.add(InlineKeyboardButton(
            acc["email"], callback_data=f"acc_{acc['id']}"
        ))

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"accounts_page_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"accounts_page_{page+1}"))
    if len(nav) > 1:
        kb.row(*nav)

    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back"))
    return kb


def account_actions(acc_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("▶️ Запустить", callback_data=f"acc_start_{acc_id}"))
    kb.add(InlineKeyboardButton("❌ Удалить", callback_data=f"acc_del_{acc_id}"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back"))
    return kb


def tasks_menu(tasks, page=1, per_page=6):
    kb = InlineKeyboardMarkup()
    chunk, page, total_pages = _slice_page(tasks, page, per_page)
    for t in chunk:
        kb.add(InlineKeyboardButton(
            f"Задача #{t['id']} ({t['status']})",
            callback_data=f"task_{t['id']}"
        ))

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"tasks_page_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"tasks_page_{page+1}"))
    if len(nav) > 1:
        kb.row(*nav)

    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back"))
    return kb


def task_actions(task_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔄 Обновить", callback_data=f"task_{task_id}_refresh"))
    kb.add(InlineKeyboardButton("📄 Лог", callback_data=f"task_log_{task_id}"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="tasks"))
    return kb


def reply_button(incoming_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{incoming_id}"))
    return kb


def incoming_actions(incoming_id, include_history=True):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{incoming_id}"))
    if include_history:
        kb.add(InlineKeyboardButton("📜 История", callback_data=f"hist_{incoming_id}"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="inbox_back"))
    return kb


def cancel_keyboard():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("❌ Отменить", callback_data="cancel_action"))
    return kb


def hide_message_keyboard():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🙈 Скрыть", callback_data="hide_message"))
    return kb


def inbox_menu(items, page=1, per_page=6, total_count=None):
    kb = InlineKeyboardMarkup()
    total_items = total_count if total_count is not None else len(items)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    chunk = items[:per_page]

    for it in chunk:
        kb.add(InlineKeyboardButton(
            f"{it['from_email']} ({_safe_ts(it['received_at'])})",
            callback_data=f"inbox_view_{it['incoming_id']}"
        ))

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"inbox_page_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"inbox_page_{page+1}"))
    if len(nav) > 1:
        kb.row(*nav)

    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back"))
    return kb


def _safe_ts(ts):
    return ts or "–"
