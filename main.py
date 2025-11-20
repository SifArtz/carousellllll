import asyncio
import contextlib
import email
import html
import json
import logging
import os
import random
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
API_TOKEN = "8153409500:AAG8SBAE8wr8QxyOsza6LkIsPxVNS4GTr_M"
bot = Bot(API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
MAIN_CHAT_ID = None


def _format_task_text(task):
    return (
        f"🆔 Задача #{task['id']}\n"
        f"Статус: {task['status']}\n"
        f"Всего продавцов: {task['total_sellers']}\n"
        f"Валидных email: {task['valid_emails']}\n"
        f"Отправлено: {task['sent_emails']}\n"
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
    global MAIN_CHAT_ID
    MAIN_CHAT_ID = msg.chat.id
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
    settings = get_settings()
    if not settings.get("ai_token"):
        return await call.message.edit_text(
            "⚠️ Сначала укажите AI Token в настройках.",
            reply_markup=main_menu()
        )

    accounts = get_accounts()
    if not accounts:
        return await call.message.edit_text(
            "Нет аккаунтов. Добавьте почту.",
            reply_markup=main_menu()
        )

    await call.message.edit_text("Выберите аккаунт:", reply_markup=accounts_menu(accounts))


@dp.callback_query_handler(lambda c: c.data.startswith("accounts_page_"))
async def accounts_page(call: types.CallbackQuery):
    page = int(call.data.split("_")[2])
    accounts = get_accounts()
    if not accounts:
        return await call.message.edit_text(
            "Нет аккаунтов. Добавьте почту.",
            reply_markup=main_menu()
        )

    await call.message.edit_text("Выберите аккаунт:", reply_markup=accounts_menu(accounts, page=page))


@dp.callback_query_handler(lambda c: c.data == "add_account")
async def add_acc_click(call: types.CallbackQuery):
    await AddAccount.email.set()
    await call.message.edit_text("Введите Gmail email:")
    await call.message.answer("Ожидаю ввод...", reply_markup=cancel_keyboard())


@dp.callback_query_handler(lambda c: c.data == "tasks")
async def tasks_click(call: types.CallbackQuery):
    tasks = get_tasks()

    if not tasks:
        return await call.message.edit_text("Задач нет.", reply_markup=main_menu())

    await call.message.edit_text("Список задач:", reply_markup=tasks_menu(tasks))


@dp.callback_query_handler(lambda c: c.data.startswith("tasks_page_"))
async def tasks_page(call: types.CallbackQuery):
    page = int(call.data.split("_")[2])
    tasks = get_tasks()
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
    total = count_unique_senders()
    if not total:
        if isinstance(message_obj, types.CallbackQuery):
            return await message_obj.message.edit_text("Входящих писем нет.", reply_markup=main_menu())
        return await message_obj.answer("Входящих писем нет.", reply_markup=main_menu())

    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page
    items = get_latest_incoming(limit=per_page, offset=offset)
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
        data["email"], data["app_password"], data["name"], proxy
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
    await call.message.edit_text("Введите AI Token:")
    await call.message.answer("Ожидаю ввод...", reply_markup=cancel_keyboard())


@dp.message_handler(state=SetToken.token)
async def save_token(msg, state):
    set_ai_token(msg.text)
    await msg.answer("AI Token сохранён!", reply_markup=types.ReplyKeyboardRemove())
    await msg.answer("AI Token сохранён!", reply_markup=main_menu())
    await state.finish()


@dp.callback_query_handler(lambda c: c.data == "set_delay")
async def set_delay_click(call):
    await SetDelay.delay.set()
    await call.message.edit_text("Введите задержку в секундах:")
    await call.message.answer("Ожидаю ввод...", reply_markup=cancel_keyboard())


@dp.message_handler(state=SetDelay.delay)
async def save_delay(msg, state):
    try:
        d = int(msg.text)
    except:
        return await msg.answer("Введите правильное число!")

    if d < 0:
        return await msg.answer("Задержка не может быть отрицательной.")

    set_delay(d)
    await msg.answer("Задержка сохранена!", reply_markup=types.ReplyKeyboardRemove())
    await msg.answer("Задержка сохранена!", reply_markup=main_menu())
    await state.finish()


# ---------------------------------------------------------
#  Просмотр аккаунта + запуск задачи
# ---------------------------------------------------------
@dp.callback_query_handler(
    lambda c: c.data.startswith("acc_") and "_start_" not in c.data and "_del_" not in c.data
)
async def view_acc(call):
    acc_id = int(call.data.split("_")[1])
    acc = get_account(acc_id)
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
    if not get_account(acc_id):
        return await call.answer("Аккаунт не найден", show_alert=True)
    delete_account(acc_id)
    await call.message.edit_text("Аккаунт удалён.", reply_markup=main_menu())


# ---------------------------------------------------------
#   Запуск задачи
# ---------------------------------------------------------
@dp.callback_query_handler(lambda c: c.data.startswith("acc_start_"))
async def start_task(call, state):
    acc_id = int(call.data.split("_")[2])
    if not get_account(acc_id):
        return await call.answer("Аккаунт не найден", show_alert=True)
    await state.update_data(acc_id=acc_id)

    await UploadTaskFile.waiting_file.set()
    await call.message.edit_text("Отправьте .txt файл с JSON данными.")


@dp.callback_query_handler(lambda c: c.data.startswith("inbox_view_"))
async def inbox_view(call: types.CallbackQuery):
    incoming_id = int(call.data.split("_")[2])
    incoming = get_incoming(incoming_id)
    if not incoming:
        return await call.answer("Письмо не найдено", show_alert=True)

    adlink = last_adlink_by_email(incoming["from_email"])
    body = incoming.get("body_full") or incoming.get("body_preview") or "Без текста"
    text = (
        f"📩 Письмо | {incoming['from_email']}\n\n"
        f"🔗 {_format_link(adlink)}\n"
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

    task_id = create_task(acc_id, len(items))
    status_msg = await msg.answer(
        f"Задача #{task_id} запущена. Обработка продавцов...", reply_markup=task_actions(task_id)
    )

    asyncio.create_task(
        run_task(task_id, acc_id, items, msg.chat.id, status_msg.chat.id, status_msg.message_id)
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
        msg["From"] = acc["email"]
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
async def ai_generate(title, seller, acc_name):
    token = get_settings()["ai_token"]

    prompt = f"""
You are a professional copywriter specialising in generating highly unique, conversational and natural English messages for Carousell Singapore buyers.

GOAL:
Create ONE fully original message that sounds like a real buyer on Carousell asking about a product.

MANDATORY (VERY IMPORTANT):
- The message MUST contain a question about availability, BUT it cannot be a standard phrasing like:
  “Is this available?”, "Still available?", "Available?", "Is this still available?"
- The availability question MUST be written in a unique, natural, human way each time.
  Examples of ALLOWED styles:
  - "Just wanted to check if it's still up for grabs?"
  - "Are you still letting this go?"
  - "Is this item still on your list?"
  You may create other unique forms — they MUST vary every time.

ALSO MANDATORY:
- Add a small, natural comment about the item "{title}".
  It must feel personal, curious or observational.
  Examples:
  - “It caught my eye because…”
  - “Been looking for something similar…”
  - “The condition looks nice from the photos…”
  But do NOT reuse specific examples — generate new ones every time.

STRICT RULES:
- NO generic marketplace templates.
- NO robotic or repetitive structures.
- NO short or lazy messages — make it feel genuinely human.
- No bullet points, no lists.
- Only ONE final message.
- NO heavy Singlish (NO “lah”, “lor”, “leh”, “hor”), but a casual SG tone is ok.
- Natural, friendly, polite, slightly casual.

EMAIL SUBJECT:
Use EXACT format (do not change it):
"Enquiry about {title} | Carousell"

EMAIL MESSAGE TO SELLER "{seller}":
- Must mention that you came across the item on Carousell.
- Must include a UNIQUE availability question (not a template).
- Must include a UNIQUE personal comment about the item.
- Must end with the buyer name: {acc_name}

FORMAT:
Return ONLY valid JSON:

{{
  "subject": "",
  "message": ""
}}
"""
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
                r.raise_for_status()
                js = await r.json()
    except Exception as e:
        log.error(f"[AI] Ошибка генерации: {e}")
        return {
            "subject": f"Question about {title}",
            "message": f"Hi! I'm interested in {title}. Is it still available? - {acc_name}",
        }

    try:
        txt = js["choices"][0]["message"]["content"]
        out = json.loads(txt)
    except Exception as e:
        log.error(f"[AI] Ошибка парсинга ответа: {e}")
        out = {
            "subject": f"Question about {title}",
            "message": f"Hello! I liked {title}. Is it still up for sale? - {acc_name}",
        }

    log.info(f"[AI] Сгенерировано: {out['subject']}")

    return out


# ---------------------------------------------------------
#  Фоновая задача
# ---------------------------------------------------------


async def run_task(task_id, acc_id, items, chat_id, status_chat_id=None, status_msg_id=None):

    acc = get_account(acc_id)
    if not acc:
        log.error(f"[TASK] Аккаунт {acc_id} не найден")
        return

    delay = max(0, get_settings().get("send_delay", 0))

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

        task_state = get_task(task_id)
        if not task_state:
            return

        text = _format_task_text({
            **task_state,
            "status": status,
            "valid_emails": valid,
            "sent_emails": sent,
            "total_sellers": len(items)
        })

        try:
            await bot.edit_message_text(
                text=text,
                chat_id=status_chat_id,
                message_id=status_msg_id,
                reply_markup=task_actions(task_id)
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
                ai_out = await ai_generate(item["title"], item["seller"], acc["name"])
            except Exception as e:
                log.error(f"[TASK] AI ошибка для {email}: {e}")
                continue

            subject = ai_out.get("subject") or f"Question about {item['title']}"
            message = ai_out.get("message") or "Hello! Is this still available?"

            line = f"{email} | {item['title']} | {item['price']} | {item['img_url']} | {item['adlink']}\n"
            f.write(line)
            log_item(task_id, email, item["title"], item["price"], item["img_url"], item["adlink"])

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
                        created_at=datetime.now(timezone.utc).isoformat()
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
)
async def task_view(call):
    task_id = int(call.data.split("_")[1])
    task = get_task(task_id)
    if not task:
        return await call.answer("Задача не найдена", show_alert=True)

    text = _format_task_text(task)

    await call.message.edit_text(text, reply_markup=task_actions(task_id))


# ---------------------------------------------------------
#   ОБНОВИТЬ
# ---------------------------------------------------------
@dp.callback_query_handler(lambda c: c.data.endswith("_refresh"))
async def refresh_task(call):
    task_id = int(call.data.split("_")[1])
    task = get_task(task_id)
    if not task:
        return await call.answer("Задача не найдена", show_alert=True)

    text = _format_task_text(task)

    try:
        await call.message.edit_text(text, reply_markup=task_actions(task_id))
    except Exception:
        await call.answer("Нет обновлений", show_alert=False)


# ---------------------------------------------------------
#  ЛОГ-ФАЙЛ
# ---------------------------------------------------------
@dp.callback_query_handler(lambda c: c.data.startswith("task_log_"))
async def send_log(call):
    task_id = int(call.data.split("_")[2])
    task = next((t for t in get_tasks() if t["id"] == task_id), None)
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
                unseen = await asyncio.to_thread(fetch_unseen_messages, acc)
                for msg_data in unseen:
                    if incoming_exists(msg_data["message_id"]):
                        continue

                    incoming_id = add_incoming_message(
                        acc["id"],
                        msg_data["message_id"],
                        msg_data["from_email"],
                        msg_data["subject"],
                        msg_data["preview"],
                        msg_data.get("body"),
                        msg_data.get("received_at")
                    )

                    if not incoming_id:
                        continue

                    adlink = last_adlink_by_email(msg_data["from_email"])

                    add_conversation_message(
                        acc["id"],
                        msg_data["from_email"],
                        "incoming",
                        msg_data["subject"],
                        msg_data.get("body") or msg_data["preview"],
                        adlink,
                        msg_data["message_id"],
                        msg_data.get("received_at")
                    )

                    text = (
                        f"📩 Новое письмо | {msg_data['from_email']}\n\n"
                        f"🔗 {_format_link(adlink)}\n"
                        f"🕒 Ответ получен: {_format_timestamp(msg_data.get('received_at'))}\n\n"
                        f"💬 Текст сообщения:\n\n{_escape_html(msg_data.get('body') or msg_data['preview'] or 'Без текста')}"
                    )

                    if MAIN_CHAT_ID:
                        await bot.send_message(
                            MAIN_CHAT_ID,
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
    incoming = get_incoming(incoming_id)
    if not incoming:
        return await call.answer("История не найдена", show_alert=True)

    email_addr = incoming["from_email"]
    history = get_conversation(email_addr, limit=None)

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
            "",
            f"🔗 {_format_link(last_adlink_by_email(email_addr))}",
            "",
        ]

        for h in history:
            icon = "🦣" if h["direction"] == "outgoing" else "👤"
            body_text = (h["body"] or "(пусто)").strip()
            display_body = "Изображение" if body_text.lower() == "изображение" else body_text
            lines.append(f"{icon} [{_format_timestamp(h['created_at'])}] {_escape_html(display_body)}")

        text = "\n".join(lines) if lines else "История пуста."
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
    incoming = get_incoming(data.get("incoming_id"))
    if not incoming:
        await msg.answer("Не удалось найти исходное письмо.")
        return await state.finish()

    acc = get_account(incoming["account_id"])
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
            last_adlink_by_email(incoming["from_email"]),
            created_at=datetime.now(timezone.utc).isoformat()
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
