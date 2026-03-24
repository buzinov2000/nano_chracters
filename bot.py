import asyncio
import re
import time
import logging
from functools import wraps

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

from config import TELEGRAM_BOT_TOKEN, IMAGE_MODELS, ALLOWED_USERS, DAILY_LIMIT_PER_USER
from session import get_session, reset_session, save_default_model
from agent import generate_prompt
from imagen import generate_images, GenerationError
from grid import make_grid

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_media_group_buffer: dict[str, dict] = {}
MEDIA_GROUP_DELAY = 1.5
_STATUS_DOTS_INTERVAL = 1.5  # секунд между обновлениями точек


class StatusMessage:
    """Одно статус-сообщение, которое редактируется in-place (BOT_TOV)."""

    _PHASES = ["🎨 генерирую", "🎨 генерирую ·", "🎨 генерирую · ·", "🎨 генерирую · · ·"]

    def __init__(self, bot, chat_id: int):
        self._bot = bot
        self._chat_id = chat_id
        self._message = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._message = await self._bot.send_message(self._chat_id, self._PHASES[0])
        self._task = asyncio.create_task(self._animate())

    async def _animate(self) -> None:
        idx = 1
        try:
            while True:
                await asyncio.sleep(_STATUS_DOTS_INTERVAL)
                text = self._PHASES[idx % len(self._PHASES)]
                try:
                    await self._message.edit_text(text)
                except Exception:
                    pass
                idx += 1
        except asyncio.CancelledError:
            pass

    async def done(self) -> None:
        """Останавливает анимацию и удаляет статус-сообщение."""
        if self._task:
            self._task.cancel()
        if self._message:
            try:
                await self._message.delete()
            except Exception:
                pass

    async def fail(self, text: str) -> None:
        """Останавливает анимацию и показывает ошибку."""
        if self._task:
            self._task.cancel()
        if self._message:
            try:
                await self._message.edit_text(text, parse_mode="Markdown")
            except Exception:
                pass

ERROR_MESSAGES = {
    "safety_filter": "`фильтр: текст — переформулируй`",
    "overloaded": "`сервер перегружен — попробуй позже`",
    "timeout": "`сервер не ответил — ещё раз?`",
}

BOT_COMMANDS = [
    BotCommand("start", "Начать заново"),
    BotCommand("prompt", "Показать текущий промпт"),
    BotCommand("prompt_edit", "Редактировать промпт"),
    BotCommand("model", "Переключить модель генерации"),
    BotCommand("more", "Сгенерировать ещё 2 варианта"),
]


async def post_init(application) -> None:
    await application.bot.set_my_commands(BOT_COMMANDS)
    logger.info("Команды бота зарегистрированы в меню")


def _error_message(e: GenerationError) -> str:
    return ERROR_MESSAGES.get(str(e), "`генерация не удалась — ещё раз?`")


def authorized(func):
    """Проверка доступа по whitelist. Если ALLOWED_USERS пуст — пропускает всех."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if ALLOWED_USERS and (not user or user.id not in ALLOWED_USERS):
            if update.message:
                await update.message.reply_text("⛔ Доступ ограничен.")
            elif update.callback_query:
                await update.callback_query.answer("⛔ Доступ ограничен.", show_alert=True)
            return
        return await func(update, context)
    return wrapper


def _pick_keyboard(count: int, extra_buttons: list | None = None, suggestions: list[str] | None = None) -> InlineKeyboardMarkup:
    """Inline-кнопки с номерами вариантов + опциональные доп. кнопки + подсказки."""
    number_row = [InlineKeyboardButton(str(i + 1), callback_data=f"pick:{i + 1}") for i in range(count)]
    rows = [number_row]
    if extra_buttons:
        rows.append(extra_buttons)
    if suggestions:
        for i, s in enumerate(suggestions[:3]):
            rows.append([InlineKeyboardButton(s, callback_data=f"suggest:{i}")])
    return InlineKeyboardMarkup(rows)


# ---------- /start, /старт ----------

@authorized
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    reset_session(user_id)
    session = get_session(user_id)
    mode_info = IMAGE_MODELS[session.image_mode]

    await update.message.reply_text("🌱 новый проект")


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


@authorized
async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    session = get_session(user_id)

    await update.message.reply_text(
        "Выберите модель генерации:",
        reply_markup=_model_keyboard(session.image_mode),
    )


@authorized
async def callback_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    mode = query.data.split(":", 1)[1]
    if mode not in IMAGE_MODELS:
        return

    user_id = update.effective_user.id
    session = get_session(user_id)
    session.image_mode = mode
    await save_default_model(mode)
    info = IMAGE_MODELS[mode]

    await query.edit_message_text(
        f"Модель переключена: {info['label']} ({info['count']} шт) — установлена по умолчанию",
    )


# ---------- /more ----------

@authorized
async def cmd_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    session = get_session(user_id)

    if not session.current_prompt:
        await update.message.reply_text("`сессия пуста — отправь скетч`", parse_mode="Markdown")
        return

    await _generate_more(chat_id, user_id, session, context)


@authorized
async def callback_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    session = get_session(user_id)

    if not session.current_prompt:
        await query.edit_message_text("`сессия пуста — отправь скетч`", parse_mode="Markdown")
        return

    await _generate_more(chat_id, user_id, session, context)


async def _generate_more(chat_id: int, user_id: int, session, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Проверка дневного лимита
    if not session.check_daily_limit(DAILY_LIMIT_PER_USER):
        await context.bot.send_message(
            chat_id,
            "`лимит исчерпан — сброс в полночь`", parse_mode="Markdown",
        )
        return

    # Lock на сессию
    if session.lock.locked():
        await context.bot.send_message(chat_id, "`генерация идёт — подожди`", parse_mode="Markdown")
        return

    async with session.lock:
        info = IMAGE_MODELS[session.image_mode]

        status = StatusMessage(context.bot, chat_id)
        await status.start()
        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)

        t0 = time.monotonic()

        try:
            new_images = await generate_images(
                session.current_prompt,
                session.sketch_bytes,
                count=2,
                model=info["model"],
                image_size=info["image_size"],
                timeout_ms=info["timeout"],
            )
        except GenerationError as e:
            await status.fail(_error_message(e))
            return

        if not new_images:
            await status.fail("`генерация не удалась — ещё раз?`")
            return

        elapsed = int(time.monotonic() - t0)

        logger.info(
            "generation user=%d model=%s mode=%s variants=%d time=%ds (more)",
            user_id, info["model"], session.image_mode, len(new_images), elapsed,
        )

        session.images.extend(new_images)
        grid = make_grid(session.images)

        extra = [InlineKeyboardButton("Ещё 2 варианта", callback_data="more")]
        keyboard = _pick_keyboard(len(session.images), extra_buttons=extra)

        await status.done()

        await context.bot.send_photo(
            chat_id,
            photo=grid,
            reply_markup=keyboard,
        )


# ---------- /prompt ----------

@authorized
async def cmd_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    session = get_session(user_id)

    if not session.current_prompt:
        await update.message.reply_text("`сессия пуста — отправь скетч`", parse_mode="Markdown")
        return

    await update.message.reply_text(f"Текущий промпт:\n\n{session.current_prompt}")


# ---------- /prompt_edit ----------

@authorized
async def cmd_prompt_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    session = get_session(user_id)

    if not session.current_prompt:
        await update.message.reply_text("`сессия пуста — отправь скетч`", parse_mode="Markdown")
        return

    session.awaiting_prompt_edit = True
    await update.message.reply_text("Что нужно поправить в промпте? Напишите правки следующим сообщением:")


async def _edit_prompt(chat_id: int, user_id: int, session, edits: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    if session.lock.locked():
        await context.bot.send_message(chat_id, "`генерация идёт — подожди`", parse_mode="Markdown")
        return

    # Статус показывается внутри _run_full_pipeline

    edit_hypothesis = (
        f"Текущий промпт: {session.current_prompt}\n"
        f"Правки от пользователя: {edits}\n"
        f"Обнови промпт соответственно."
    )
    await _run_full_pipeline(
        chat_id, user_id, session.sketch_bytes, edit_hypothesis,
        ref_images=session.ref_images or None,
        context=context,
    )


# ---------- Выбор вариантов (inline-кнопки) ----------

async def _send_variant(bot, chat_id: int, image_bytes: bytes, n: int) -> None:
    """Фоновая отправка одного варианта."""
    try:
        await bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)
        await bot.send_document(
            chat_id,
            document=image_bytes,
            filename=f"variant_{n}.jpg",
        )
    except Exception:
        logger.exception("Ошибка отправки варианта %d", n)
        try:
            await bot.send_message(chat_id, "`не удалось отправить файл — ещё раз?`", parse_mode="Markdown")
        except Exception:
            pass


@authorized
async def callback_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    session = get_session(user_id)

    n = int(query.data.split(":", 1)[1])

    if not session.images or n < 1 or n > len(session.images):
        await context.bot.send_message(chat_id, "`вариант не найден`", parse_mode="Markdown")
        return

    # Отправляем в фоне — хэндлер завершается мгновенно, следующий callback обрабатывается сразу
    asyncio.create_task(_send_variant(context.bot, chat_id, session.images[n - 1], n))


@authorized
async def callback_suggest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подсказка-кнопка → новая итерация с текстом подсказки как гипотезой."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    session = get_session(user_id)

    idx = int(query.data.split(":", 1)[1])

    if not session.sketch_bytes:
        await context.bot.send_message(chat_id, "`сессия пуста — отправь скетч`", parse_mode="Markdown")
        return

    if not session.suggestions or idx >= len(session.suggestions):
        return

    suggestion = session.suggestions[idx]

    await _run_full_pipeline(
        chat_id, user_id, session.sketch_bytes, suggestion,
        ref_images=session.ref_images or None,
        context=context,
    )


# ---------- Полный пайплайн ----------

async def _run_full_pipeline(chat_id: int, user_id: int, sketch: bytes, caption: str, ref_images: list[bytes] | None, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = get_session(user_id)

    # Проверка дневного лимита
    if not session.check_daily_limit(DAILY_LIMIT_PER_USER):
        await context.bot.send_message(
            chat_id,
            "`лимит исчерпан — сброс в полночь`", parse_mode="Markdown",
        )
        return

    # Lock на сессию — не запускать параллельные генерации
    if session.lock.locked():
        await context.bot.send_message(chat_id, "`генерация идёт — подожди`", parse_mode="Markdown")
        return

    async with session.lock:
        info = IMAGE_MODELS[session.image_mode]
        t0 = time.monotonic()

        status = StatusMessage(context.bot, chat_id)
        await status.start()

        try:
            prompt, suggestions = await generate_prompt(sketch, caption, ref_images=ref_images, grid=info.get("grid", False))
        except Exception:
            logger.exception("Ошибка генерации промпта")
            await status.fail("`промпт: ошибка — ещё раз?`")
            return

        session.current_prompt = prompt
        session.suggestions = suggestions

        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)

        try:
            images = await generate_images(
                prompt, sketch,
                count=info["count"],
                model=info["model"],
                image_size=info["image_size"],
                grid=info.get("grid", False),
                timeout_ms=info["timeout"],
            )
        except GenerationError as e:
            await status.fail(_error_message(e))
            return

        if not images:
            await status.fail("`генерация не удалась — ещё раз?`")
            return

        elapsed = int(time.monotonic() - t0)

        logger.info(
            "generation user=%d model=%s mode=%s variants=%d time=%ds",
            user_id, info["model"], session.image_mode, len(images), elapsed,
        )

        session.images = images
        grid = make_grid(images)

        # Кнопки выбора + «ещё 2» для моделей с count <= 2
        extra = None
        if info["count"] <= 2:
            extra = [InlineKeyboardButton("Ещё 2 варианта", callback_data="more")]
        keyboard = _pick_keyboard(len(images), extra_buttons=extra, suggestions=suggestions)

        await status.done()

        await context.bot.send_photo(
            chat_id,
            photo=grid,
            reply_markup=keyboard,
        )


# ---------- Фото ----------

async def _process_photos(chat_id: int, user_id: int, photos: list[bytes], caption: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = get_session(user_id)

    # Проверка lock ДО сохранения скетча — чтобы не перезаписать данные во время генерации
    if session.lock.locked():
        await context.bot.send_message(chat_id, "`генерация идёт — подожди`", parse_mode="Markdown")
        return

    session.sketch_bytes = photos[0]
    session.ref_images = photos[1:] if len(photos) > 1 else []

    if not caption:
        ref_note = f" + {len(session.ref_images)} реф(ов)" if session.ref_images else ""
        await context.bot.send_message(
            chat_id,
            f"Скетч сохранён{ref_note}. Добавьте текстовое описание гипотезы к картинке.",
        )
        return

    await _run_full_pipeline(
        chat_id, user_id, photos[0], caption,
        ref_images=session.ref_images or None,
        context=context,
    )


async def _process_media_group(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    mg_id = data["media_group_id"]

    buf = _media_group_buffer.pop(mg_id, None)
    if not buf:
        return

    await _process_photos(buf["chat_id"], buf["user_id"], buf["photos"], buf["caption"], context)


@authorized
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    photo = update.message.photo[-1]
    file = await photo.get_file()
    photo_bytes = bytes(await file.download_as_bytearray())

    # 👀 реакция — мгновенный «кивок» (BOT_TOV)
    try:
        await update.message.set_reaction("👀")
    except Exception:
        pass

    media_group_id = update.message.media_group_id

    if media_group_id:
        if media_group_id not in _media_group_buffer:
            _media_group_buffer[media_group_id] = {
                "chat_id": chat_id,
                "user_id": user_id,
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
        await _process_photos(chat_id, user_id, [photo_bytes], caption, context)


# ---------- Текст ----------

@authorized
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    session = get_session(user_id)

    # Если ждём правки промпта
    if session.awaiting_prompt_edit:
        session.awaiting_prompt_edit = False
        if session.current_prompt:
            await _edit_prompt(chat_id, user_id, session, text, context)
            return

    # Кириллические алиасы
    if text.strip() == "/старт":
        await cmd_start(update, context)
        return

    if text.strip() == "/промпт":
        await cmd_prompt(update, context)
        return

    await update.message.reply_text("`отправь скетч с гипотезой`", parse_mode="Markdown")


# ---------- Ошибки ----------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Необработанная ошибка: %s", context.error, exc_info=context.error)

    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                update.effective_chat.id,
                "`ошибка — попробуй /start`",
                parse_mode="Markdown",
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
        .concurrent_updates(True)
        .post_init(post_init)
        .build()
    )

    # Латинские команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("prompt", cmd_prompt))
    app.add_handler(CommandHandler("prompt_edit", cmd_prompt_edit))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("more", cmd_more))

    # Inline-кнопки
    app.add_handler(CallbackQueryHandler(callback_model, pattern=r"^model:"))
    app.add_handler(CallbackQueryHandler(callback_more, pattern=r"^more$"))
    app.add_handler(CallbackQueryHandler(callback_pick, pattern=r"^pick:\d+$"))
    app.add_handler(CallbackQueryHandler(callback_suggest, pattern=r"^suggest:"))

    # Фото и текст
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.add_error_handler(error_handler)

    logger.info("Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
