import asyncio
import contextlib
import email
import imaplib
import html
import json
import logging
import os
import random
import re
import smtplib
import tempfile
from datetime import datetime, timezone
from email import encoders
from email.header import decode_header
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from mimetypes import guess_type

import aiohttp
import dns.resolver

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.utils import executor

from db import init_db
from models import *
from keyboards import *
from states import *


# ---------------------------------------------------------
#  LOGGING
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("BOT")


# ---------------------------------------------------------
#  BOT
# ---------------------------------------------------------
API_TOKEN = "8441011368:AAGsbBZZWkEhkxsnzCCcoi6nbGC1WDcT9mU"
bot = Bot(API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())


def _format_task_text(task):
    checker_enabled = task.get("incoming_checker_enabled")
    if checker_enabled is None:
        checker_enabled = 1
    checker_state = "включён" if checker_enabled else "выключен"
    return (
        f"🆔 Задача #{task['id']}\n"
        f"Статус: {task['status']}\n"
        f"Всего продавцов: {task['total_sellers']}\n"
        f"Валидных email: {task['valid_emails']}\n"
        f"Отправлено: {task['sent_emails']}\n"
        f"Чекер входящих: {checker_state}\n"
    )


def _paginate(items, page, per_page):
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end], page, total_pages


def _format_link(adlink):
    if not adlink:
        return "Ссылка не найдена"
    safe_link = html.escape(adlink, quote=True)
    return f"<a href=\"{safe_link}\">Ссылка на объявление</a>"


def _escape_html(text: str) -> str:
    return html.escape(text or "")


# ---------------------------------------------------------
# /start
# ---------------------------------------------------------
@dp.message_handler(commands=["start"])
async def start_cmd(msg: types.Message):
    await msg.answer("Главное меню:", reply_markup=main_menu())
    log.info(f"/start от {msg.chat.id}")


@dp.message_handler(lambda m: m.text and m.text.lower() == "отменить", state="*")
async def cancel_action(msg: types.Message, state: FSMContext):
    if await state.get_state() is None:
        return await msg.answer("Нет активных действий.")

    await state.finish()
    await msg.answer("Действие отменено.")
    await msg.answer("Главное меню:", reply_markup=main_menu())


@dp.callback_query_handler(lambda c: c.data == "cancel_action", state="*")
async def cancel_action_inline(call: types.CallbackQuery, state: FSMContext):
    if await state.get_state() is None:
        await call.answer("Нет активных действий")
        return await call.message.edit_reply_markup()

    await state.finish()
    await call.answer("Действие отменено")
    with contextlib.suppress(Exception):
        await call.message.edit_text("Действие отменено.")
    await bot.send_message(call.message.chat.id, "Главное меню:", reply_markup=main_menu())


# ---------------------------------------------------------
# Главные кнопки
# ---------------------------------------------------------
@dp.callback_query_handler(lambda c: c.data == "start_task")
async def click_start_task(call: types.CallbackQuery):
    user_id = call.from_user.id
    settings = get_settings(user_id)
    if not settings.get("ai_token"):
        return await call.message.edit_text(
            "⚠️ Сначала укажите AI Token в настройках.",
            reply_markup=main_menu()
        )

    accounts = get_accounts(user_id)
    if not accounts:
        return await call.message.edit_text(
            "Нет аккаунтов. Добавьте почту.",
            reply_markup=main_menu()
        )

    await call.message.edit_text("Выберите аккаунт:", reply_markup=accounts_menu(accounts))


@dp.callback_query_handler(lambda c: c.data.startswith("accounts_page_"))
async def accounts_page(call: types.CallbackQuery):
    page = int(call.data.split("_")[2])
    accounts = get_accounts(call.from_user.id)
    if not accounts:
        return await call.message.edit_text(
            "Нет аккаунтов. Добавьте почту.",
            reply_markup=main_menu()
        )

    await call.message.edit_text("Выберите аккаунт:", reply_markup=accounts_menu(accounts, page=page))


@dp.callback_query_handler(lambda c: c.data == "add_account")
async def add_acc_click(call: types.CallbackQuery):
    await AddAccount.email.set()
    await call.message.edit_text("Введите Gmail email:", reply_markup=cancel_keyboard())


@dp.callback_query_handler(lambda c: c.data == "tasks")
async def tasks_click(call: types.CallbackQuery):
    tasks = get_tasks(call.from_user.id)

    if not tasks:
        return await call.message.edit_text("Задач нет.", reply_markup=main_menu())

    await call.message.edit_text("Список задач:", reply_markup=tasks_menu(tasks))


@dp.callback_query_handler(lambda c: c.data.startswith("tasks_page_"))
async def tasks_page(call: types.CallbackQuery):
    page = int(call.data.split("_")[2])
    tasks = get_tasks(call.from_user.id)
    if not tasks:
        return await call.message.edit_text("Задач нет.", reply_markup=main_menu())

    await call.message.edit_text("Список задач:", reply_markup=tasks_menu(tasks, page=page))


@dp.callback_query_handler(lambda c: c.data == "settings")
async def settings_click(call: types.CallbackQuery):
    await call.message.edit_text("Настройки:", reply_markup=settings_menu())


@dp.callback_query_handler(lambda c: c.data == "back")
async def back_click(call: types.CallbackQuery):
    await call.message.edit_text("Главное меню:", reply_markup=main_menu())


@dp.callback_query_handler(lambda c: c.data == "noop")
async def noop(call: types.CallbackQuery):
    await call.answer()


async def _render_inbox_page(message_obj, page: int = 1):
    per_page = 6
    user_id = message_obj.from_user.id if isinstance(message_obj, types.CallbackQuery) else message_obj.chat.id
    total = count_unique_senders(user_id)
    if not total:
        if isinstance(message_obj, types.CallbackQuery):
            return await message_obj.message.edit_text("Входящих писем нет.", reply_markup=main_menu())
        return await message_obj.answer("Входящих писем нет.", reply_markup=main_menu())

    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page
    items = get_latest_incoming(user_id, limit=per_page, offset=offset)
    if isinstance(message_obj, types.CallbackQuery):
        await message_obj.message.edit_text(
            "Входящие письма:",
            reply_markup=inbox_menu(items, page=page, per_page=per_page, total_count=total)
        )
    else:
        await message_obj.answer(
            "Входящие письма:",
            reply_markup=inbox_menu(items, page=page, per_page=per_page, total_count=total)
        )


@dp.callback_query_handler(lambda c: c.data == "inbox")
async def inbox_click(call: types.CallbackQuery):
    await _render_inbox_page(call, page=1)


@dp.callback_query_handler(lambda c: c.data.startswith("inbox_page_"))
async def inbox_page(call: types.CallbackQuery):
    page = int(call.data.split("_")[2])
    await _render_inbox_page(call, page=page)


@dp.callback_query_handler(lambda c: c.data == "inbox_back")
async def inbox_back(call: types.CallbackQuery):
    await _render_inbox_page(call, page=1)


# ---------------------------------------------------------
#  Добавление аккаунта
# ---------------------------------------------------------
@dp.message_handler(state=AddAccount.email)
async def acc_set_email(msg, state):
    await state.update_data(email=msg.text)
    await AddAccount.app_password.set()
    await msg.answer("Email сохранён. Теперь введите App Password:")


@dp.message_handler(state=AddAccount.app_password)
async def acc_set_pass(msg, state):
    await state.update_data(app_password=msg.text)
    await AddAccount.name.set()
    await msg.answer("Введите имя аккаунта:")


@dp.message_handler(state=AddAccount.name)
async def acc_set_name(msg, state):
    await state.update_data(name=msg.text)
    await AddAccount.proxy.set()
    await msg.answer("Введите прокси (`user:pass@ip:port`) или напишите: нет")


@dp.message_handler(state=AddAccount.proxy)
async def acc_set_proxy(msg, state):
    proxy = None if msg.text.lower() == "нет" else msg.text
    data = await state.get_data()

    add_account(
        msg.chat.id, data["email"], data["app_password"], data["name"], proxy
    )

    log.info(f"Добавлен аккаунт {data['email']}")
    await msg.answer("Аккаунт добавлен!", reply_markup=types.ReplyKeyboardRemove())
    await msg.answer("Аккаунт добавлен!", reply_markup=main_menu())
    await state.finish()


# ---------------------------------------------------------
#  Настройки
# ---------------------------------------------------------
@dp.callback_query_handler(lambda c: c.data == "set_token")
async def set_token_click(call):
    await SetToken.token.set()
    await call.message.edit_text("Введите AI Token:", reply_markup=cancel_keyboard())


@dp.message_handler(state=SetToken.token)
async def save_token(msg, state):
    set_ai_token(msg.chat.id, msg.text)
    await msg.answer("AI Token сохранён!", reply_markup=types.ReplyKeyboardRemove())
    await msg.answer("AI Token сохранён!", reply_markup=main_menu())
    await state.finish()


@dp.callback_query_handler(lambda c: c.data == "set_delay")
async def set_delay_click(call):
    await SetDelay.delay.set()
    await call.message.edit_text("Введите задержку в секундах:", reply_markup=cancel_keyboard())


@dp.message_handler(state=SetDelay.delay)
async def save_delay(msg, state):
    try:
        d = int(msg.text)
    except:
        return await msg.answer("Введите правильное число!")

    if d < 0:
        return await msg.answer("Задержка не может быть отрицательной.")

    set_delay(msg.chat.id, d)
    await msg.answer("Задержка сохранена!", reply_markup=types.ReplyKeyboardRemove())
    await msg.answer("Задержка сохранена!", reply_markup=main_menu())
    await state.finish()


@dp.callback_query_handler(lambda c: c.data == "set_prompt")
async def set_prompt_click(call):
    current_prompt = get_settings(call.from_user.id).get("ai_prompt") or "(используется промт по умолчанию)"
    hint = (
        "Введите промт для ИИ. Вы можете использовать плейсхолдеры {title}, {acc_name}, {seller}.\n\n"
        f"Текущий промт:\n{current_prompt}"
    )
    await SetPrompt.prompt.set()
    await call.message.edit_text(hint, reply_markup=cancel_keyboard())


@dp.message_handler(state=SetPrompt.prompt)
async def save_prompt(msg, state):
    set_ai_prompt(msg.chat.id, msg.text)
    await msg.answer(
        "Промт сохранён! Нажмите \"Сгенерировать промт\" в настройках, чтобы проверить результат.",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    await msg.answer("Настройки:", reply_markup=settings_menu())
    await state.finish()


@dp.callback_query_handler(lambda c: c.data == "generate_prompt")
async def generate_prompt_example(call: types.CallbackQuery):
    settings = get_settings(call.from_user.id)
    if not settings.get("ai_token"):
        return await call.message.edit_text(
            "⚠️ Сначала укажите AI Token в настройках.",
            reply_markup=settings_menu(),
        )

    await call.answer("Генерируем пример...")
    sample_title = "Example listing"
    sample_seller = "seller"
    sample_acc_name = "Demo Buyer"
    generated = await ai_generate(sample_title, sample_seller, sample_acc_name, call.from_user.id)

    text = (
        f"Тема: {generated.get('subject', '')}\n\n"
        f"{generated.get('message', '')}"
    )
    await call.message.edit_text(text or "Не удалось сгенерировать", reply_markup=settings_menu())


# ---------------------------------------------------------
#  Просмотр аккаунта + запуск задачи
# ---------------------------------------------------------
@dp.callback_query_handler(
    lambda c: c.data.startswith("acc_") and "_start_" not in c.data and "_del_" not in c.data
)
async def view_acc(call):
    acc_id = int(call.data.split("_")[1])
    acc = get_account(acc_id, call.from_user.id)
    if not acc:
        return await call.answer("Аккаунт не найден", show_alert=True)

    text = (
        f"<b>{acc['email']}</b>\n"
        f"Имя: {acc['name']}\n"
        f"Proxy: {acc['proxy'] or 'нет'}"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=account_actions(acc_id))


@dp.callback_query_handler(lambda c: c.data.startswith("acc_del_"))
async def delete_acc(call):
    acc_id = int(call.data.split("_")[2])
    if not get_account(acc_id, call.from_user.id):
        return await call.answer("Аккаунт не найден", show_alert=True)
    delete_account(acc_id, call.from_user.id)
    await call.message.edit_text("Аккаунт удалён.", reply_markup=main_menu())


# ---------------------------------------------------------
#   Запуск задачи
# ---------------------------------------------------------
@dp.callback_query_handler(lambda c: c.data.startswith("acc_start_"))
async def start_task(call, state):
    acc_id = int(call.data.split("_")[2])
    acc = get_account(acc_id, call.from_user.id)
    if not acc:
        return await call.answer("Аккаунт не найден", show_alert=True)
    await state.update_data(acc_id=acc_id, user_id=call.from_user.id)

    await UploadTaskFile.waiting_file.set()
    await call.message.edit_text("Отправьте .txt файл с JSON данными.")


@dp.callback_query_handler(lambda c: c.data.startswith("inbox_view_"))
async def inbox_view(call: types.CallbackQuery):
    incoming_id = int(call.data.split("_")[2])
    incoming = get_incoming(incoming_id, call.from_user.id)
    if not incoming:
        return await call.answer("Письмо не найдено", show_alert=True)

    adlink = last_adlink_by_email(incoming["from_email"], call.from_user.id)
    body = incoming.get("body_full") or incoming.get("body_preview") or "Без текста"
    text = (
        f"📩 Письмо | {incoming['from_email']}\n\n"
        f"🔗 {_format_link(adlink)}\n\n"
        f"🕒 Ответ получен: {_format_timestamp(incoming.get('received_at'))}\n\n"
        f"💬 Текст сообщения:\n\n{_escape_html(body)}"
    )

    await call.message.edit_text(
        text,
        reply_markup=incoming_actions(incoming_id),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# ---------------------------------------------------------
#   Получение файла
# ---------------------------------------------------------
@dp.message_handler(content_types=["document"], state=UploadTaskFile.waiting_file)
async def file_received(msg, state):

    file_info = await msg.document.get_file()
    path = f"./{msg.document.file_name}"
    await file_info.download(destination=path)

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return await msg.answer("Не удалось прочитать JSON файл. Проверьте формат данных.")

    items = []
    for idx, v in enumerate(data.values(), start=1):
        missing = [k for k in ["title", "price", "img_url", "seller"] if k not in v]
        if missing:
            return await msg.answer(f"Строка {idx}: отсутствуют поля: {', '.join(missing)}")

        adlink = v.get("adlink") or v.get("adLink") or v.get("ad_link") or ""
        items.append({
            "title": v["title"],
            "price": v["price"],
            "img_url": v["img_url"],
            "seller": v["seller"],
            "adlink": adlink
        })

    if not items:
        return await msg.answer("Файл пустой, не нашлось продавцов для обработки.")

    st = await state.get_data()
    acc_id = st["acc_id"]
    user_id = st["user_id"]

    task_id = create_task(acc_id, len(items), user_id)
    status_msg = await msg.answer(
        f"Задача #{task_id} запущена. Обработка продавцов...",
        reply_markup=task_actions(task_id, checker_enabled=True)
    )

    asyncio.create_task(
        run_task(task_id, acc_id, items, msg.chat.id, status_msg.chat.id, status_msg.message_id, user_id)
    )

    await state.finish()


# ---------------------------------------------------------
#  SMTP
# ---------------------------------------------------------
def smtp_sync(email):
    try:
        records = dns.resolver.resolve("gmail.com", "MX")
        mx = str(records[0].exchange)
        s = smtplib.SMTP(mx, timeout=7)
        s.helo()
        s.mail("test@example.com")
        code, _ = s.rcpt(email)
        s.quit()
        return code == 250
    except Exception as e:
        log.warning(f"SMTP ERROR {email}: {e}")
        return False


async def smtp_check(email):
    log.info(f"[SMTP] Проверка -> {email}")
    ok = await asyncio.to_thread(smtp_sync, email)
    log.info(f"[SMTP] {'OK' if ok else 'FAIL'} -> {email}")
    return ok


# ---------------------------------------------------------
#  Email sending
# ---------------------------------------------------------
def send_sync(to, subject, text, acc, attachments=None):
    try:
        msg = MIMEMultipart()
        msg["From"] = acc["name"]
        msg["To"] = to
        msg["Subject"] = subject

        msg.attach(MIMEText(text or "", "plain"))

        for attachment in attachments or []:
            with open(attachment["path"], "rb") as f:
                payload = f.read()

            mime_type, _ = guess_type(attachment["filename"])
            if mime_type and mime_type.startswith("image/"):
                part = MIMEImage(payload, name=attachment["filename"])
            else:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(payload)
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=attachment["filename"],
                )

            msg.attach(part)

        s = smtplib.SMTP("smtp.gmail.com", 587, timeout=10)
        s.starttls()
        s.login(acc["email"], acc["app_password"])
        s.sendmail(acc["email"], to, msg.as_string())
        s.quit()
        return True
    except Exception as e:
        log.error(f"Ошибка отправки {to}: {e}")
        return False


async def send_email(to, subject, text, acc, attachments=None):
    log.info(f"[SEND] → {to}")
    return await asyncio.to_thread(send_sync, to, subject, text, acc, attachments)


# ---------------------------------------------------------
# AI генерация
# ---------------------------------------------------------
DEFAULT_AI_PROMPT = """
You are a professional copywriter specialising in low-spam, natural English outreach for Carousell Singapore buyers.

GOAL:
Create ONE fully original message that sounds like a real buyer on Carousell asking about a product.

DELIVERABILITY FIRST (VERY IMPORTANT):
- Keep tone neutral, friendly and human — avoid hype, salesy language, all caps, slogans, or multiple exclamation marks.
- No links, no URLs, no phone numbers, no prices, no discounts, no emojis.
- Write 35–80 words, in plain text sentences (no bullet points or lists).
- Vary sentence structure; avoid repetition and template-like phrasing.

AVAILABILITY QUESTION (MANDATORY):
- Include ONE unique, natural availability question that is NOT a standard wording like:
  “Is this available?”, "Still available?", "Available?", "Is this still available?".
- Each time, craft a fresh, human variation such as:
  - "Just wanted to check if it's still up for grabs?"
  - "Are you still letting this go?"
  - "Is this item still on your list?"
  Create other unique forms each time.

PERSONAL COMMENT (MANDATORY):
- Add a brief, personal remark about the item "{title}" that feels curious or observational (e.g., what caught your attention, condition, or fit for a need). Do not reuse sample wording; write something new each time.

STRICT RULES:
- NO generic marketplace templates.
- NO robotic or repetitive structures.
- Only ONE final message.
- NO heavy Singlish (NO “lah”, “lor”, “leh”, “hor”), but a light SG tone is ok.
- Natural, polite, slightly casual.

EMAIL SUBJECT:
Use EXACT format (do not change it):
"Enquiry about {title} | Carousell"

EMAIL MESSAGE TO SELLER "{seller}":
- Must mention that you came across the item on Carousell.
- Must include a UNIQUE availability question (not a template).
- Must include a UNIQUE personal comment about the item.
- Please contact via Telegram @miialing
- Must end with the buyer name: {acc_name}

FORMAT:
Return ONLY valid JSON:

{{
  "subject": "",
  "message": ""
}}
"""


def _build_prompt(user_id, title, seller, acc_name):
    settings = get_settings(user_id)
    prompt_template = settings.get("ai_prompt") or DEFAULT_AI_PROMPT
    try:
        return prompt_template.format(title=title, seller=seller, acc_name=acc_name)
    except Exception as e:
        log.error(f"[AI] Ошибка форматирования промта: {e}")
        return DEFAULT_AI_PROMPT.format(title=title, seller=seller, acc_name=acc_name)


async def ai_generate(title, seller, acc_name, user_id):
    token = get_settings(user_id)["ai_token"]


    prompt = _build_prompt(user_id, title, seller, acc_name)
    log.info(f"[AI] Генерация письма для {seller}@gmail.com ({title})")

    client_timeout = aiohttp.ClientTimeout(total=25)
    try:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.post(
                "https://neuroapi.host/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200
                }
            ) as r:
                body = await r.text()
                if r.status >= 400:
                    log.error(
                        f"[AI] Ошибка генерации: HTTP {r.status} | {body[:400]}"
                    )
                    return {
                        "subject": f"Question about {title}",
                        "message": f"Hi! I'm interested in {title}. Is it still available? - {acc_name}",
                    }

                try:
                    js = json.loads(body)
                except Exception as parse_err:
                    log.error(
                        f"[AI] Ошибка чтения JSON ответа: {parse_err} | {body[:400]}"
                    )
                    return {
                        "subject": f"Question about {title}",
                        "message": f"Hi! I'm interested in {title}. Is it still available? - {acc_name}",
                    }
    except Exception:
        log.exception("[AI] Ошибка генерации")
        return {
            "subject": f"Question about {title}",
            "message": f"Hi! I'm interested in {title}. Is it still available? - {acc_name}",
        }

    content = None
    try:
        content = js["choices"][0]["message"].get("content")
    except Exception as e:
        log.error(f"[AI] Некорректный формат ответа: {e} | {js}")

    if isinstance(content, dict):
        out = content
    elif isinstance(content, str):
        cleaned = content.strip()
        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.S)
        if fenced_match:
            cleaned = fenced_match.group(1)

        try:
            out = json.loads(cleaned)
        except Exception as e:
            log.error(f"[AI] Ошибка парсинга ответа: {e} | {cleaned[:200]}")
            out = None
    else:
        out = None

    if not isinstance(out, dict):
        out = {
            "subject": f"Question about {title}",
            "message": f"Hello! I liked {title}. Is it still up for sale? - {acc_name}",
        }

    log.info(f"[AI] Сгенерировано: {out.get('subject', '(нет темы)')}")

    return out


# ---------------------------------------------------------
#  Фоновая задача
# ---------------------------------------------------------


async def run_task(task_id, acc_id, items, chat_id, status_chat_id=None, status_msg_id=None, user_id=None):

    acc = get_account(acc_id, user_id)
    if not acc:
        log.error(f"[TASK] Аккаунт {acc_id} не найден")
        return

    delay = max(0, get_settings(user_id).get("send_delay", 0))

    class SendRateLimiter:
        def __init__(self, base_delay: int):
            self.base_delay = base_delay
            self._lock = asyncio.Lock()
            self._last_planned = None

        def _next_delay(self) -> float:
            if self.base_delay <= 0:
                return 0
            jitter = max(1, int(self.base_delay * 0.2))
            low = max(0, self.base_delay - jitter)
            high = self.base_delay + jitter
            return random.uniform(low, max(high, low + 0.1))

        async def wait_turn(self):
            if self.base_delay <= 0:
                return
            async with self._lock:
                delay_value = self._next_delay()
                now = asyncio.get_running_loop().time()
                if self._last_planned is None:
                    self._last_planned = now
                    sleep_for = 0
                else:
                    self._last_planned = max(self._last_planned + delay_value, now)
                    sleep_for = max(0, self._last_planned - now)
            if sleep_for:
                await asyncio.sleep(sleep_for)

    rate_limiter = SendRateLimiter(delay)
    log_path = f"task_{task_id}.txt"

    valid = 0
    sent = 0
    counter_lock = asyncio.Lock()
    send_tasks = []

    async def update_progress(status: str):
        if not status_chat_id or not status_msg_id:
            return

        task_state = get_task(task_id, user_id)
        if not task_state:
            return

        text = _format_task_text({
            **task_state,
            "status": status,
            "valid_emails": valid,
            "sent_emails": sent,
            "total_sellers": len(items)
        })

        checker_flag = task_state.get("incoming_checker_enabled")
        if checker_flag is None:
            checker_flag = 1

        try:
            await bot.edit_message_text(
                text=text,
                chat_id=status_chat_id,
                message_id=status_msg_id,
                reply_markup=task_actions(task_id, checker_enabled=bool(checker_flag))
            )
        except Exception:
            pass

    await update_progress("running")

    with open(log_path, "w", encoding="utf-8") as f:
        for item in items:
            email = f"{item['seller']}@gmail.com"
            log.info(f"[TASK] Обработка продавца {email}")

            try:
                smtp_ok = await smtp_check(email)
            except Exception as e:
                log.error(f"[TASK] SMTP ошибка для {email}: {e}")
                continue

            if not smtp_ok:
                continue

            update_valid(task_id)
            valid += 1

            try:
                ai_out = await ai_generate(item["title"], item["seller"], acc["name"], user_id)
            except Exception as e:
                log.error(f"[TASK] AI ошибка для {email}: {e}")
                continue

            subject = ai_out.get("subject") or f"Question about {item['title']}"
            message = ai_out.get("message") or "Hello! Is this still available?"

            line = f"{email} | {item['title']} | {item['price']} | {item['img_url']} | {item['adlink']}\n"
            f.write(line)
            log_item(task_id, email, item["title"], item["price"], item["img_url"], item["adlink"], user_id)

            async def schedule_send(to_email, subj, body, adlink):
                nonlocal sent
                try:
                    await rate_limiter.wait_turn()
                    sent_ok = await send_email(to_email, subj, body, acc)
                except Exception as e:
                    log.error(f"[TASK] Ошибка отправки {to_email}: {e}")
                    sent_ok = False

                if sent_ok:
                    update_sent(task_id)
                    async with counter_lock:
                        sent += 1
                    add_conversation_message(
                        acc_id,
                        to_email,
                        "outgoing",
                        subj,
                        body,
                        adlink,
                        created_at=datetime.now(timezone.utc).isoformat(),
                        user_id=user_id,
                    )

                await update_progress("running")

            send_tasks.append(asyncio.create_task(
                schedule_send(email, subject, message, item.get("adlink", ""))
            ))

    if send_tasks:
        await asyncio.gather(*send_tasks, return_exceptions=True)

    finish_task(task_id, log_path)

    await update_progress("finished")

    await bot.send_message(
        chat_id,
        f"Задача #{task_id} завершена!\n"
        f"Всего продавцов: {len(items)}\n"
        f"Валидных email: {valid}\n"
        f"Отправлено: {sent}"
    )

    log.info(f"[TASK] Задача #{task_id} звершена!")

# ---------------------------------------------------------
#  Просмотр задачи
# ---------------------------------------------------------
@dp.callback_query_handler(
    lambda c: c.data.startswith("task_")
    and not c.data.startswith("task_log_")
    and not c.data.endswith("_refresh")
    and "toggle_checker" not in c.data
)
async def task_view(call):
    task_id = int(call.data.split("_")[1])
    task = get_task(task_id, call.from_user.id)
    if not task:
        return await call.answer("Задача не найдена", show_alert=True)

    text = _format_task_text(task)

    checker_flag = task.get("incoming_checker_enabled")
    if checker_flag is None:
        checker_flag = 1

    await call.message.edit_text(
        text,
        reply_markup=task_actions(task_id, checker_enabled=bool(checker_flag))
    )


# ---------------------------------------------------------
#   ОБНОВИТЬ
# ---------------------------------------------------------
@dp.callback_query_handler(lambda c: c.data.endswith("_refresh"))
async def refresh_task(call):
    task_id = int(call.data.split("_")[1])
    task = get_task(task_id, call.from_user.id)
    if not task:
        return await call.answer("Задача не найдена", show_alert=True)

    text = _format_task_text(task)

    checker_flag = task.get("incoming_checker_enabled")
    if checker_flag is None:
        checker_flag = 1

    try:
        await call.message.edit_text(
            text,
            reply_markup=task_actions(task_id, checker_enabled=bool(checker_flag))
        )
    except Exception:
        await call.answer("Нет обновлений", show_alert=False)


@dp.callback_query_handler(lambda c: c.data.startswith("task_toggle_checker_"))
async def toggle_task_checker(call: types.CallbackQuery):
    task_id = int(call.data.split("_")[3])
    task = get_task(task_id, call.from_user.id)
    if not task:
        return await call.answer("Задача не найдена", show_alert=True)

    current_state = task.get("incoming_checker_enabled")
    if current_state is None:
        current_state = 1

    new_state = not bool(current_state)
    set_task_checker(task_id, new_state, call.from_user.id)
    task["incoming_checker_enabled"] = int(new_state)

    text = _format_task_text(task)

    try:
        await call.message.edit_text(
            text,
            reply_markup=task_actions(task_id, checker_enabled=new_state)
        )
    except Exception:
        pass

    await call.answer("Чекер включён" if new_state else "Чекер отключён")


# ---------------------------------------------------------
#  ЛОГ-ФАЙЛ
# ---------------------------------------------------------
@dp.callback_query_handler(lambda c: c.data.startswith("task_log_"))
async def send_log(call):
    task_id = int(call.data.split("_")[2])
    task = next((t for t in get_tasks(call.from_user.id) if t["id"] == task_id), None)
    if not task:
        return await call.answer("Задача не найдена", show_alert=True)

    if not task["log_file_path"]:
        return await call.answer("Лог ещё не создан!")

    await bot.send_document(
        call.message.chat.id,
        open(task["log_file_path"], "rb")
    )


# ---------------------------------------------------------
#  IMAP helpers
# ---------------------------------------------------------
def _decode_mime_words(header_value):
    decoded = decode_header(header_value)
    parts = []
    for text, enc in decoded:
        if isinstance(text, bytes):
            parts.append(text.decode(enc or "utf-8", errors="ignore"))
        else:
            parts.append(text)
    return "".join(parts)


def _extract_text_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                try:
                    return part.get_payload(decode=True).decode(charset, errors="ignore")
                except Exception:
                    continue
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            return msg.get_payload(decode=True).decode(charset, errors="ignore")
        except Exception:
            return ""
    return ""


def _clean_incoming_body(body: str) -> str:
    if not body:
        return body

    lines = body.splitlines()
    cleaned = []
    stop_markers = [" wrote:", "написал", "пишет"]

    for line in lines:
        stripped = line.strip()
        lower_line = stripped.lower()

        if stripped.startswith(">"):
            break
        if lower_line.startswith("on ") and "wrote:" in lower_line:
            break
        if any(marker in lower_line for marker in stop_markers) and lower_line.endswith(":"):
            break
        if stripped.startswith("--"):
            break
        if stripped.startswith("чт,") or stripped.startswith("сб,") or stripped.startswith("вс,"):
            break

        cleaned.append(line)

    cleaned_text = "\n".join(cleaned).strip()
    return cleaned_text or body.strip()


def _parse_date(date_str):
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def _format_timestamp(ts):
    if not ts:
        return "неизвестно"

    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return ts


def fetch_unseen_messages(acc):
    messages = []
    with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
        imap.login(acc["email"], acc["app_password"])
        imap.select("inbox")
        status, data = imap.search(None, "UNSEEN")
        if status != "OK":
            return messages

        for num in data[0].split():
            status, msg_data = imap.fetch(num, "(RFC822)")
            if status != "OK":
                continue

            msg = email.message_from_bytes(msg_data[0][1])
            message_id = msg.get("Message-ID", num.decode())
            subject = _decode_mime_words(msg.get("Subject", "(без темы)"))
            from_email = email.utils.parseaddr(msg.get("From", ""))[1]
            raw_body = _extract_text_body(msg)
            body = _clean_incoming_body(raw_body)
            preview = body.strip().splitlines()[0][:200] if body else ""
            received_at = _parse_date(msg.get("Date"))
            messages.append({
                "message_id": message_id,
                "from_email": from_email,
                "subject": subject,
                "preview": preview,
                "body": body,
                "received_at": received_at
            })

    return messages


async def check_inboxes():
    while True:
        accounts = get_accounts()
        for acc in accounts:
            try:
                if acc.get("user_id") and not user_has_enabled_checker(acc["user_id"]):
                    continue

                unseen = await asyncio.to_thread(fetch_unseen_messages, acc)
                for msg_data in unseen:
                    if incoming_exists(msg_data["message_id"], acc.get("user_id")):
                        continue

                    incoming_id = add_incoming_message(
                        acc["id"],
                        msg_data["message_id"],
                        msg_data["from_email"],
                        msg_data["subject"],
                        msg_data["preview"],
                        msg_data.get("body"),
                        msg_data.get("received_at"),
                        acc.get("user_id"),
                    )

                    if not incoming_id:
                        continue

                    adlink = last_adlink_by_email(msg_data["from_email"], acc["user_id"])

                    add_conversation_message(
                        acc["id"],
                        msg_data["from_email"],
                        "incoming",
                        msg_data["subject"],
                        msg_data.get("body") or msg_data["preview"],
                        adlink,
                        msg_data["message_id"],
                        msg_data.get("received_at"),
                        acc.get("user_id"),
                    )

                    text = (
                        f"📩 Новое письмо | {msg_data['from_email']}\n\n"
                        f"🔗 {_format_link(adlink)}\n\n"
                        f"🕒 Ответ получен: {_format_timestamp(msg_data.get('received_at'))}\n\n"
                        f"💬 Текст сообщения:\n\n{_escape_html(msg_data.get('body') or msg_data['preview'] or 'Без текста')}"
                    )

                    if acc.get("user_id"):
                        await bot.send_message(
                            acc["user_id"],
                            text,
                            reply_markup=incoming_actions(incoming_id),
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
            except Exception as e:
                log.warning(f"[IMAP] Ошибка для {acc['email']}: {e}")

        await asyncio.sleep(60)


# ---------------------------------------------------------
#  Reply to incoming email
# ---------------------------------------------------------
@dp.callback_query_handler(lambda c: c.data.startswith("hist_"))
async def show_history(call: types.CallbackQuery):
    incoming_id = int(call.data.split("_")[1])
    incoming = get_incoming(incoming_id, call.from_user.id)
    if not incoming:
        return await call.answer("История не найдена", show_alert=True)

    email_addr = incoming["from_email"]
    history = get_conversation(email_addr, call.from_user.id, limit=None)

    if not history:
        return await call.message.answer("История пуста.")

    if len(history) > 25:
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8", suffix=".txt") as f:
            for h in history:
                icon = "➡️" if h["direction"] == "outgoing" else "⬅️"
                f.write(
                    f"{icon} [{_format_timestamp(h['created_at'])}] {h['subject']}\n{h['body']}\nAdlink: {h.get('adlink') or '—'}\n\n"
                )
            file_path = f.name

        await bot.send_document(
            call.message.chat.id,
            open(file_path, "rb"),
            caption=f"История с {email_addr} (файл)"
        )
        try:
            os.remove(file_path)
        except Exception:
            pass
    else:
        lines = [
            f"📜 История | {email_addr}",
            f"🔗 {_format_link(last_adlink_by_email(email_addr, call.from_user.id))}"
        ]

        for h in history:
            icon = "👤" if h["direction"] == "outgoing" else "🦣"
            body_text = (h["body"] or "(пусто)").strip()
            display_body = "Изображение" if body_text.lower() == "изображение" else body_text
            lines.append(f"{icon} [{_format_timestamp(h['created_at'])}] {_escape_html(display_body)}")

        text = "\n\n".join(lines) if lines else "История пуста."
        await call.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=hide_message_keyboard(),
            disable_web_page_preview=True,
        )


# ---------------------------------------------------------
#  Reply to incoming email
# ---------------------------------------------------------
@dp.callback_query_handler(lambda c: c.data.startswith("reply_"))
async def start_reply(call: types.CallbackQuery, state: FSMContext):
    incoming_id = int(call.data.split("_")[1])
    incoming = get_incoming(incoming_id)
    if not incoming:
        return await call.answer("Сообщение не найдено", show_alert=True)

    await state.update_data(incoming_id=incoming_id)
    await ReplyMessage.waiting_text.set()
    await call.message.answer(
        f"Введите ответ для {incoming['from_email']} (тема: {incoming['subject']})",
        reply_markup=cancel_keyboard(),
    )


@dp.message_handler(state=ReplyMessage.waiting_text, content_types=["text", "photo", "document"])
async def send_reply(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    incoming = get_incoming(data.get("incoming_id"), msg.chat.id)
    if not incoming:
        await msg.answer("Не удалось найти исходное письмо.")
        return await state.finish()

    acc = get_account(incoming["account_id"], msg.chat.id)
    if not acc:
        await msg.answer("Аккаунт для ответа не найден.")
        return await state.finish()
    subject = f"Re: {incoming['subject']}"
    attachments = []
    logged_body = None
    body = msg.text or msg.caption or ""

    if msg.photo:
        photo = msg.photo[-1]
        file_info = await photo.get_file()
        file_path = os.path.join(tempfile.gettempdir(), f"{photo.file_unique_id}.jpg")
        await file_info.download(destination=file_path)
        attachments.append({"path": file_path, "filename": os.path.basename(file_path)})
        logged_body = "Изображение"
    elif msg.document:
        mime = msg.document.mime_type or ""
        if not mime.startswith("image/"):
            return await msg.answer("Можно отправлять только изображения в качестве вложений.")
        file_info = await msg.document.get_file()
        extension = os.path.splitext(msg.document.file_name or "attachment")[1] or ""
        file_path = os.path.join(tempfile.gettempdir(), f"{msg.document.file_unique_id}{extension}")
        await file_info.download(destination=file_path)
        attachments.append({"path": file_path, "filename": msg.document.file_name or os.path.basename(file_path)})
        logged_body = "Изображение"
    else:
        logged_body = body

    try:
        sent = await send_email(incoming["from_email"], subject, body, acc, attachments=attachments)
    finally:
        for att in attachments:
            try:
                os.remove(att["path"])
            except Exception:
                pass

    if sent:
        add_conversation_message(
            acc["id"],
            incoming["from_email"],
            "outgoing",
            subject,
            logged_body,
            last_adlink_by_email(incoming["from_email"], msg.chat.id),
            created_at=datetime.now(timezone.utc).isoformat(),
            user_id=msg.chat.id,
        )
        await msg.answer("Ответ отправлен!", reply_markup=types.ReplyKeyboardRemove())
        await msg.answer("Главное меню:", reply_markup=main_menu())
    else:
        await msg.answer("Не удалось отправить ответ.")

    await state.finish()


@dp.callback_query_handler(lambda c: c.data == "hide_message")
async def hide_message(call: types.CallbackQuery):
    try:
        await call.message.delete()
    except Exception:
        pass


# ---------------------------------------------------------
#  START
# ---------------------------------------------------------
if __name__ == "__main__":
    init_db()
    log.info("BOT STARTED")
    async def on_startup(dispatcher):
        dispatcher.loop.create_task(check_inboxes())

    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
