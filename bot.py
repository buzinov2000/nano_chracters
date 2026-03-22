import re
import time
import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import TELEGRAM_BOT_TOKEN, VARIANTS_COUNT
from session import get_session, reset_session
from agent import generate_prompt
from imagen import generate_images
from grid import make_grid

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SELECT_PATTERN = re.compile(r"^\d+(\s+\d+)*$")

# Буфер для медиагрупп: media_group_id -> {chat_id, photos: [bytes], caption}
_media_group_buffer: dict[str, dict] = {}

MEDIA_GROUP_DELAY = 1.5  # секунд — ждём пока все фото медиагруппы придут


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    reset_session(chat_id)
    await update.message.reply_text(
        "Привет! Я бот-курьер для пайплайна персонажей.\n\n"
        "Что я умею:\n"
        "• Отправь скетч с подписью-гипотезой → я сгенерирую промпт и варианты картинок\n"
        "• Можно отправить несколько фото: первое — скетч, остальные — рефы\n"
        "• Напиши номера вариантов (например: 1 3) → получишь их в полном разрешении\n"
        "• /промпт — посмотреть или отредактировать текущий промпт\n"
        "• /старт — начать заново"
    )


async def _run_full_pipeline(chat_id: int, sketch: bytes, caption: str, ref_images: list[bytes] | None, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Полный цикл: промпт → генерация → сетка."""
    session = get_session(chat_id)
    t0 = time.monotonic()

    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)

    try:
        prompt, suggestions = await generate_prompt(sketch, caption, ref_images=ref_images)
    except Exception:
        logger.exception("Ошибка генерации промпта")
        await context.bot.send_message(chat_id, "Не удалось сгенерировать промпт. Попробуйте ещё раз.")
        return

    session.current_prompt = prompt
    session.suggestions = suggestions

    await context.bot.send_message(chat_id, f"Промпт готов. Генерирую {VARIANTS_COUNT} вариантов...")
    await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)

    images = await generate_images(prompt, sketch, count=VARIANTS_COUNT)

    if not images:
        await context.bot.send_message(
            chat_id,
            "Не удалось сгенерировать картинки. Возможно, сработал фильтр безопасности — попробуйте переформулировать.",
        )
        return

    session.images = images
    grid = make_grid(images)

    elapsed = int(time.monotonic() - t0)
    await context.bot.send_photo(chat_id, photo=grid, caption=f"Сгенерировано {len(images)} вариантов за {elapsed} сек")

    suggestions_text = "\n".join(f"• {s}" for s in suggestions)
    await context.bot.send_message(
        chat_id,
        f"Отправьте номера понравившихся вариантов (например: 1 3)\n\nПодсказки:\n{suggestions_text}",
    )


async def _process_photos(chat_id: int, photos: list[bytes], caption: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка скетча (+ рефов)."""
    session = get_session(chat_id)

    session.sketch_bytes = photos[0]
    session.ref_images = photos[1:] if len(photos) > 1 else []

    if not caption:
        ref_note = f" + {len(session.ref_images)} реф(ов)" if session.ref_images else ""
        await context.bot.send_message(
            chat_id,
            f"Скетч сохранён{ref_note}. Добавьте текстовое описание гипотезы к картинке.",
        )
        return

    ref_note = f" (+ {len(session.ref_images)} рефов)" if session.ref_images else ""
    await context.bot.send_message(chat_id, f"Получил скетч{ref_note}. Генерирую промпт...")

    await _run_full_pipeline(
        chat_id, photos[0], caption,
        ref_images=session.ref_images or None,
        context=context,
    )


async def _process_media_group(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job-callback: обрабатывает собранную медиагруппу."""
    data = context.job.data
    mg_id = data["media_group_id"]

    buf = _media_group_buffer.pop(mg_id, None)
    if not buf:
        return

    await _process_photos(buf["chat_id"], buf["photos"], buf["caption"], context)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка сообщения с фото — одиночного или из медиагруппы."""
    chat_id = update.effective_chat.id

    photo = update.message.photo[-1]
    file = await photo.get_file()
    photo_bytes = bytes(await file.download_as_bytearray())

    media_group_id = update.message.media_group_id

    if media_group_id:
        if media_group_id not in _media_group_buffer:
            _media_group_buffer[media_group_id] = {
                "chat_id": chat_id,
                "photos": [],
                "caption": update.message.caption or "",
            }
            context.job_queue.run_once(
                _process_media_group,
                when=MEDIA_GROUP_DELAY,
                data={"media_group_id": media_group_id},
            )
        else:
            if update.message.caption:
                _media_group_buffer[media_group_id]["caption"] = update.message.caption

        _media_group_buffer[media_group_id]["photos"].append(photo_bytes)
    else:
        caption = update.message.caption or ""
        await _process_photos(chat_id, [photo_bytes], caption, context)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка текстовых сообщений (включая кириллические команды)."""
    text = update.message.text or ""

    if text.strip() == "/старт":
        await start(update, context)
        return

    if text.startswith("/промпт"):
        chat_id = update.effective_chat.id
        session = get_session(chat_id)

        if not session.current_prompt:
            await update.message.reply_text("Сначала отправьте скетч с гипотезой.")
            return

        edits = text[len("/промпт"):].strip()

        if not edits:
            await update.message.reply_text(f"Текущий промпт:\n\n{session.current_prompt}")
            return

        await update.message.reply_text("Обновляю промпт...")

        edit_hypothesis = (
            f"Текущий промпт: {session.current_prompt}\n"
            f"Правки от пользователя: {edits}\n"
            f"Обнови промпт соответственно."
        )
        await _run_full_pipeline(
            chat_id, session.sketch_bytes, edit_hypothesis,
            ref_images=session.ref_images or None,
            context=context,
        )
        return

    if SELECT_PATTERN.match(text.strip()):
        chat_id = update.effective_chat.id
        session = get_session(chat_id)
        if not session.images:
            await update.message.reply_text("Сначала отправьте скетч с гипотезой.")
            return

        await update.message.reply_chat_action(ChatAction.UPLOAD_DOCUMENT)

        nums = [int(n) for n in text.strip().split()]
        for n in nums:
            if 1 <= n <= len(session.images):
                await update.message.reply_document(
                    document=session.images[n - 1],
                    filename=f"variant_{n}.jpg",
                )
            else:
                await update.message.reply_text(f"Вариант {n} не найден (доступны 1–{len(session.images)})")
        return

    await update.message.reply_text(
        "Отправьте скетч с описанием гипотезы"
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальный обработчик ошибок."""
    logger.error("Необработанная ошибка: %s", context.error, exc_info=context.error)

    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                update.effective_chat.id,
                "Произошла ошибка. Попробуйте ещё раз или начните заново командой /старт",
            )
        except Exception:
            logger.exception("Не удалось отправить сообщение об ошибке")


def main() -> None:
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .read_timeout(60)
        .write_timeout(60)
        .connect_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    logger.info("Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
