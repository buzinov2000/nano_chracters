import re
import time
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import TELEGRAM_BOT_TOKEN, IMAGE_MODELS
from session import get_session, reset_session
from agent import generate_prompt
from imagen import generate_images, GenerationError
from grid import make_grid

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SELECT_PATTERN = re.compile(r"^\d+(\s+\d+)*$")

_media_group_buffer: dict[str, dict] = {}
MEDIA_GROUP_DELAY = 1.5

ERROR_MESSAGES = {
    "safety_filter": "Генерация заблокирована фильтрами безопасности. Попробуйте переформулировать гипотезу.",
    "overloaded": "Модель перегружена запросами. Попробуйте через пару минут или переключите модель через /model.",
    "timeout": "Сервер не ответил вовремя. Попробуйте ещё раз или переключите модель через /model.",
}

BOT_COMMANDS = [
    BotCommand("start", "Начать заново"),
    BotCommand("prompt", "Показать / редактировать промпт"),
    BotCommand("model", "Переключить модель генерации"),
    BotCommand("more", "Сгенерировать ещё 2 варианта"),
]


async def post_init(application) -> None:
    await application.bot.set_my_commands(BOT_COMMANDS)
    logger.info("Команды бота зарегистрированы в меню")


def _error_message(e: GenerationError) -> str:
    return ERROR_MESSAGES.get(str(e), "Не удалось сгенерировать. Попробуйте ещё раз.")


# ---------- /start, /старт ----------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    reset_session(chat_id)
    session = get_session(chat_id)
    mode_info = IMAGE_MODELS[session.image_mode]

    await update.message.reply_text(
        "Привет! Я бот-курьер для пайплайна персонажей.\n\n"
        "Что я умею:\n"
        "• Отправь скетч с подписью-гипотезой → сгенерирую промпт и варианты\n"
        "• Можно отправить несколько фото: первое — скетч, остальные — рефы\n"
        "• Напиши номера вариантов (например: 1 3) → получишь в полном разрешении\n\n"
        "Команды:\n"
        "/prompt — показать / редактировать промпт\n"
        "/model — переключить модель генерации\n"
        "/more — сгенерировать ещё 2 варианта\n"
        "/start — начать заново\n\n"
        f"Текущая модель: {mode_info['label']} ({mode_info['count']} шт)"
    )


# ---------- /model ----------

def _model_keyboard(current_mode: str) -> InlineKeyboardMarkup:
    buttons = []
    for key, info in IMAGE_MODELS.items():
        marker = " ✓" if key == current_mode else ""
        buttons.append([InlineKeyboardButton(
            f"{info['label']} ({info['count']} шт){marker}",
            callback_data=f"model:{key}",
        )])
    return InlineKeyboardMarkup(buttons)


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    await update.message.reply_text(
        "Выберите модель генерации:",
        reply_markup=_model_keyboard(session.image_mode),
    )


async def callback_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    mode = query.data.split(":", 1)[1]
    if mode not in IMAGE_MODELS:
        return

    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    session.image_mode = mode
    info = IMAGE_MODELS[mode]

    await query.edit_message_text(
        f"Модель переключена: {info['label']} ({info['count']} шт)",
    )


# ---------- /more ----------

async def cmd_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if not session.current_prompt:
        await update.message.reply_text("Сначала отправьте скетч с гипотезой.")
        return

    await _generate_more(chat_id, session, context)


async def callback_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if not session.current_prompt:
        await query.edit_message_text("Сессия устарела. Отправьте скетч заново.")
        return

    await _generate_more(chat_id, session, context)


async def _generate_more(chat_id: int, session, context: ContextTypes.DEFAULT_TYPE) -> None:
    info = IMAGE_MODELS[session.image_mode]

    await context.bot.send_message(chat_id, "Генерирую ещё 2 варианта...")
    await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)

    t0 = time.monotonic()

    try:
        new_images = await generate_images(
            session.current_prompt,
            session.sketch_bytes,
            count=2,
            model=info["model"],
        )
    except GenerationError as e:
        await context.bot.send_message(chat_id, _error_message(e))
        return

    if not new_images:
        await context.bot.send_message(chat_id, "Не удалось сгенерировать. Попробуйте ещё раз.")
        return

    session.images.extend(new_images)
    grid = make_grid(session.images)
    elapsed = int(time.monotonic() - t0)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Ещё 2 варианта", callback_data="more")],
    ])

    await context.bot.send_photo(
        chat_id,
        photo=grid,
        caption=f"Добавлено {len(new_images)} вариантов (всего {len(session.images)}) за {elapsed} сек",
        reply_markup=keyboard,
    )


# ---------- /prompt, /промпт ----------

async def cmd_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if not session.current_prompt:
        await update.message.reply_text("Сначала отправьте скетч с гипотезой.")
        return

    edits = " ".join(context.args) if context.args else ""

    if not edits:
        # Показать промпт + кнопка «Редактировать»
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Редактировать", callback_data="edit_prompt")],
        ])
        await update.message.reply_text(
            f"Текущий промпт:\n\n{session.current_prompt}",
            reply_markup=keyboard,
        )
        return

    # Есть правки — сразу перегенерируем
    await _edit_prompt(chat_id, session, edits, context)


async def callback_edit_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if not session.current_prompt:
        await query.edit_message_text("Сессия устарела. Отправьте скетч заново.")
        return

    session.awaiting_prompt_edit = True
    await query.edit_message_text(
        f"Текущий промпт:\n\n{session.current_prompt}\n\n"
        "Напишите правки следующим сообщением:"
    )


async def _edit_prompt(chat_id: int, session, edits: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(chat_id, "Обновляю промпт...")

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


# ---------- Полный пайплайн ----------

async def _run_full_pipeline(chat_id: int, sketch: bytes, caption: str, ref_images: list[bytes] | None, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = get_session(chat_id)
    info = IMAGE_MODELS[session.image_mode]
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

    await context.bot.send_message(
        chat_id,
        f"Промпт готов. Генерирую {info['count']} вариантов ({info['label']})...",
    )
    await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)

    try:
        images = await generate_images(prompt, sketch, count=info["count"], model=info["model"])
    except GenerationError as e:
        await context.bot.send_message(chat_id, _error_message(e))
        return

    if not images:
        await context.bot.send_message(chat_id, "Не удалось сгенерировать картинки. Попробуйте ещё раз.")
        return

    session.images = images
    grid = make_grid(images)
    elapsed = int(time.monotonic() - t0)

    # Кнопка «ещё 2» для моделей с count <= 2
    keyboard = None
    if info["count"] <= 2:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Ещё 2 варианта", callback_data="more")],
        ])

    await context.bot.send_photo(
        chat_id,
        photo=grid,
        caption=f"Сгенерировано {len(images)} вариантов за {elapsed} сек ({info['label']})",
        reply_markup=keyboard,
    )

    suggestions_text = "\n".join(f"• {s}" for s in suggestions)
    await context.bot.send_message(
        chat_id,
        f"Отправьте номера понравившихся вариантов (например: 1 3)\n\nПодсказки:\n{suggestions_text}",
    )


# ---------- Фото ----------

async def _process_photos(chat_id: int, photos: list[bytes], caption: str, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    data = context.job.data
    mg_id = data["media_group_id"]

    buf = _media_group_buffer.pop(mg_id, None)
    if not buf:
        return

    await _process_photos(buf["chat_id"], buf["photos"], buf["caption"], context)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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


# ---------- Текст ----------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    # Если ждём правки промпта
    if session.awaiting_prompt_edit:
        session.awaiting_prompt_edit = False
        if session.current_prompt:
            await _edit_prompt(chat_id, session, text, context)
            return

    # Кириллические алиасы
    if text.strip() == "/старт":
        await cmd_start(update, context)
        return

    if text.startswith("/промпт"):
        if not session.current_prompt:
            await update.message.reply_text("Сначала отправьте скетч с гипотезой.")
            return

        edits = text[len("/промпт"):].strip()

        if not edits:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Редактировать", callback_data="edit_prompt")],
            ])
            await update.message.reply_text(
                f"Текущий промпт:\n\n{session.current_prompt}",
                reply_markup=keyboard,
            )
            return

        await _edit_prompt(chat_id, session, edits, context)
        return

    # Выбор вариантов по номерам
    if SELECT_PATTERN.match(text.strip()):
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


# ---------- Ошибки ----------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Необработанная ошибка: %s", context.error, exc_info=context.error)

    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                update.effective_chat.id,
                "Произошла ошибка. Попробуйте ещё раз или начните заново командой /start",
            )
        except Exception:
            logger.exception("Не удалось отправить сообщение об ошибке")


# ---------- main ----------

def main() -> None:
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .read_timeout(60)
        .write_timeout(60)
        .connect_timeout(30)
        .post_init(post_init)
        .build()
    )

    # Латинские команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("prompt", cmd_prompt))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("more", cmd_more))

    # Inline-кнопки
    app.add_handler(CallbackQueryHandler(callback_model, pattern=r"^model:"))
    app.add_handler(CallbackQueryHandler(callback_more, pattern=r"^more$"))
    app.add_handler(CallbackQueryHandler(callback_edit_prompt, pattern=r"^edit_prompt$"))

    # Фото и текст
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.add_error_handler(error_handler)

    logger.info("Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
