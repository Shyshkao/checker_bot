import json
import os
import re
import logging
from pathlib import Path

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

CARDS_FILE = Path("data/cards.json")
CARDS_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# ============================================================
# РОБОТА З БАЗОЮ КАРТ
# ============================================================

def load_cards():
    if not CARDS_FILE.exists():
        return {}

    try:
        with open(CARDS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

            # Якщо старий формат був списком,
            # конвертуємо його в новий формат
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
# ОТРИМАННЯ ID ПОТОЧНОЇ ГРУПИ
# ============================================================

def get_chat_id(update: Update):
    """
    Кожна група має власний ID.
    Саме він використовується як окремий пул карт.
    """

    chat = update.effective_chat

    if not chat:
        return None

    return str(chat.id)


def get_chat_pool(update: Update):
    """
    Повертає пул карт саме поточної групи.
    """

    all_cards = load_cards()
    chat_id = get_chat_id(update)

    if not chat_id:
        return []

    return all_cards.get(chat_id, [])


def save_chat_pool(update: Update, pool):
    """
    Зберігає пул тільки для поточної групи.
    """

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
    Прибирає пробіли, дефіси та зірочки Markdown.

    4149 4975 1915 1072
    ->
    4149497519151072

    4149-4975-1915-1072
    ->
    4149497519151072

    **4441 1110 6904 2608
    ->
    4441111069042608
    """

    card = card.strip()

    # Прибираємо Markdown *
    card = card.replace("*", "")

    # Прибираємо пробіли та дефіси
    card = re.sub(r"[\s-]", "", card)

    return card


# ============================================================
# НОРМАЛІЗАЦІЯ КАРТИ З МАСКОЮ
# ============================================================

def normalize_pattern(card):
    """
    Нормалізація карти, яка може містити * як маску.

    Наприклад:

    4441 **** 2608
    ->
    4441****2608
    """

    card = card.strip()

    card = re.sub(r"[\s-]", "", card)

    return card


# ============================================================
# ПЕРЕВІРКА КАРТИ
# ============================================================

def is_valid_card(card):
    """
    Перевіряє звичайну карту.

    Дозволено 13-19 цифр.
    """

    normalized = normalize_card(card)

    if not normalized.isdigit():
        return False

    if not 13 <= len(normalized) <= 19:
        return False

    return True


# ============================================================
# ПЕРЕВІРКА МАСКИ
# ============================================================

def is_valid_pattern(card):
    """
    Перевіряє карту з маскою.

    Наприклад:

    4441****2608
    """

    normalized = normalize_pattern(card)

    if not re.fullmatch(r"[\d*]+", normalized):
        return False

    digit_count = sum(c.isdigit() for c in normalized)

    if digit_count < 4:
        return False

    if len(normalized) < 13 or len(normalized) > 19:
        return False

    return True


# ============================================================
# ПОРІВНЯННЯ ДВОХ КАРТ
# ============================================================

def cards_match(pattern, actual):
    """
    Порівнює карту з пулу з реальною картою.

    * = будь-яка цифра.

    Наприклад:

    4441111024376760
    =
    4441111024376760

    4441****2437****
    =
    4441123424379876
    """

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
# ПОШУК КАРТ У ТЕКСТІ
# ============================================================

def extract_cards(text):
    """
    Витягує реальні номери карт з тексту.

    Підтримує:

    4441111024376760

    4441 1110 2437 6760

    4441-1110-2437-6760

    **4441 1110 2437 6760
    """

    if not text:
        return []

    result = []

    # --------------------------------------------------------
    # 1. Карти з пробілами або дефісами
    # --------------------------------------------------------

    pattern = r"(?<!\d)(?:\d{4}[\s-]?){3}\d{4}(?!\d)"

    matches = re.findall(pattern, text)

    for match in matches:

        card = normalize_card(match)

        if is_valid_card(card):
            result.append(card)

    # --------------------------------------------------------
    # 2. Суцільні номери карт 13-19 цифр
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
# ПОШУК ЗБІГУ В ПУЛІ
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
# ІМ'Я КОРИСТУВАЧА
# ============================================================

def get_user_name(user):

    if user.username:
        return f"@{user.username}"

    name = " ".join(
        filter(
            None,
            [
                user.first_name,
                user.last_name
            ]
        )
    )

    if name:
        return name

    return str(user.id)


# ============================================================
# /START
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = (
        "🤖 Бот перевірки карт з переплат\n\n"
        "Доступні команди:\n\n"
        "/pereplata — додати карту в пул\n"
        "/cards — переглянути пул цієї групи\n"
        "/delcard — видалити карту\n"
        "/cancel — скасувати поточну дію\n\n"
    )

    await update.message.reply_text(text)


# ============================================================
# /PEREPLATA
# ============================================================

async def pereplata_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    # Працюємо тільки в групах
    if update.effective_chat.type not in [
        "group",
        "supergroup"
    ]:

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
# /CARDS
# ============================================================

async def cards_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_chat.type not in [
        "group",
        "supergroup"
    ]:

        await update.message.reply_text(
            "❌ Цю команду потрібно використовувати "
            "в Telegram-групі."
        )

        return

    cards = get_chat_pool(update)

    if not cards:

        await update.message.reply_text(
            "📋 Пул карт цієї групи порожній."
        )

        return

    text = "📋 ПУЛ КАРТ ЦІЄЇ ГРУПИ\n\n"

    for index, card in enumerate(
        cards,
        start=1
    ):

        text += (
            f"{index}. 💳 {card['card']}\n"
            f"   📝 {card['description']}\n"
            f"   👤 Додав: {card.get('added_by', 'Невідомо')}\n\n"
        )

    text += f"Всього карт: {len(cards)}"

    await update.message.reply_text(text)


# ============================================================
# /DELCARD
# ============================================================

async def delcard_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_chat.type not in [
        "group",
        "supergroup"
    ]:

        await update.message.reply_text(
            "❌ Цю команду потрібно використовувати "
            "в Telegram-групі."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "❌ Вкажіть карту.\n\n"
            "Приклад:\n"
            "/delcard 4441111024376760"
        )

        return

    card = normalize_card(
        " ".join(context.args)
    )

    cards = get_chat_pool(update)

    found = None

    for item in cards:

        if normalize_card(
            item["card"]
        ) == card:

            found = item
            break

    if not found:

        await update.message.reply_text(
            "❌ Такої карти немає у пулі цієї групи."
        )

        return

    cards.remove(found)

    save_chat_pool(
        update,
        cards
    )

    await update.message.reply_text(
        "🗑️ КАРТУ ВИДАЛЕНО\n\n"
        f"💳 {found['card']}\n"
        f"📝 {found['description']}"
    )


# ============================================================
# ДОДАВАННЯ КАРТИ
# ============================================================

async def process_pereplata(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message
    user = update.effective_user

    text = message.text.strip()

    session = context.user_data.get(
        "pereplata"
    )

    if not session:
        return False

    # ========================================================
    # КРОК 1 — КАРТА
    # ========================================================

    if session["step"] == "card":

        cards = extract_cards(text)

        if len(cards) == 0:

            await message.reply_text(
                "❌ Не вдалося розпізнати карту.\n\n"
                "Введіть номер ще раз.\n\n"
                "Наприклад:\n"
                "4441111024376760"
            )

            return True

        if len(cards) > 1:

            await message.reply_text(
                "❌ Я знайшов декілька карт.\n\n"
                "Введіть тільки одну карту."
            )

            return True

        card = cards[0]

        # ----------------------------------------------------
        # Перевіряємо, чи карта вже є У ЦІЙ ГРУПІ
        # ----------------------------------------------------

        pool = get_chat_pool(update)

        for item in pool:

            if cards_match(
                item["card"],
                card
            ):

                await message.reply_text(
                    "⚠️ Така карта вже є у пулі цієї групи.\n\n"
                    f"💳 {item['card']}\n"
                    f"📝 {item['description']}"
                )

                context.user_data.pop(
                    "pereplata",
                    None
                )

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

        cards = get_chat_pool(update)

        new_card = {
            "card": session["card"],
            "description": description,
            "added_by": get_user_name(user),
            "user_id": user.id
        }

        cards.append(new_card)

        save_chat_pool(
            update,
            cards
        )

        context.user_data.pop(
            "pereplata",
            None
        )

        await message.reply_text(
            "✅ КАРТУ ДОДАНО ДО ПУЛУ ЦІЄЇ ГРУПИ\n\n"
            f"💳 {new_card['card']}\n"
            f"📝 {new_card['description']}\n"
            f"👤 Додав: {new_card['added_by']}"
        )

        return True

    return False


# ============================================================
# ОБРОБКА ЗВИЧАЙНИХ ПОВІДОМЛЕНЬ
# ============================================================

async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    message = update.message

    text = message.text

    if not text:
        return

    # ========================================================
    # СПОЧАТКУ ПЕРЕВІРЯЄМО ДОДАВАННЯ КАРТИ
    # ========================================================

    if await process_pereplata(
        update,
        context
    ):
        return

    # ========================================================
    # КОМАНДИ НЕ ПЕРЕВІРЯЄМО
    # ========================================================

    if text.startswith("/"):
        return

    # ========================================================
    # ШУКАЄМО КАРТИ
    # ========================================================

    matches = find_matches(
        update,
        text
    )

    if not matches:
        return

    # ========================================================
    # ПРИБИРАЄМО ДУБЛІКАТИ
    # ========================================================

    unique_matches = {}

    for match in matches:

        card_id = (
            match["pool"]["card"],
            match["pool"]["description"]
        )

        unique_matches[card_id] = match

    # ========================================================
    # ФОРМУЄМО ПОВІДОМЛЕННЯ
    # ========================================================

    response = (
        "🚨 ЗНАЙДЕНО КАРТУ З ПУЛУ\n\n"
    )

    for match in unique_matches.values():

        pool_card = match["pool"]

        response += (
            f"💳 Карта: {pool_card['card']}\n"
            f"📝 Опис: {pool_card['description']}\n\n"
        )

    # ========================================================
    # ВІДПОВІДАЄМО НА ПОВІДОМЛЕННЯ
    # ========================================================

    await message.reply_text(
        response
    )


# ============================================================
# ЗАПУСК БОТА
# ============================================================

def main():

    if not BOT_TOKEN:

        print(
            "❌ BOT_TOKEN не знайдено!"
        )

        print(
            "Перевір файл .env"
        )

        return

    print(
        "🤖 Запуск бота..."
    )

    application = (
        Application.builder()
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
    # Звичайні текстові повідомлення
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


if __name__ == "__main__":
    main()