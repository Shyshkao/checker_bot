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

# Основна база карт для /pereplata
CARDS_FILE = Path("data/cards.json")

# ОКРЕМА база для антидубля заявок
DUPLICATE_CARDS_FILE = Path("data/duplicate_cards.json")

# Створюємо папку data, якщо її немає
CARDS_FILE.parent.mkdir(parents=True, exist_ok=True)

# Український час
KYIV_TZ = ZoneInfo("Europe/Kyiv")


# ============================================================
# ОСНОВНА БАЗА КАРТ
# ============================================================

def load_cards():
    if not CARDS_FILE.exists():
        return {}

    try:
        with open(
            CARDS_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

            if isinstance(data, list):
                return {"old_pool": data}

            if isinstance(data, dict):
                return data

            return {}

    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_cards(cards):
    CARDS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        CARDS_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            cards,
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
# БАЗА КАРТ ОКРЕМО ДЛЯ КОЖНОЇ ГРУПИ
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
# НОРМАЛІЗАЦІЯ КАРТИ
# ============================================================

def normalize_card(card):
    """
    Перетворює:

    5355 2800 3668 8131
    5355-2800-3668-8131
    **5355 2800 3668 8131**
    `5355280036688131`

    у:

    5355280036688131
    """

    if not card:
        return ""

    card = str(card).strip()

    # Telegram Markdown
    card = card.replace("**", "")
    card = card.replace("__", "")
    card = card.replace("`", "")

    # Пробіли та дефіси
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

    digit_count = sum(
        c.isdigit()
        for c in normalized
    )

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
# ПОШУК КАРТ У БУДЬ-ЯКОМУ ПОВІДОМЛЕННІ
# ============================================================

def extract_cards(text):
    """
    Дістає карти з будь-якого повідомлення.

    Підтримує:

    5355280036688131

    5355 2800 3668 8131

    5355-2800-3668-8131

    **5355 2800 3668 8131**

    `5355280036688131`

    Тип заявки НЕ має значення.
    """

    if not text:
        return []

    result = []

    # --------------------------------------------------------
    # КАРТА ПО 4 ЦИФРИ
    # --------------------------------------------------------

    pattern_grouped = (
        r"(?<!\d)"
        r"(?:\d{4}[\s-]?){3}"
        r"\d{4}"
        r"(?!\d)"
    )

    matches = re.findall(
        pattern_grouped,
        text
    )

    for match in matches:

        card = normalize_card(match)

        if is_valid_card(card):
            result.append(card)

    # --------------------------------------------------------
    # СУЦІЛЬНА КАРТА 13-19 ЦИФР
    # --------------------------------------------------------

    pattern_plain = (
        r"(?<!\d)"
        r"\d{13,19}"
        r"(?!\d)"
    )

    matches = re.findall(
        pattern_plain,
        text
    )

    for match in matches:

        card = normalize_card(match)

        if is_valid_card(card):
            result.append(card)

    # --------------------------------------------------------
    # УНІКАЛЬНІ КАРТИ
    # --------------------------------------------------------

    return list(dict.fromkeys(result))


# ============================================================
# ============================================================
# АНТИДУБЛЬ КАРТ
# ============================================================
# ============================================================

def load_duplicate_cards():
    """
    Окрема база антидубля.

    Структура:

    {
        "CHAT_ID": {
            "2026-10-08": {
                "5355280036688131": {
                    "message_ids": [123, 456]
                }
            }
        }
    }
    """

    if not DUPLICATE_CARDS_FILE.exists():
        return {}

    try:
        with open(
            DUPLICATE_CARDS_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

            if isinstance(data, dict):
                return data

            return {}

    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_duplicate_cards(data):
    DUPLICATE_CARDS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        DUPLICATE_CARDS_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=4
        )


def get_today():
    """
    Сьогоднішня дата за київським часом.
    """

    return datetime.now(
        KYIV_TZ
    ).strftime("%Y-%m-%d")


def cleanup_duplicate_history(data):
    """
    Видаляємо всі старі дні.
    Для антидубля нам потрібні
    тільки заявки за сьогодні.
    """

    today = get_today()

    changed = False

    for chat_id in list(data.keys()):

        if not isinstance(
            data[chat_id],
            dict
        ):
            del data[chat_id]
            changed = True
            continue

        for date_key in list(
            data[chat_id].keys()
        ):

            if date_key != today:

                del data[chat_id][date_key]

                changed = True

        if not data[chat_id]:

            del data[chat_id]

            changed = True

    return changed


def register_card_for_duplicate_check(
    update: Update,
    card: str
):
    """
    ГОЛОВНА ФУНКЦІЯ АНТИДУБЛЯ.

    Перевіряється ТІЛЬКИ:

        група
        +
        сьогодні
        +
        номер картки

    Все інше ігнорується.
    """

    chat = update.effective_chat
    message = update.effective_message

    if not chat or not message:
        return False, 0

    # Нормалізуємо картку
    card = normalize_card(card)

    if not is_valid_card(card):
        return False, 0

    chat_id = str(chat.id)

    message_id = message.message_id

    today = get_today()

    # Завантажуємо базу
    data = load_duplicate_cards()

    # Видаляємо старі дні
    cleanup_duplicate_history(data)

    # --------------------------------------------------------
    # Створюємо групу
    # --------------------------------------------------------

    if chat_id not in data:

        data[chat_id] = {}

    # --------------------------------------------------------
    # Створюємо сьогоднішній день
    # --------------------------------------------------------

    if today not in data[chat_id]:

        data[chat_id][today] = {}

    today_data = data[chat_id][today]

    # --------------------------------------------------------
    # ПЕРША ПОЯВА КАРТИ СЬОГОДНІ
    # --------------------------------------------------------

    if card not in today_data:

        today_data[card] = {
            "message_ids": [
                message_id
            ]
        }

        save_duplicate_cards(data)

        return False, 0

    # --------------------------------------------------------
    # КАРТА ВЖЕ Є
    # --------------------------------------------------------

    card_data = today_data[card]

    if not isinstance(
        card_data,
        dict
    ):

        card_data = {
            "message_ids": []
        }

        today_data[card] = card_data

    message_ids = card_data.get(
        "message_ids",
        []
    )

    # --------------------------------------------------------
    # ТОЧНО ТЕ САМЕ TELEGRAM-ПОВІДОМЛЕННЯ
    #
    # Не рахуємо його повторно.
    # --------------------------------------------------------

    if message_id in message_ids:

        save_duplicate_cards(data)

        return False, max(
            0,
            len(message_ids) - 1
        )

    # --------------------------------------------------------
    # НОВЕ ПОВІДОМЛЕННЯ З ТІЄЮ САМОЮ КАРТКОЮ
    # --------------------------------------------------------

    previous_count = len(
        message_ids
    )

    message_ids.append(
        message_id
    )

    card_data["message_ids"] = message_ids

    save_duplicate_cards(data)

    return True, previous_count


async def process_duplicate_check(
    update: Update,
    text: str
):
    """
    Перевірка антидубля.

    Немає жодної перевірки типу заявки.

    Бот просто:

    1. Отримує повідомлення.
    2. Дістає з нього карти.
    3. Для кожної карти перевіряє сьогоднішню історію.
    4. Якщо карта вже була — попередження.
    """

    if not text:
        return

    # --------------------------------------------------------
    # Дістаємо ВСІ карти з повідомлення
    # --------------------------------------------------------

    cards = extract_cards(text)

    if not cards:
        return

    # --------------------------------------------------------
    # Перевіряємо кожну карту
    # --------------------------------------------------------

    for card in cards:

        is_duplicate, previous_count = (
            register_card_for_duplicate_check(
                update,
                card
            )
        )

        # Перша поява
        if not is_duplicate:
            continue

        # ----------------------------------------------------
        # ДРУГА / НАСТУПНА ПОЯВА
        # ----------------------------------------------------

        warning = (
            "🚨 **МОЖЛИВЕ ЗАДВОЄННЯ ЗАЯВКИ!**\n\n"
            f"💳 Карта: `{card}`\n\n"
            "⚠️ Ця картка вже зустрічалась "
            "сьогодні в цій групі.\n\n"
            f"📊 Попередніх появ: {previous_count}\n\n"
            "❗ Перевірте картку перед проведенням оплати."
        )

        try:

            await update.effective_message.reply_text(
                warning,
                parse_mode="Markdown"
            )

        except Exception as e:

            print(
                f"Помилка відправки антидубля: {e}"
            )


# ============================================================
# ============================================================
# /PEREPLATA
# ============================================================
# ============================================================

async def pereplata(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data["pereplata"] = {
        "step": "card"
    }

    await update.message.reply_text(
        "💳 Введіть номер картки:"
    )


# ============================================================
# ОБРОБКА PEREPLATA
# ============================================================

async def handle_pereplata(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    state = context.user_data.get(
        "pereplata"
    )

    if not state:
        return False

    text = update.message.text.strip()

    # --------------------------------------------------------
    # КРОК 1 — КАРТКА
    # --------------------------------------------------------

    if state["step"] == "card":

        card = normalize_card(text)

        if not is_valid_card(card):

            await update.message.reply_text(
                "❌ Невірний номер картки.\n\n"
                "Введіть картку ще раз."
            )

            return True

        # Отримуємо карти цієї групи
        pool = get_chat_pool(update)

        # Перевіряємо дублювання в основній базі
        for item in pool:

            saved_card = item.get(
                "card",
                ""
            )

            if cards_match(
                saved_card,
                card
            ):

                await update.message.reply_text(
                    "⚠️ Ця картка вже є в базі."
                )

                return True

        # Переходимо до опису
        context.user_data["pereplata"] = {
            "step": "description",
            "card": card
        }

        await update.message.reply_text(
            "📝 Тепер введіть опис для цієї картки:"
        )

        return True

    # --------------------------------------------------------
    # КРОК 2 — ОПИС
    # --------------------------------------------------------

    if state["step"] == "description":

        card = state["card"]

        description = text

        pool = get_chat_pool(update)

        user = update.effective_user

        if user:

            added_by = user.full_name

            if user.username:

                added_by += (
                    f" (@{user.username})"
                )

        else:

            added_by = "Невідомий користувач"

        pool.append({
            "card": card,
            "description": description,
            "added_by": added_by,
            "user_id": (
                user.id
                if user
                else None
            )
        })

        save_chat_pool(
            update,
            pool
        )

        context.user_data.pop(
            "pereplata",
            None
        )

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

async def cards_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    pool = get_chat_pool(update)

    if not pool:

        await update.message.reply_text(
            "📭 У цій групі база карт порожня."
        )

        return

    text = (
        "💳 **КАРТИ ЦІЄЇ ГРУПИ**\n\n"
    )

    for index, item in enumerate(
        pool,
        start=1
    ):

        card = item.get(
            "card",
            ""
        )

        description = item.get(
            "description",
            ""
        )

        added_by = item.get(
            "added_by",
            ""
        )

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

async def delcard_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "❌ Вкажіть номер картки.\n\n"
            "Наприклад:\n"
            "/delcard 4441111122223333"
        )

        return

    card = normalize_card(
        "".join(
            context.args
        )
    )

    if not is_valid_card(card):

        await update.message.reply_text(
            "❌ Невірний номер картки."
        )

        return

    pool = get_chat_pool(update)

    new_pool = []

    deleted = False

    for item in pool:

        saved_card = item.get(
            "card",
            ""
        )

        if cards_match(
            saved_card,
            card
        ):

            deleted = True

            continue

        new_pool.append(item)

    if deleted:

        save_chat_pool(
            update,
            new_pool
        )

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

async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data.pop(
        "pereplata",
        None
    )

    await update.message.reply_text(
        "❌ Дію скасовано."
    )


# ============================================================
# ПОШУК КАРТ У ОСНОВНІЙ БАЗІ
# ============================================================

async def check_saved_cards(
    update: Update,
    text: str
):

    cards = extract_cards(text)

    if not cards:
        return

    pool = get_chat_pool(update)

    if not pool:
        return

    for actual_card in cards:

        for item in pool:

            saved_card = item.get(
                "card",
                ""
            )

            if not cards_match(
                saved_card,
                actual_card
            ):
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
    # PEREPLATA
    # --------------------------------------------------------

    handled = await handle_pereplata(
        update,
        context
    )

    if handled:
        return

    # --------------------------------------------------------
    # Команди не перевіряємо
    # --------------------------------------------------------

    if text.startswith("/"):
        return

    # --------------------------------------------------------
    # АНТИДУБЛЬ
    #
    # Тут немає перевірки типу заявки.
    # Будь-яке повідомлення з картою перевіряється.
    # --------------------------------------------------------

    await process_duplicate_check(
        update,
        text
    )

    # --------------------------------------------------------
    # ОСНОВНА БАЗА КАРТ
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

    print(
        "🤖 Бот запускається..."
    )

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # КОМАНДИ
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
    # ЗВИЧАЙНІ ПОВІДОМЛЕННЯ
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler
        )
    )

    print(
        "✅ Бот запущений!"
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()