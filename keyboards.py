from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("▶️ Запустить задачу", callback_data="start_task"))
    kb.add(InlineKeyboardButton("➕ Добавить почту", callback_data="add_account"))
    kb.add(InlineKeyboardButton("📊 Список задач", callback_data="tasks"))
    kb.add(InlineKeyboardButton("⚙️ Настройки", callback_data="settings"))
    return kb


def settings_menu():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔑 AI Token", callback_data="set_token"))
    kb.add(InlineKeyboardButton("⌛️ Задержка отправки", callback_data="set_delay"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back"))
    return kb


def accounts_menu(accounts):
    kb = InlineKeyboardMarkup()
    for acc in accounts:
        kb.add(InlineKeyboardButton(
            acc["email"], callback_data=f"acc_{acc['id']}"
        ))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back"))
    return kb


def account_actions(acc_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("▶️ Запустить", callback_data=f"acc_start_{acc_id}"))
    kb.add(InlineKeyboardButton("❌ Удалить", callback_data=f"acc_del_{acc_id}"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back"))
    return kb


def tasks_menu(tasks):
    kb = InlineKeyboardMarkup()
    for t in tasks:
        kb.add(InlineKeyboardButton(
            f"Задача #{t['id']} ({t['status']})",
            callback_data=f"task_{t['id']}"
        ))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back"))
    return kb


def task_actions(task_id):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔄 Обновить", callback_data=f"task_{task_id}_refresh"))
    kb.add(InlineKeyboardButton("📄 Лог", callback_data=f"task_log_{task_id}"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="tasks"))
    return kb
