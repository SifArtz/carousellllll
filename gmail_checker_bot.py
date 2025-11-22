import asyncio
import os
import re
import smtplib
import tempfile
from typing import List, Tuple

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Укажите токен бота в переменной окружения BOT_TOKEN")

bot = Bot(BOT_TOKEN)
dp = Dispatcher(bot)

EMAIL_REGEX = re.compile(r"^[^@\s]+@gmail\.com$", re.IGNORECASE)
MX_SERVERS = [
    "gmail-smtp-in.l.google.com",
    "alt1.gmail-smtp-in.l.google.com",
    "alt2.gmail-smtp-in.l.google.com",
]


def _normalize_email(raw_email: str) -> str:
    candidate = raw_email.strip()
    if not candidate:
        return ""

    if "@" not in candidate:
        candidate = f"{candidate}@gmail.com"
    return candidate.lower()


def _parse_lines(path: str) -> List[Tuple[str, str, str]]:
    rows: List[Tuple[str, str, str]] = []
    with open(path, "r", encoding="utf-8", errors="ignore") as src:
        for line in src:
            parts = [part.strip() for part in line.split("|")]
            if len(parts) < 3:
                continue

            email_part, title, ad_link = parts[0], parts[1], parts[2]
            email_value = _normalize_email(email_part)
            rows.append((email_value, title, ad_link))
    return rows


def _check_gmail_exists(email_value: str) -> bool:
    if not EMAIL_REGEX.match(email_value):
        return False

    for mx_server in MX_SERVERS:
        try:
            with smtplib.SMTP(mx_server, 25, timeout=10) as smtp:
                smtp.ehlo_or_helo_if_needed()
                smtp.mail("validator@example.com")
                code, _ = smtp.rcpt(email_value)
                if code == 250:
                    return True
        except (smtplib.SMTPException, OSError):
            continue
    return False


async def _validate_rows(rows: List[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
    valid_rows: List[Tuple[str, str, str]] = []
    for email_value, title, ad_link in rows:
        exists = await asyncio.to_thread(_check_gmail_exists, email_value)
        if exists:
            valid_rows.append((email_value, title, ad_link))
    return valid_rows


@dp.message_handler(commands=["start", "help"])
async def start_handler(message: types.Message):
    await message.answer(
        "Пришлите текстовый файл с данными в формате: \n"
        "email_или_логин | title | adLink\n"
        "Бот автоматически добавит @gmail.com к логину, проверит синтаксис и существование адреса, "
        "после чего вернёт файл с валидными строками."
    )


@dp.message_handler(content_types=[types.ContentType.DOCUMENT])
async def document_handler(message: types.Message):
    document = message.document
    await message.answer("Файл получен, начинаю обработку...")

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        await document.download(destination_file=tmp)
        input_path = tmp.name

    rows = _parse_lines(input_path)
    if not rows:
        await message.answer("Не удалось найти ни одной строки формата email | title | adLink.")
        return

    valid_rows = await _validate_rows(rows)
    if not valid_rows:
        await message.answer("Валидных gmail-адресов не найдено.")
        return

    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as out:
        for email_value, title, ad_link in valid_rows:
            out.write(f"{email_value} | {title} | {ad_link}\n")
        output_path = out.name

    await message.answer_document(
        types.InputFile(output_path, filename="validated_emails.txt"),
        caption=f"Готово! Валидных записей: {len(valid_rows)}",
    )


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
