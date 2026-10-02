import json
import re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from dotenv import load_dotenv
import os


# ============================================================
# НАЛАШТУВАННЯ
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

CARDS_FILE = Path("data/cards.json")
REQUESTS_FILE = Path("data/requests.json")

CARDS_FILE.parent.mkdir(parents=True, exist_ok=True)


# Час України
KYIV_TZ = ZoneInfo("Europe/Kyiv")


# ============================================================
# РОБОТА З ОСНОВНОЮ БАЗОЮ КАРТ
# ============================================================

def load_cards():
    if not CARDS_FILE.exists():
        return {}

    try:
        with open(CARDS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

            if isinstance(data, list):
                return {"old_pool": data}

            if isinstance(data, dict):
                return data

            return {}

    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_cards(cards):
    CARDS_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(CARDS_FILE, "w", encoding="utf-8") as file:
        json.dump(
            cards,
            file,
            ensure_ascii=False,
            indent=4
        )


# ============================================================
# РОБОТА З БАЗОЮ ДУБЛІВ
# ============================================================

def load_requests():
    if not REQUESTS_FILE.exists():
        return {}

    try:
        with open(REQUESTS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

            if isinstance(data, dict):
                return data

            return {}

    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_requests(requests):
    REQUESTS_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(REQUESTS_FILE, "w", encoding="utf-8") as file:
        json.dump(
            requests,
            file,
            ensure_ascii=False,
            indent=4
        )


# ============================================================
# CHAT ID
# ============================================================

def get_chat_id(update: Update):
    chat = update.effective_chat

    if not chat:
        return None

    return str(chat.id)


# ============================================================
# ОСНОВНА БАЗА КАРТ ПО ГРУПАХ
# ============================================================

def get_chat_pool(update: Update):
    all_cards = load_cards()

    chat_id = get_chat_id(update)

    if not chat_id:
        return []

    return all_cards.get(chat_id, [])


def save_chat_pool(update: Update, pool):
    all_cards = load_cards()

    chat_id = get_chat_id(update)

    if not chat_id:
        return

    all_cards[chat_id] = pool

    save_cards(all_cards)


# ============================================================
# НОРМАЛІЗАЦІЯ КАРТ
# ============================================================

def normalize_card(card):
    """
    Перетворює:

    4441 1111 2222 3333
    4441-1111-2222-3333
    4441111122223333

    у:

    4441111122223333
    """

    if not card:
        return ""

    card = str(card).strip()

    # Прибираємо Telegram Markdown
    card = card.replace("**", "")
    card = card.replace("__", "")
    card = card.replace("`", "")

    # Прибираємо пробіли та дефіси
    card = re.sub(r"[\s-]", "", card)

    return card


def normalize_pattern(card):
    if not card:
        return ""

    card = str(card).strip()

    card = card.replace("**", "")
    card = card.replace("__", "")
    card = card.replace("`", "")

    card = re.sub(r"[\s-]", "", card)

    return card


# ============================================================
# ПЕРЕВІРКА КАРТИ
# ============================================================

def is_valid_card(card):
    normalized = normalize_card(card)

    if not normalized.isdigit():
        return False

    if not 13 <= len(normalized) <= 19:
        return False

    return True


def is_valid_pattern(card):
    normalized = normalize_pattern(card)

    if not re.fullmatch(r"[\d\*]+", normalized):
        return False

    digit_count = sum(c.isdigit() for c in normalized)

    if digit_count < 4:
        return False

    if not 13 <= len(normalized) <= 19:
        return False

    return True


# ============================================================
# ПОРІВНЯННЯ КАРТ
# ============================================================

def cards_match(pattern, actual):
    pattern = normalize_pattern(pattern)
    actual = normalize_card(actual)

    if len(pattern) != len(actual):
        return False

    for p, a in zip(pattern, actual):

        if p == "*":
            continue

        if p != a:
            return False

    return True


# ============================================================
# ПОШУК КАРТ У ПОВІДОМЛЕННІ
# ============================================================

def extract_cards(text):
    """
    Шукає картки в будь-якому тексті.

    Підтримує:

    4441111122223333
    4441 1111 2222 3333
    4441-1111-2222-3333

    Також знаходить карту просто в повідомленні
    без будь-яких додаткових слів.
    """

    if not text:
        return []

    result = []

    # --------------------------------------------------------
    # Варіант 1:
    # 4441 1111 2222 3333
    # 4441-1111-2222-3333
    # 4441111122223333
    # --------------------------------------------------------

    pattern = r"(?<!\d)(?:\d{4}[\s-]?){3}\d{4}(?!\d)"

    matches = re.findall(pattern, text)

    for match in matches:

        card = normalize_card(match)

        if is_valid_card(card):
            result.append(card)

    # --------------------------------------------------------
    # Варіант 2:
    # будь-яка суцільна послідовність 13-19 цифр
    # --------------------------------------------------------

    pattern = r"(?<!\d)\d{13,19}(?!\d)"

    matches = re.findall(pattern, text)

    for match in matches:

        card = normalize_card(match)

        if is_valid_card(card):
            result.append(card)

    # Прибираємо дублікати
    return list(dict.fromkeys(result))


# ============================================================
# ДУБЛІ ЗА КАРТКОЮ
# ============================================================

def get_today():
    """
    Повертає сьогоднішню дату саме за київським часом.
    """

    return datetime.now(KYIV_TZ).strftime("%Y-%m-%d")


def cleanup_old_requests(requests):
    """
    Залишаємо тільки сьогоднішні записи.

    Старі дні більше не потрібні для антидубля.
    """

    today = get_today()

    changed = False

    for chat_id in list(requests.keys()):

        chat_data = requests.get(chat_id)

        if not isinstance(chat_data, dict):
            del requests[chat_id]
            changed = True
            continue

        for date_key in list(chat_data.keys()):

            if date_key != today:
                del chat_data[date_key]
                changed = True

        if not chat_data:
            del requests[chat_id]
            changed = True

    return changed


def check_duplicate_card(update: Update, card):
    """
    ГОЛОВНА ЛОГІКА АНТИДУБЛЯ.

    Перевіряємо ВИКЛЮЧНО номер картки.

    Неважливо:
    - який текст заявки;
    - яка сума;
    - який ID;
    - який курс;
    - хто власник;
    - чи це просто номер картки.

    Важливо тільки:

    chat_id + сьогоднішня дата + номер картки
    """

    chat_id = get_chat_id(update)

    if not chat_id:
        return False, 0

    card = normalize_card(card)

    if not is_valid_card(card):
        return False, 0

    today = get_today()

    requests = load_requests()

    # --------------------------------------------------------
    # Видаляємо старі дні
    # --------------------------------------------------------

    cleanup_old_requests(requests)

    # --------------------------------------------------------
    # Створюємо структуру
    # --------------------------------------------------------

    if chat_id not in requests:
        requests[chat_id] = {}

    if today not in requests[chat_id]:
        requests[chat_id][today] = {}

    today_cards = requests[chat_id][today]

    # --------------------------------------------------------
    # Перевіряємо картку
    # --------------------------------------------------------

    previous_count = today_cards.get(card, 0)

    is_duplicate = previous_count > 0

    # Додаємо поточне використання
    today_cards[card] = previous_count + 1

    save_requests(requests)

    return is_duplicate, previous_count


# ============================================================
# ЗАПОБІГАННЯ ПОВТОРНІЙ ОБРОБЦІ ТОГО САМОГО TELEGRAM MESSAGE
# ============================================================

def message_was_processed(update: Update):
    """
    Якщо Telegram повторно доставить той самий message,
    не будемо рахувати його як нову заявку.
    """

    chat = update.effective_chat
    message = update.effective_message

    if not chat or not message:
        return False

    chat_id = str(chat.id)
    message_id = str(message.message_id)

    requests = load_requests()

    if "__processed_messages__" not in requests:
        requests["__processed_messages__"] = {}

    processed = requests["__processed_messages__"]

    if chat_id not in processed:
        processed[chat_id] = {}

    today = get_today()

    if today not in processed[chat_id]:
        processed[chat_id][today] = []

    today_messages = processed[chat_id][today]

    if message_id in today_messages:
        return True

    today_messages.append(message_id)

    # Щоб база не росла нескінченно
    if len(today_messages) > 5000:
        processed[chat_id][today] = today_messages[-5000:]

    save_requests(requests)

    return False


# ============================================================
# АНТИДУБЛЬ ПОВІДОМЛЕННЯ
# ============================================================

async def process_duplicate_check(update: Update, text):
    """
    Просто шукаємо картки в повідомленні.

    НЕ перевіряємо, чи це "схоже на заявку".

    Це принципово.
    """

    if not text:
        return

    # --------------------------------------------------------
    # Не обробляємо один і той самий Telegram message двічі
    # --------------------------------------------------------

    if message_was_processed(update):
        return

    # --------------------------------------------------------
    # Шукаємо картки
    # --------------------------------------------------------

    cards = extract_cards(text)

    if not cards:
        return

    # --------------------------------------------------------
    # Перевіряємо кожну знайдену картку
    # --------------------------------------------------------

    for card in cards:

        is_duplicate, previous_count = check_duplicate_card(
            update,
            card
        )

        if not is_duplicate:
            continue

        # ----------------------------------------------------
        # Знайдено дубль
        # ----------------------------------------------------

        warning = (
            "🚨 **УВАГА — МОЖЛИВЕ ЗАДВОЄННЯ!**\n\n"
            f"💳 Карта: `{card}`\n\n"
            "⚠️ Ця карта вже зустрічалась у заявці "
            "сьогодні.\n\n"
            f"📊 Попередніх появ сьогодні: {previous_count}\n\n"
            "❗ Перевірте, будь ласка, чи не задвоєна "
            "заявка перед проведенням оплати."
        )

        try:
            await update.effective_message.reply_text(
                warning,
                parse_mode="Markdown"
            )

        except Exception as e:
            print(f"Помилка відправки попередження: {e}")


# ============================================================
# /PEREPLATA
# ============================================================

async def pereplata(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["pereplata"] = {
        "step": "card"
    }

    await update.message.reply_text(
        "💳 Введіть номер картки:"
    )


# ============================================================
# ОБРОБКА /PEREPLATA
# ============================================================

async def handle_pereplata(update: Update, context: ContextTypes.DEFAULT_TYPE):

    state = context.user_data.get("pereplata")

    if not state:
        return False

    text = update.message.text.strip()

    # --------------------------------------------------------
    # Крок 1 — номер картки
    # --------------------------------------------------------

    if state["step"] == "card":

        card = normalize_card(text)

        if not is_valid_card(card):

            await update.message.reply_text(
                "❌ Невірний номер картки.\n\n"
                "Введіть картку ще раз."
            )

            return True

        pool = get_chat_pool(update)

        # Перевіряємо, чи вже є така карта
        for item in pool:

            saved_card = item.get("card", "")

            if cards_match(saved_card, card):

                await update.message.reply_text(
                    "⚠️ Ця картка вже є у базі."
                )

                return True

        context.user_data["pereplata"] = {
            "step": "description",
            "card": card
        }

        await update.message.reply_text(
            "📝 Тепер введіть опис для цієї картки:"
        )

        return True

    # --------------------------------------------------------
    # Крок 2 — опис
    # --------------------------------------------------------

    if state["step"] == "description":

        card = state["card"]

        description = text

        pool = get_chat_pool(update)

        user = update.effective_user

        if user:

            added_by = user.full_name

            if user.username:
                added_by += f" (@{user.username})"

        else:
            added_by = "Невідомий користувач"

        pool.append({
            "card": card,
            "description": description,
            "added_by": added_by,
            "user_id": user.id if user else None
        })

        save_chat_pool(update, pool)

        context.user_data.pop("pereplata", None)

        await update.message.reply_text(
            "✅ Картку успішно додано!\n\n"
            f"💳 `{card}`\n"
            f"📝 {description}",
            parse_mode="Markdown"
        )

        return True

    return False


# ============================================================
# /CARDS
# ============================================================

async def cards_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    pool = get_chat_pool(update)

    if not pool:

        await update.message.reply_text(
            "📭 У цій групі база карт порожня."
        )

        return

    text = "💳 **КАРТИ ЦІЄЇ ГРУПИ**\n\n"

    for index, item in enumerate(pool, start=1):

        card = item.get("card", "")
        description = item.get("description", "")
        added_by = item.get("added_by", "")

        text += (
            f"{index}. `{card}`\n"
            f"📝 {description}\n"
            f"👤 {added_by}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="Markdown"
    )


# ============================================================
# /DELCARD
# ============================================================

async def delcard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text(
            "❌ Вкажіть номер картки.\n\n"
            "Наприклад:\n"
            "/delcard 4441111122223333"
        )

        return

    card = normalize_card("".join(context.args))

    if not is_valid_card(card):

        await update.message.reply_text(
            "❌ Невірний номер картки."
        )

        return

    pool = get_chat_pool(update)

    new_pool = []

    deleted = False

    for item in pool:

        saved_card = item.get("card", "")

        if cards_match(saved_card, card):
            deleted = True
            continue

        new_pool.append(item)

    if deleted:

        save_chat_pool(update, new_pool)

        await update.message.reply_text(
            f"✅ Картку `{card}` видалено.",
            parse_mode="Markdown"
        )

    else:

        await update.message.reply_text(
            "❌ Такої картки в цій групі немає."
        )


# ============================================================
# /CANCEL
# ============================================================

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data.pop("pereplata", None)

    await update.message.reply_text(
        "❌ Дію скасовано."
    )


# ============================================================
# ПОШУК КАРТ У БАЗІ
# ============================================================

async def check_saved_cards(update: Update, text):

    cards = extract_cards(text)

    if not cards:
        return

    pool = get_chat_pool(update)

    if not pool:
        return

    for actual_card in cards:

        for item in pool:

            saved_card = item.get("card", "")

            if not cards_match(saved_card, actual_card):
                continue

            description = item.get(
                "description",
                "Без опису"
            )

            added_by = item.get(
                "added_by",
                "Невідомо"
            )

            response = (
                "💳 **ЗНАЙДЕНО КАРТУ В БАЗІ**\n\n"
                f"Номер: `{actual_card}`\n"
                f"📝 Опис: {description}\n"
                f"👤 Додав: {added_by}"
            )

            try:

                await update.effective_message.reply_text(
                    response,
                    parse_mode="Markdown"
                )

            except Exception as e:

                print(
                    f"Помилка відповіді по карті: {e}"
                )


# ============================================================
# ГОЛОВНИЙ ОБРОБНИК ПОВІДОМЛЕНЬ
# ============================================================

async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.effective_message

    if not message:
        return

    text = message.text

    if not text:
        return

    # --------------------------------------------------------
    # Якщо зараз користувач проходить /pereplata
    # --------------------------------------------------------

    handled = await handle_pereplata(
        update,
        context
    )

    if handled:
        return

    # --------------------------------------------------------
    # Команди не перевіряємо як заявки
    # --------------------------------------------------------

    if text.startswith("/"):
        return

    # --------------------------------------------------------
    # АНТИДУБЛЬ
    #
    # Тут тепер НІЯКОГО looks_like_request().
    #
    # Будь-яке повідомлення з картою перевіряється.
    # --------------------------------------------------------

    await process_duplicate_check(
        update,
        text
    )

    # --------------------------------------------------------
    # Стара функція пошуку карт у вашій базі
    # --------------------------------------------------------

    await check_saved_cards(
        update,
        text
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN не знайдений у змінних середовища."
        )

    print("🤖 Бот запускається...")

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # Команди
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "pereplata",
            pereplata
        )
    )

    application.add_handler(
        CommandHandler(
            "cards",
            cards_command
        )
    )

    application.add_handler(
        CommandHandler(
            "delcard",
            delcard_command
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_command
        )
    )

    # --------------------------------------------------------
    # Звичайні повідомлення
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler
        )
    )

    print("✅ Бот запущений!")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()