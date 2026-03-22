import re
import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import TELEGRAM_BOT_TOKEN

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SELECT_PATTERN = re.compile(r"^\d+(\s+\d+)*$")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я бот-курьер для пайплайна персонажей.\n\n"
        "Что я умею:\n"
        "• Отправь скетч с подписью-гипотезой → я сгенерирую промпт и варианты картинок\n"
        "• Напиши номера вариантов (например: 1 3) → получишь их в полном разрешении\n"
        "• /промпт — посмотреть или отредактировать текущий промпт\n"
        "• /старт — начать заново"
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка сообщения с фото (+ опциональный caption)."""
    photo = update.message.photo[-1]
    file = await photo.get_file()
    photo_bytes = await file.download_as_bytearray()

    caption = update.message.caption or ""
    await update.message.reply_text(f"Получил скетч + текст: {caption}")
    await update.message.reply_photo(photo=bytes(photo_bytes))


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка текстовых сообщений (включая кириллические команды)."""
    text = update.message.text or ""

    if text.strip() == "/старт":
        await start(update, context)
        return

    if text.startswith("/промпт"):
        await update.message.reply_text("Показ/редактирование промпта (заглушка)")
        return

    if SELECT_PATTERN.match(text.strip()):
        await update.message.reply_text(f"Выбор вариантов: {text.strip()}")
        return

    await update.message.reply_text(
        "Отправьте скетч с описанием гипотезы"
    )


def main() -> None:
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
