# Параллельность и защита бота

> Дополнение к `DEVELOPMENT_PLAN.md`. **Реализовано** — все пункты выполнены.

---

## Проблема

Бот будут использовать несколько человек одновременно. Генерация занимает 10–60 секунд в зависимости от модели. Пока один пользователь ждёт — бот должен принимать запросы от других. Плюс нужна защита от несанкционированного использования и контроль расходов на API.

---

## Часть 1 — Параллельность

### Что уже работает

- `python-telegram-bot` v21+ — полностью async, каждое сообщение — отдельная корутина
- `client.aio.models.generate_content()` — async-вызовы к Google API
- `asyncio.create_task()` — фоновая отправка документов при нажатии inline-кнопок
- `job_queue.run_once` — буферизация медиагрупп (не блокирует event loop)

Если всё правильно реализовано, бот уже не блокируется при обработке одного запроса.

### Что нужно добавить

**1. Семафор на одновременные вызовы к Google API**

Разные модели создают разную нагрузку:
- Fast (`gemini-2.5-flash-image`): 4 параллельных вызова на генерацию
- Pro/Quality (grid): 1 вызов на генерацию

Без ограничения: 3 пользователя одновременно на fast-модели = 12 параллельных вызовов → 429 от Google.

```python
# config.py
MAX_CONCURRENT_API_CALLS = 8  # максимум одновременных вызовов к Image API

# imagen.py
import asyncio

_semaphore = asyncio.Semaphore(MAX_CONCURRENT_API_CALLS)

async def _generate_single(client, model, contents, config):
    async with _semaphore:
        return await client.aio.models.generate_content(
            model=model, contents=contents, config=config
        )
```

Все вызовы `generate_content` для картинок — через семафор. И для fast (4 вызова через `gather`), и для grid (1 вызов). Промпт-агент (текстовый Gemini Flash) — без семафора, он дешёвый и быстрый.

**2. Lock на сессию пользователя**

Если пользователь отправит два скетча подряд — второй может перезаписать сессию пока первый ещё генерируется. Или нажмёт inline-кнопку пока идёт `/prompt_edit`.

```python
# session.py
import asyncio

class Session:
    def __init__(self):
        self.lock = asyncio.Lock()
        # ...остальные поля...
```

```python
# bot.py
async def handle_sketch(update, context):
    session = get_session(chat_id)

    if session.lock.locked():
        await update.message.reply_text("⏳ Предыдущая генерация ещё идёт, подождите.")
        return

    async with session.lock:
        # ... полный цикл генерации
```

Проверка `locked()` до `async with` — чтобы не ставить в очередь, а сразу ответить пользователю.

**3. Защита user_data.json от одновременной записи**

Несколько пользователей могут переключить модель одновременно → гонка при записи в файл.

```python
# session.py
_file_lock = asyncio.Lock()

async def save_user_data(data: dict):
    async with _file_lock:
        # asyncio.to_thread чтобы файловый I/O не блокировал event loop
        await asyncio.to_thread(_write_json, "user_data.json", data)
```

**4. Статус-сообщения с прогрессом**

```python
status = StatusMessage(context.bot, chat_id)
await status.start()                          # `📝 пишу промпт` с анимацией точек
# ... generate_prompt ...
await status.set_phase(StatusMessage.IMAGE)    # `🎨 генерирую` с анимацией точек
# ... generate_images ...
await status.done()                            # удаляет сообщение
# отправить сетку
```

---

## Часть 2 — Защита доступа (whitelist)

### Whitelist по Telegram user ID

Telegram user ID — числовой, не меняется, не подделывается.

```python
# config.py
import os

ALLOWED_USERS: set[int] = set()
_raw = os.getenv("ALLOWED_USERS", "")
if _raw:
    ALLOWED_USERS = {int(uid.strip()) for uid in _raw.split(",") if uid.strip()}
```

```env
# .env (и на VPS, и локально)
ALLOWED_USERS=123456789,987654321
```

```python
# bot.py — декоратор для всех хэндлеров
from functools import wraps
from config import ALLOWED_USERS

def authorized(func):
    @wraps(func)
    async def wrapper(update, context):
        user_id = update.effective_user.id
        if ALLOWED_USERS and user_id not in ALLOWED_USERS:
            await update.message.reply_text("⛔ Доступ ограничен.")
            return
        return await func(update, context)
    return wrapper
```

Применить к `handle_sketch`, `handle_text`, `callback_query_handler` — ко всему, что запускает генерацию или отдаёт картинки.

**Если `ALLOWED_USERS` пустой** — бот открыт для всех (для локального тестирования).

**Как узнать user_id:** отправить боту `/start`, в логах будет `update.effective_user.id`. Или @userinfobot в Telegram.

---

## Часть 3 — Rate limiting (контроль расходов)

### Per-user дневной лимит генераций

Одна генерация (fast) ≈ $0.16, одна генерация (Pro/Quality grid) ≈ $0.04–0.13. Поставить лимит на количество генераций, не на деньги — проще и надёжнее.

```python
# session.py
from datetime import date

class Session:
    def __init__(self):
        # ...существующие поля...
        self.generations_today: int = 0
        self.last_generation_date: date | None = None

    def check_daily_limit(self, limit: int) -> bool:
        """True = можно генерировать."""
        today = date.today()
        if self.last_generation_date != today:
            self.generations_today = 0
            self.last_generation_date = today
        if self.generations_today >= limit:
            return False
        self.generations_today += 1
        return True
```

```python
# config.py
DAILY_LIMIT_PER_USER = 50  # генераций в день (~$8 при fast, ~$2.5 при grid)
```

```python
# bot.py
if not session.check_daily_limit(DAILY_LIMIT_PER_USER):
    await update.message.reply_text(
        f"⚠️ Дневной лимит ({DAILY_LIMIT_PER_USER} генераций) исчерпан. Сброс в полночь."
    )
    return
```

**Заметка:** лимит живёт в памяти (в сессии) — при перезапуске бота сбрасывается. На первом этапе это нормально. Если нужна точность — вынести в `user_data.json`.

### Логирование расходов

Для мониторинга — логировать каждую генерацию:

```python
logger.info(
    "generation user=%d model=%s mode=%s variants=%d",
    user_id, model_id, mode, count
)
```

По логам можно посчитать расход: `journalctl -u nano-characters | grep generation | wc -l`.

Точный биллинг — в Google Cloud Console.

---

## Итоговый .env

```env
TELEGRAM_BOT_TOKEN=...
GOOGLE_API_KEY=...
ALLOWED_USERS=123456789,987654321
DAILY_LIMIT_PER_USER=50
```

---

## Чек-лист для реализации

- [x] Семафор в `imagen.py` на `MAX_CONCURRENT_API_CALLS` (все вызовы generate_content для картинок)
- [x] Lock на сессию — не запускать генерацию если предыдущая ещё идёт
- [x] Lock на `user_data.json` при записи
- [x] Whitelist `ALLOWED_USERS` в `.env`, декоратор `@authorized`
- [x] Дневной лимит генераций в `session.py`
- [x] Логирование: кто, какая модель, сколько вариантов, время генерации
- [ ] Добавить `ALLOWED_USERS` и `DAILY_LIMIT_PER_USER` в `.env` на VPS

---

## Детали реализации (отличия от плана)

- **`concurrent_updates(True)`** — добавлено в `ApplicationBuilder`. Без этого `python-telegram-bot` обрабатывает апдейты последовательно и lock никогда не срабатывает
- **Сессии по `user_id`**, а не по `chat_id` — чтобы в групповых чатах каждый пользователь имел свою сессию, lock и лимит
- **Статус-сообщения с прогрессом** (п.4 из плана) — реализован класс `StatusMessage` в `bot.py`: одно сообщение, редактируется in-place с анимацией точек. Две фазы: `PROMPT` (`📝 пишу промпт`) → `IMAGE` (`🎨 генерирую`). После генерации сообщение удаляется
- **`save_default_model`** стала async (с `_file_lock` и `asyncio.to_thread`)
