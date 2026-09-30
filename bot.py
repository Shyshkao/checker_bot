import json
import os
import re
import logging
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
# НАЛАШТУВАННЯ
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

DATA_FOLDER = Path("data")
DATA_FOLDER.mkdir(parents=True, exist_ok=True)

CARDS_FILE = DATA_FOLDER / "cards.json"
REQUESTS_FILE = DATA_FOLDER / "requests.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# ============================================================
# ЗАГАЛЬНІ ФУНКЦІЇ
# ============================================================

def get_today():
    """
    Поточна дата у форматі YYYY-MM-DD.
    """

    return datetime.now().strftime("%Y-%m-%d")


def get_now():
    """
    Поточні дата та час.
    """

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_user_name(user):
    """
    Ім'я користувача Telegram.
    """

    if not user:
        return "Невідомий користувач"

    if user.full_name:
        return user.full_name

    if user.username:
        return f"@{user.username}"

    return str(user.id)


# ============================================================
# РОБОТА З CARDS
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

    with open(CARDS_FILE, "w", encoding="utf-8") as file:

        json.dump(
            cards,
            file,
            ensure_ascii=False,
            indent=4
        )


# ============================================================
# РОБОТА З REQUESTS
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

    with open(REQUESTS_FILE, "w", encoding="utf-8") as file:

        json.dump(
            requests,
            file,
            ensure_ascii=False,
            indent=4
        )


# ============================================================
# РОБОТА З ГРУПОЮ
# ============================================================

def get_chat_id(update: Update):

    chat = update.effective_chat

    if not chat:
        return None

    return str(chat.id)


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

    if not card:
        return ""

    card = card.strip()

    # Прибираємо Telegram Markdown
    card = card.replace("**", "")

    # Прибираємо пробіли та дефіси
    card = re.sub(r"[\s-]", "", card)

    # Для звичайної карти прибираємо *
    card = card.replace("*", "")

    return card


def normalize_pattern(card):

    if not card:
        return ""

    card = card.strip()

    card = card.replace("**", "")

    card = re.sub(r"[\s-]", "", card)

    return card


# ============================================================
# ПЕРЕВІРКА КАРТ
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
# ВИТЯГУВАННЯ КАРТ
# ============================================================

def extract_cards(text):

    if not text:
        return []

    result = []

    # --------------------------------------------------------
    # Картка з пробілами або дефісами
    #
    # 4441 1111 3792 6279
    # 4441-1111-3792-6279
    # --------------------------------------------------------

    pattern = r"(?<!\d)(?:\d{4}[\s-]?){3}\d{4}(?!\d)"

    matches = re.findall(pattern, text)

    for match in matches:

        card = normalize_card(match)

        if is_valid_card(card):

            result.append(card)

    # --------------------------------------------------------
    # Суцільний номер
    #
    # 4441111137926279
    # --------------------------------------------------------

    pattern = r"(?<!\d)\d{13,19}(?!\d)"

    matches = re.findall(pattern, text)

    for match in matches:

        card = normalize_card(match)

        if is_valid_card(card):

            result.append(card)

    # --------------------------------------------------------
    # Прибираємо дублікати
    # --------------------------------------------------------

    return list(dict.fromkeys(result))


# ============================================================
# ВИЗНАЧЕННЯ, ЧИ СХОЖЕ ПОВІДОМЛЕННЯ НА ЗАЯВКУ
# ============================================================

def looks_like_request(text):

    if not text:
        return False

    text_lower = text.lower()

    # --------------------------------------------------------
    # Формат 1
    # --------------------------------------------------------

    request_markers = [
        "курс:",
        "комісія:",
        "комиссия:",
        "екв. usdt:",
        "экв. usdt:",
        "сума переказу:",
        "сумма перевода:",
        "реквізити:",
        "реквизиты:",
        "власник карти:",
        "владелец карты:",
        "номер картки",
        "номер карты",
        "курс виплати",
        "время взятия в обработку",
        "в обработке",
    ]

    marker_count = 0

    for marker in request_markers:

        if marker in text_lower:

            marker_count += 1

    # Якщо є хоча б один характерний маркер
    if marker_count >= 1:
        return True

    # --------------------------------------------------------
    # Формат з USDT
    # --------------------------------------------------------

    if re.search(r"\d+(?:[.,]\d+)?\s*usdt", text_lower):

        if extract_cards(text):
            return True

    # --------------------------------------------------------
    # Якщо є дата + карта
    # --------------------------------------------------------

    if re.search(
        r"\b\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\b",
        text_lower
    ):

        if extract_cards(text):
            return True

    # --------------------------------------------------------
    # Якщо є "Card" + номер карти
    # --------------------------------------------------------

    if re.search(r"\bcard\b", text_lower):

        if extract_cards(text):
            return True

    return False


# ============================================================
# ПОШУК ЗАДВОЄННЯ
# ============================================================

def check_duplicate_request(update: Update, card):

    requests = load_requests()

    chat_id = get_chat_id(update)

    if not chat_id:
        return False, 0

    today = get_today()

    # Структура:
    #
    # {
    #     "chat_id": {
    #         "2026-09-30": {
    #             "card": 2
    #         }
    #     }
    # }

    if chat_id not in requests:
        requests[chat_id] = {}

    if today not in requests[chat_id]:
        requests[chat_id][today] = {}

    today_cards = requests[chat_id][today]

    previous_count = today_cards.get(card, 0)

    today_cards[card] = previous_count + 1

    save_requests(requests)

    return previous_count > 0, previous_count


# ============================================================
# ОЧИЩЕННЯ СТАРИХ ЗАПИСІВ
# ============================================================

def cleanup_old_requests():

    requests = load_requests()

    today = get_today()

    changed = False

    for chat_id in list(requests.keys()):

        dates = requests[chat_id]

        for date in list(dates.keys()):

            # Залишаємо тільки сьогоднішній день
            if date != today:

                del dates[date]

                changed = True

        if not dates:

            del requests[chat_id]

            changed = True

    if changed:

        save_requests(requests)


# ============================================================
# /START
# ============================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🤖 Бот працює.\n\n"
        "Доступні команди:\n\n"
        "/pereplata — додати карту до пулу\n"
        "/cards — показати карти групи\n"
        "/delcard <карта> — видалити карту\n"
        "/cancel — скасувати поточну дію"
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
# /PEREPLATA
# ============================================================

async def pereplata_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_chat.type not in ["group", "supergroup"]:

        await update.message.reply_text(
            "❌ Цю команду потрібно використовувати "
            "в Telegram-групі."
        )

        return

    context.user_data["pereplata"] = {
        "step": "card"
    }

    await update.message.reply_text(
        "💳 Введіть номер карти.\n\n"
        "Приклад:\n"
        "4441111024376760\n\n"
        "Також можна:\n"
        "4441 1110 2437 6760\n"
        "4441-1110-2437-6760\n\n"
        "Для скасування напишіть /cancel"
    )


# ============================================================
# ОБРОБКА PEREPLATA
# ============================================================

async def process_pereplata(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.message

    if not message:
        return False

    user = update.effective_user

    text = message.text

    if not text:
        return False

    text = text.strip()

    session = context.user_data.get("pereplata")

    if not session:
        return False

    # ========================================================
    # КРОК 1 — КАРТА
    # ========================================================

    if session["step"] == "card":

        card = normalize_card(text)

        if not card.isdigit() or not 13 <= len(card) <= 19:

            await message.reply_text(
                "❌ Не вдалося розпізнати карту.\n\n"
                "Введіть номер ще раз.\n\n"
                "Наприклад:\n"
                "4441111024376760\n\n"
                "Також можна:\n"
                "4441 1110 2437 6760\n"
                "4441-1110-2437-6760"
            )

            return True

        pool = get_chat_pool(update)

        for item in pool:

            if cards_match(item["card"], card):

                await message.reply_text(
                    "⚠️ Така карта вже є у пулі цієї групи.\n\n"
                    f"💳 {item['card']}\n"
                    f"📝 {item['description']}"
                )

                context.user_data.pop("pereplata", None)

                return True

        context.user_data["pereplata"] = {
            "step": "description",
            "card": card
        }

        await message.reply_text(
            f"💳 Карту отримано:\n"
            f"{card}\n\n"
            "📝 Тепер введіть опис карти.\n\n"
            "Приклад:\n"
            "Заказ 7893747 перплата Андрій 789грн\n\n"
            "Для скасування напишіть /cancel"
        )

        return True

    # ========================================================
    # КРОК 2 — ОПИС
    # ========================================================

    if session["step"] == "description":

        description = text

        if not description:

            await message.reply_text(
                "❌ Опис не може бути порожнім."
            )

            return True

        pool = get_chat_pool(update)

        new_card = {
            "card": session["card"],
            "description": description,
            "added_by": get_user_name(user),
            "user_id": user.id
        }

        pool.append(new_card)

        save_chat_pool(update, pool)

        context.user_data.pop("pereplata", None)

        await message.reply_text(
            "✅ КАРТУ ДОДАНО ДО ПУЛУ ЦІЄЇ ГРУПИ\n\n"
            f"💳 {new_card['card']}\n"
            f"📝 {new_card['description']}\n"
            f"👤 Додав: {new_card['added_by']}"
        )

        return True

    return False


# ============================================================
# /CARDS
# ============================================================

async def cards_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_chat.type not in ["group", "supergroup"]:

        await update.message.reply_text(
            "❌ Цю команду потрібно використовувати "
            "в Telegram-групі."
        )

        return

    pool = get_chat_pool(update)

    if not pool:

        await update.message.reply_text(
            "📭 У пулі цієї групи поки немає карт."
        )

        return

    response = "💳 КАРТИ ЦІЄЇ ГРУПИ\n\n"

    for index, item in enumerate(pool, start=1):

        response += (
            f"{index}. 💳 {item['card']}\n"
            f"📝 {item['description']}\n"
            f"👤 {item.get('added_by', 'Невідомо')}\n\n"
        )

    await update.message.reply_text(response)


# ============================================================
# /DELCARD
# ============================================================

async def delcard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_chat.type not in ["group", "supergroup"]:

        await update.message.reply_text(
            "❌ Цю команду потрібно використовувати "
            "в Telegram-групі."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "❌ Вкажіть карту для видалення.\n\n"
            "Приклад:\n"
            "/delcard 4441111024376760"
        )

        return

    card_to_delete = normalize_card(" ".join(context.args))

    if not card_to_delete:

        await update.message.reply_text(
            "❌ Некоректний номер карти."
        )

        return

    pool = get_chat_pool(update)

    if not pool:

        await update.message.reply_text(
            "📭 У пулі цієї групи немає карт."
        )

        return

    deleted = None

    for item in pool:

        if cards_match(item["card"], card_to_delete):

            deleted = item

            break

    if not deleted:

        await update.message.reply_text(
            "❌ Такої карти немає у пулі цієї групи."
        )

        return

    pool.remove(deleted)

    save_chat_pool(update, pool)

    await update.message.reply_text(
        "🗑 КАРТУ ВИДАЛЕНО\n\n"
        f"💳 {deleted['card']}\n"
        f"📝 {deleted['description']}"
    )


# ============================================================
# ОБРОБКА ЗАЯВОК
# ============================================================

async def process_request(update: Update, text):

    # --------------------------------------------------------
    # Спочатку перевіряємо, чи це схоже на заявку
    # --------------------------------------------------------

    if not looks_like_request(text):

        return False

    # --------------------------------------------------------
    # Витягуємо карти
    # --------------------------------------------------------

    detected_cards = extract_cards(text)

    if not detected_cards:

        return False

    # --------------------------------------------------------
    # Якщо в повідомленні декілька карт,
    # перевіряємо кожну
    # --------------------------------------------------------

    duplicate_cards = []

    for card in detected_cards:

        is_duplicate, previous_count = check_duplicate_request(
            update,
            card
        )

        if is_duplicate:

            duplicate_cards.append(
                (card, previous_count)
            )

    # --------------------------------------------------------
    # Якщо дубліката немає — нічого не пишемо
    # --------------------------------------------------------

    if not duplicate_cards:

        logger.info(
            f"Нова заявка: "
            f"chat={get_chat_id(update)}, "
            f"cards={detected_cards}"
        )

        return False

    # --------------------------------------------------------
    # Формуємо попередження
    # --------------------------------------------------------

    response = (
        "🚨 **УВАГА — МОЖЛИВЕ ЗАДВОЄННЯ ЗАЯВКИ!**\n\n"
    )

    for card, previous_count in duplicate_cards:

        response += (
            f"💳 Карта: `{card}`\n"
            f"⚠️ Ця карта вже була в заявці сьогодні.\n"
            f"Попередніх заявок сьогодні: {previous_count}\n\n"
        )

    response += (
        "❗ Перевірте, будь ласка, чи не задвоїли заявку "
        "перед проведенням оплати."
    )

    # --------------------------------------------------------
    # Відповідаємо саме на заявку
    # --------------------------------------------------------

    try:

        await update.message.reply_text(
            response,
            parse_mode="Markdown"
        )

    except Exception as error:

        logger.error(
            f"Помилка відповіді на заявку: {error}"
        )

        # Запасний варіант без Markdown
        await update.message.reply_text(
            response.replace("**", "").replace("`", "")
        )

    return True


# ============================================================
# ПОШУК КАРТ З ПУЛУ
# ============================================================

def find_matches(update: Update, text):

    detected_cards = extract_cards(text)

    if not detected_cards:

        return []

    pool = get_chat_pool(update)

    if not pool:

        return []

    matches = []

    for detected_card in detected_cards:

        for pool_card in pool:

            if cards_match(
                pool_card["card"],
                detected_card
            ):

                matches.append({
                    "detected": detected_card,
                    "pool": pool_card
                })

    return matches


# ============================================================
# ОБРОБКА ЗВИЧАЙНИХ ПОВІДОМЛЕНЬ
# ============================================================

async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:

        return

    text = update.message.text

    if not text:

        return

    logger.info(
        f"📩 MESSAGE: "
        f"chat={get_chat_id(update)}, "
        f"text={text[:200]}"
    )

    # --------------------------------------------------------
    # Якщо користувач зараз проходить /pereplata
    # --------------------------------------------------------

    if await process_pereplata(update, context):

        return

    # --------------------------------------------------------
    # Команди тут не обробляємо
    # --------------------------------------------------------

    if text.startswith("/"):

        return

    # --------------------------------------------------------
    # 1. Перевіряємо заявку на дубль
    # --------------------------------------------------------

    await process_request(
        update,
        text
    )

    # --------------------------------------------------------
    # 2. Перевіряємо карту по пулу /pereplata
    # --------------------------------------------------------

    matches = find_matches(
        update,
        text
    )

    if not matches:

        return

    unique_matches = {}

    for match in matches:

        card_id = (
            match["pool"]["card"],
            match["pool"]["description"]
        )

        unique_matches[card_id] = match

    response = "🚨 ЗНАЙДЕНО КАРТУ З ПУЛУ\n\n"

    for match in unique_matches.values():

        pool_card = match["pool"]

        response += (
            f"💳 Карта: {pool_card['card']}\n"
            f"📝 Опис: {pool_card['description']}\n\n"
        )

    await update.message.reply_text(
        response
    )


# ============================================================
# ПОМИЛКИ
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Помилка під час обробки update:",
        exc_info=context.error
    )


# ============================================================
# ЗАПУСК
# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN не знайдено. "
            "Перевір змінну BOT_TOKEN."
        )

    # При запуску очищаємо стару історію
    # і залишаємо тільки сьогоднішню
    cleanup_old_requests()

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # Команди
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    application.add_handler(
        CommandHandler(
            "pereplata",
            pereplata_command
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

    # --------------------------------------------------------
    # Помилки
    # --------------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "🤖 БОТ ЗАПУЩЕНИЙ"
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()