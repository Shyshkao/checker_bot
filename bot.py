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
    """
    Завантажує всі карти з data/cards.json.
    Кожна група має свій окремий пул.
    """

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
    """
    Зберігає всі карти у файл.
    """

    with open(CARDS_FILE, "w", encoding="utf-8") as file:
        json.dump(
            cards,
            file,
            ensure_ascii=False,
            indent=4
        )


# ============================================================
# РОБОТА З ГРУПОЮ
# ============================================================

def get_chat_id(update: Update):
    """
    Повертає ID поточного чату.
    """

    chat = update.effective_chat

    if not chat:
        return None

    return str(chat.id)


def get_chat_pool(update: Update):
    """
    Повертає пул карт тільки поточної групи.
    """

    all_cards = load_cards()
    chat_id = get_chat_id(update)

    if not chat_id:
        return []

    return all_cards.get(chat_id, [])


def save_chat_pool(update: Update, pool):
    """
    Зберігає пул карт поточної групи.
    """

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
    Нормалізація звичайної карти.

    Прибирає:
    - пробіли
    - дефіси
    - зірочки

    Наприклад:

    4441 1110 2437 6760
    4441-1110-2437-6760
    4441111024376760

    ->

    4441111024376760
    """

    if not card:
        return ""

    card = card.strip()

    # Telegram Markdown
    card = card.replace("**", "")

    # Прибираємо пробіли та дефіси
    card = re.sub(r"[\s-]", "", card)

    # Зірочки прибираємо тільки для звичайної карти
    card = card.replace("*", "")

    return card


def normalize_pattern(card):
    """
    Нормалізація шаблону карти.

    Наприклад:

    4441****2608
    4441 **** 2608
    4441-****-2608

    ->

    4441****2608
    """

    if not card:
        return ""

    card = card.strip()

    # Telegram Markdown
    card = card.replace("**", "")

    # Прибираємо пробіли та дефіси
    card = re.sub(r"[\s-]", "", card)

    return card


# ============================================================
# ПЕРЕВІРКА КАРТ
# ============================================================

def is_valid_card(card):
    """
    Перевіряє звичайний номер карти.
    """

    normalized = normalize_card(card)

    if not normalized.isdigit():
        return False

    if not 13 <= len(normalized) <= 19:
        return False

    return True


def is_valid_pattern(card):
    """
    Перевіряє шаблон карти із *.

    Наприклад:

    4441****2608
    """

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
    """
    Порівнює карту з пулу з реальною картою.

    * = будь-яка цифра.

    Наприклад:

    4441****2608

    буде збігатися з:

    444112342608

    якщо довжина та інші цифри збігаються.
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
# ПОШУК КАРТ У ПОВІДОМЛЕННІ
# ============================================================

def extract_cards(text):
    """
    Витягує номери карт із повідомлення.

    Підтримує:

    4441111024376760

    4441 1110 2437 6760

    4441-1110-2437-6760
    """

    if not text:
        return []

    result = []

    # --------------------------------------------------------
    # Варіант:
    # 4441 1110 2437 6760
    # 4441-1110-2437-6760
    # --------------------------------------------------------

    pattern = r"(?<!\d)(?:\d{4}[\s-]?){3}\d{4}(?!\d)"

    matches = re.findall(pattern, text)

    for match in matches:

        card = normalize_card(match)

        if is_valid_card(card):
            result.append(card)

    # --------------------------------------------------------
    # Варіант:
    # 4441111024376760
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
# ІНФОРМАЦІЯ ПРО КОРИСТУВАЧА
# ============================================================

def get_user_name(user):
    """
    Повертає ім'я користувача.
    """

    if not user:
        return "Невідомий користувач"

    if user.full_name:
        return user.full_name

    if user.username:
        return f"@{user.username}"

    return str(user.id)


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

    # Починаємо процес додавання карти
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
# ОБРОБКА /PEREPLATA
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

    # Немає активної операції
    if not session:
        return False

    # ========================================================
    # КРОК 1 — ВВЕДЕННЯ КАРТИ
    # ========================================================

    if session["step"] == "card":

        # ----------------------------------------------------
        # ВАЖЛИВО:
        # Тут ми НЕ використовуємо extract_cards().
        #
        # Беремо весь текст, який ввів користувач,
        # і очищаємо його.
        # ----------------------------------------------------

        card = normalize_card(text)

        # Перевірка
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

        # ----------------------------------------------------
        # Перевіряємо, чи є карта в пулі цієї групи
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Переводимо процес на введення опису
        # ----------------------------------------------------

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
    # КРОК 2 — ВВЕДЕННЯ ОПИСУ
    # ========================================================

    if session["step"] == "description":

        description = text

        if not description:

            await message.reply_text(
                "❌ Опис не може бути порожнім.\n\n"
                "Введіть опис ще раз."
            )

            return True

        # Отримуємо пул поточної групи
        pool = get_chat_pool(update)

        # Створюємо нову карту
        new_card = {
            "card": session["card"],
            "description": description,
            "added_by": get_user_name(user),
            "user_id": user.id
        }

        # Додаємо карту
        pool.append(new_card)

        # Зберігаємо
        save_chat_pool(update, pool)

        # Завершуємо процес
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

    # Перевіряємо аргумент
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
# ПОШУК ЗБІГІВ У ЗВИЧАЙНИХ ПОВІДОМЛЕННЯХ
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

            if cards_match(pool_card["card"], detected_card):

                matches.append({
                    "detected": detected_card,
                    "pool": pool_card
                })

    return matches


# ============================================================
# ОБРОБКА ЗВИЧАЙНИХ ПОВІДОМЛЕНЬ
# ============================================================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    message = update.message

    text = message.text

    if not text:
        return

    # --------------------------------------------------------
    # Спочатку перевіряємо, чи людина зараз додає карту
    # --------------------------------------------------------

    if await process_pereplata(update, context):
        return

    # --------------------------------------------------------
    # Команди тут не обробляємо
    # --------------------------------------------------------

    if text.startswith("/"):
        return

    # --------------------------------------------------------
    # Шукаємо карти у звичайному повідомленні
    # --------------------------------------------------------

    matches = find_matches(update, text)

    if not matches:
        return

    # --------------------------------------------------------
    # Прибираємо дублікати
    # --------------------------------------------------------

    unique_matches = {}

    for match in matches:

        card_id = (
            match["pool"]["card"],
            match["pool"]["description"]
        )

        unique_matches[card_id] = match

    # --------------------------------------------------------
    # Формуємо відповідь
    # --------------------------------------------------------

    response = "🚨 ЗНАЙДЕНО КАРТУ З ПУЛУ\n\n"

    for match in unique_matches.values():

        pool_card = match["pool"]

        response += (
            f"💳 Карта: {pool_card['card']}\n"
            f"📝 Опис: {pool_card['description']}\n\n"
        )

    await message.reply_text(response)


# ============================================================
# ПОМИЛКИ
# ============================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):

    logger.error(
        "Помилка під час обробки update:",
        exc_info=context.error
    )


# ============================================================
# ЗАПУСК БОТА
# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN не знайдено. "
            "Перевір змінну BOT_TOKEN."
        )

    application = Application.builder().token(BOT_TOKEN).build()

    # --------------------------------------------------------
    # Команди
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler("start", start_command)
    )

    application.add_handler(
        CommandHandler("pereplata", pereplata_command)
    )

    application.add_handler(
        CommandHandler("cards", cards_command)
    )

    application.add_handler(
        CommandHandler("delcard", delcard_command)
    )

    application.add_handler(
        CommandHandler("cancel", cancel_command)
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

    # --------------------------------------------------------
    # Обробник помилок
    # --------------------------------------------------------

    application.add_error_handler(error_handler)

    # --------------------------------------------------------
    # Запуск
    # --------------------------------------------------------

    logger.info("Бот запущений.")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()