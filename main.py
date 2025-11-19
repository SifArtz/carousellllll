import json
import asyncio
import logging
import smtplib
import imaplib
import email
from email.header import decode_header
import aiohttp
import dns.resolver
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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


# ---------------------------------------------------------
# /start
# ---------------------------------------------------------
@dp.message_handler(commands=["start"])
async def start_cmd(msg: types.Message):
    global MAIN_CHAT_ID
    MAIN_CHAT_ID = msg.chat.id
    await msg.answer("Главное меню:", reply_markup=main_menu())
    log.info(f"/start от {msg.chat.id}")


# ---------------------------------------------------------
# Главные кнопки
# ---------------------------------------------------------
@dp.callback_query_handler(lambda c: c.data == "start_task")
async def click_start_task(call: types.CallbackQuery):
    accounts = get_accounts()
    if not accounts:
        return await call.message.edit_text(
            "Нет аккаунтов. Добавьте почту.",
            reply_markup=main_menu()
        )

    await call.message.edit_text("Выберите аккаунт:", reply_markup=accounts_menu(accounts))


@dp.callback_query_handler(lambda c: c.data == "add_account")
async def add_acc_click(call: types.CallbackQuery):
    await AddAccount.email.set()
    await call.message.edit_text("Введите Gmail email:")


@dp.callback_query_handler(lambda c: c.data == "tasks")
async def tasks_click(call: types.CallbackQuery):
    tasks = get_tasks()

    if not tasks:
        return await call.message.edit_text("Задач нет.", reply_markup=main_menu())

    await call.message.edit_text("Список задач:", reply_markup=tasks_menu(tasks))


@dp.callback_query_handler(lambda c: c.data == "settings")
async def settings_click(call: types.CallbackQuery):
    await call.message.edit_text("Настройки:", reply_markup=settings_menu())


@dp.callback_query_handler(lambda c: c.data == "back")
async def back_click(call: types.CallbackQuery):
    await call.message.edit_text("Главное меню:", reply_markup=main_menu())


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
    await msg.answer("Аккаунт добавлен!", reply_markup=main_menu())
    await state.finish()


# ---------------------------------------------------------
#  Настройки
# ---------------------------------------------------------
@dp.callback_query_handler(lambda c: c.data == "set_token")
async def set_token_click(call):
    await SetToken.token.set()
    await call.message.edit_text("Введите AI Token:")


@dp.message_handler(state=SetToken.token)
async def save_token(msg, state):
    set_ai_token(msg.text)
    await msg.answer("AI Token сохранён!", reply_markup=main_menu())
    await state.finish()


@dp.callback_query_handler(lambda c: c.data == "set_delay")
async def set_delay_click(call):
    await SetDelay.delay.set()
    await call.message.edit_text("Введите задержку в секундах:")


@dp.message_handler(state=SetDelay.delay)
async def save_delay(msg, state):
    try:
        d = int(msg.text)
    except:
        return await msg.answer("Введите правильное число!")

    set_delay(d)
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

    text = (
        f"<b>{acc['email']}</b>\n"
        f"Имя: {acc['name']}\n"
        f"Proxy: {acc['proxy'] or 'нет'}"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=account_actions(acc_id))


@dp.callback_query_handler(lambda c: c.data.startswith("acc_del_"))
async def delete_acc(call):
    acc_id = int(call.data.split("_")[2])
    delete_account(acc_id)
    await call.message.edit_text("Аккаунт удалён.", reply_markup=main_menu())


# ---------------------------------------------------------
#   Запуск задачи
# ---------------------------------------------------------
@dp.callback_query_handler(lambda c: c.data.startswith("acc_start_"))
async def start_task(call, state):
    acc_id = int(call.data.split("_")[2])
    await state.update_data(acc_id=acc_id)

    await UploadTaskFile.waiting_file.set()
    await call.message.edit_text("Отправьте .txt файл с JSON данными.")


# ---------------------------------------------------------
#   Получение файла
# ---------------------------------------------------------
@dp.message_handler(content_types=["document"], state=UploadTaskFile.waiting_file)
async def file_received(msg, state):

    file_info = await msg.document.get_file()
    path = f"./{msg.document.file_name}"
    await file_info.download(destination=path)

    f = open(path, "r", encoding="utf-8-sig")
    data = json.load(f)
    f.close()

    items = [{
        "title": v["title"],
        "price": v["price"],
        "img_url": v["img_url"],
        "seller": v["seller"],
        "adlink": v.get("adlink", "")
    } for v in data.values()]

    st = await state.get_data()
    acc_id = st["acc_id"]

    task_id = create_task(acc_id, len(items))

    asyncio.create_task(run_task(task_id, acc_id, items, msg.chat.id))

    await msg.answer("Задача запущена!", reply_markup=main_menu())
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
def send_sync(to, subject, text, acc):
    try:
        msg = MIMEMultipart()
        msg["From"] = acc["email"]
        msg["To"] = to
        msg["Subject"] = subject

        msg.attach(MIMEText(text, "plain"))

        s = smtplib.SMTP("smtp.gmail.com", 587, timeout=10)
        s.starttls()
        s.login(acc["email"], acc["app_password"])
        s.sendmail(acc["email"], to, msg.as_string())
        s.quit()
        return True
    except Exception as e:
        log.error(f"Ошибка отправки {to}: {e}")
        return False


async def send_email(to, subject, text, acc):
    log.info(f"[SEND] → {to}")
    return await asyncio.to_thread(send_sync, to, subject, text, acc)


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

    async with aiohttp.ClientSession() as session:
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
            js = await r.json()

    txt = js["choices"][0]["message"]["content"]
    out = json.loads(txt)

    log.info(f"[AI] Сгенерировано: {out['subject']}")

    return out


# ---------------------------------------------------------
#  Фоновая задача
# ---------------------------------------------------------
async def run_task(task_id, acc_id, items, chat_id):

    acc = get_account(acc_id)
    delay = get_settings()["send_delay"]

    log_path = f"task_{task_id}.txt"
    f = open(log_path, "w", encoding="utf-8")

    valid = 0
    sent = 0

    for item in items:
        email = f"{item['seller']}@gmail.com"
        log.info(f"[TASK] Обработка продавца {email}")

        # SMTP
        if not await smtp_check(email):
            continue

        update_valid(task_id)
        valid += 1

        # AI
        ai_out = await ai_generate(item["title"], item["seller"], acc["name"])
        subject = ai_out["subject"]
        message = ai_out["message"]

        # SEND
        if await send_email(email, subject, message, acc):
            update_sent(task_id)
            sent += 1

        # LOG FILE
        line = f"{email} | {item['title']} | {item['price']} | {item['img_url']} | {item['adlink']}\n"
        f.write(line)

        # DB log
        log_item(task_id, email, item["title"], item["price"], item["img_url"], item["adlink"])

        await asyncio.sleep(delay)

    f.close()
    finish_task(task_id, log_path)

    await bot.send_message(
        chat_id,
        f"Задача #{task_id} завершена!\n"
        f"Всего продавцов: {len(items)}\n"
        f"Валидных email: {valid}\n"
        f"Отправлено: {sent}"
    )

    log.info(f"[TASK] Задача #{task_id} завершена!")


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
    task = next(t for t in get_tasks() if t["id"] == task_id)

    text = (
        f"🆔 Задача #{task['id']}\n"
        f"Статус: {task['status']}\n"
        f"Всего продавцов: {task['total_sellers']}\n"
        f"Валидных email: {task['valid_emails']}\n"
        f"Отправлено: {task['sent_emails']}\n"
    )

    await call.message.edit_text(text, reply_markup=task_actions(task_id))


# ---------------------------------------------------------
#   ОБНОВИТЬ
# ---------------------------------------------------------
@dp.callback_query_handler(lambda c: c.data.endswith("_refresh"))
async def refresh_task(call):
    task_id = int(call.data.split("_")[1])
    task = next(t for t in get_tasks() if t["id"] == task_id)

    text = (
        f"🆔 Задача #{task['id']}\n"
        f"Статус: {task['status']}\n"
        f"Всего продавцов: {task['total_sellers']}\n"
        f"Валидных email: {task['valid_emails']}\n"
        f"Отправлено: {task['sent_emails']}\n"
    )

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
    task = next(t for t in get_tasks() if t["id"] == task_id)

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
            body = _extract_text_body(msg)
            preview = body.strip().splitlines()[0][:200] if body else ""
            messages.append({
                "message_id": message_id,
                "from_email": from_email,
                "subject": subject,
                "preview": preview
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
                        msg_data["preview"]
                    )

                    if not incoming_id:
                        continue

                    text = (
                        f"📩 Новое письмо\n"
                        f"От: {msg_data['from_email']}\n"
                        f"Тема: {msg_data['subject']}\n\n"
                        f"{msg_data['preview'] or 'Без текста'}"
                    )

                    if MAIN_CHAT_ID:
                        await bot.send_message(
                            MAIN_CHAT_ID,
                            text,
                            reply_markup=reply_button(incoming_id)
                        )
            except Exception as e:
                log.warning(f"[IMAP] Ошибка для {acc['email']}: {e}")

        await asyncio.sleep(60)


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
        f"Введите ответ для {incoming['from_email']} (тема: {incoming['subject']})"
    )


@dp.message_handler(state=ReplyMessage.waiting_text)
async def send_reply(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    incoming = get_incoming(data.get("incoming_id"))
    if not incoming:
        await msg.answer("Не удалось найти исходное письмо.")
        return await state.finish()

    acc = get_account(incoming["account_id"])
    subject = f"Re: {incoming['subject']}"
    body = msg.text

    if await send_email(incoming["from_email"], subject, body, acc):
        await msg.answer("Ответ отправлен!", reply_markup=main_menu())
    else:
        await msg.answer("Не удалось отправить ответ.")

    await state.finish()


# ---------------------------------------------------------
#  START
# ---------------------------------------------------------
if __name__ == "__main__":
    init_db()
    log.info("BOT STARTED")
    async def on_startup(dispatcher):
        dispatcher.loop.create_task(check_inboxes())

    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
