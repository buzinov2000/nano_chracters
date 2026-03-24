# Character Pipeline Bot — План разработки

> Этот документ — инструкция для Claude Code. Выполняй этапы последовательно.
> Репозиторий: https://github.com/buzinov2000/nano_chracters
> Архитектура проекта описана в `CHARACTER_PIPELINE_BOT.md` в корне репо.

---

## Контекст

Телеграм-бот, который автоматизирует «курьерскую» часть пайплайна разработки персонажей: принимает скетч + гипотезу → генерирует промпт → отправляет в Gemini Image API → возвращает сетку вариантов с номерами → позволяет итерировать.

Творческие решения принимает человек. Бот — логистика между человеком и API.

---

## Стек и ключевые зависимости

| Компонент | Что использовать |
|---|---|
| Python | 3.11+ |
| Telegram | `python-telegram-bot` (последняя стабильная, v21+) |
| Google AI SDK | `google-genai` (**не** `google-generativeai`, он deprecated) |
| Промпт-агент | модель `gemini-2.5-flash` |
| Генерация картинок | модель `gemini-2.5-flash-image` (Nano Banana) |
| Сборка сетки превью | `Pillow` |
| Конфиг | `python-dotenv` |

### requirements.txt

```
python-telegram-bot>=21.0
google-genai>=1.66.0
Pillow>=10.0
python-dotenv>=1.0
```

### .env (шаблон, добавить в .gitignore)

```
TELEGRAM_BOT_TOKEN=
GOOGLE_API_KEY=
```

> **Важно:** переменная для Google SDK называется `GOOGLE_API_KEY` (так SDK подхватывает автоматически). Можно также передать через `genai.Client(api_key=...)`.

---

## Структура проекта

```
nano_chracters/
├── CHARACTER_PIPELINE_BOT.md   ← архитектурный документ (уже есть)
├── DEVELOPMENT_PLAN.md         ← этот файл
├── bot.py                      ← точка входа, хэндлеры Telegram
├── agent.py                    ← промпт-агент (Gemini Flash)
├── imagen.py                   ← генерация картинок (Gemini Image)
├── grid.py                     ← сборка сетки превью с номерами (Pillow)
├── session.py                  ← состояние сессии пользователя (in-memory)
├── config.py                   ← загрузка .env, константы, модели
├── prompts/
│   └── prompt_agent.txt        ← системный промпт для агента
├── .env                        ← API ключи (в .gitignore)
├── .gitignore
└── requirements.txt
```

---

## Этап 0 — Инициализация проекта

**Задача:** подготовить репозиторий к работе.

**Действия:**
1. Создать `.gitignore` (Python-стандартный + `.env`)
2. Создать `requirements.txt` (см. выше)
3. Создать `config.py`:
   - Загрузка `.env` через `dotenv`
   - Константы: `TELEGRAM_BOT_TOKEN`, `GOOGLE_API_KEY`
   - Константы моделей: `PROMPT_AGENT_MODEL = "gemini-2.5-flash"`, `IMAGE_MODEL = "gemini-2.5-flash-image"`
   - Константа `VARIANTS_COUNT = 4` (сколько картинок генерировать за итерацию)
4. Создать пустые файлы-заглушки: `bot.py`, `agent.py`, `imagen.py`, `grid.py`, `session.py`
5. Создать `prompts/prompt_agent.txt` с начальным системным промптом (см. ниже)

**Начальный системный промпт для агента** (`prompts/prompt_agent.txt`):

```
You are a prompt engineer for character design image generation.

You receive: a sketch image + a text hypothesis from the art director.
You produce: a detailed image generation prompt optimized for the Gemini Image model.

Style direction: 3D-rendered character design, soft studio lighting, clean material definition (plastic, fabric, metal, fur), neutral background, character centered in frame. Think Pixar/DreamWorks quality character turnarounds.

Rules:
- Always describe the character in full: silhouette, proportions, key features, materials, colors
- Incorporate the user's hypothesis literally — it's the creative direction, don't reinterpret it
- Include technical image instructions: "3D render, studio lighting, centered composition, neutral gray background, high detail"
- Keep prompt under 300 words
- Write in English regardless of input language

After the prompt, suggest 2-3 short next-step ideas for the user (in Russian), for example:
- Попробовать другой материал (мех вместо пластика)?
- Сделать вид сзади?
- Показать 4 варианта цвета?

Format your response as:
PROMPT:
[the image generation prompt]

SUGGESTIONS:
- [suggestion 1]
- [suggestion 2]
- [suggestion 3]
```

**Критерий готовности:** `pip install -r requirements.txt` проходит без ошибок, все файлы на месте.

---

## Этап 1 — Скелет бота (Telegram echo)

**Задача:** бот принимает картинку + текст и отвечает эхом. Проверяем, что Telegram-часть работает.

**Файл:** `bot.py`

**Действия:**
1. Импортировать `python-telegram-bot` (v21+, используя `Application` builder pattern)
2. Хэндлер на `/start` — приветствие с кратким описанием команд
3. Хэндлер на сообщение с фото + текстом (или caption):
   - Скачать файл фото в байты (через `photo[-1].get_file()`)
   - Отправить эхо-ответ: "Получил скетч + текст: {caption}"
   - Отправить фото обратно для проверки
4. Хэндлер на текстовое сообщение без фото:
   - Если текст — числа через пробел (паттерн `^\d+(\s+\d+)*$`) → пока заглушка "Выбор вариантов: {числа}"
   - Если текст начинается с `/промпт` → заглушка "Показ/редактирование промпта"
   - Иначе → "Отправьте скетч с описанием гипотезы"

**Критерий готовности:** запускаешь бот, отправляешь картинку с подписью — получаешь эхо. Текстовые команды распознаются корректно.

---

## Этап 2 — Модуль сессий

**Задача:** хранить состояние диалога в памяти.

**Файл:** `session.py`

**Действия:**
1. Класс `Session`:
   ```python
   class Session:
       sketch_bytes: bytes | None    # последний скетч
       current_prompt: str | None    # текущий промпт от агента
       suggestions: list[str]        # подсказки от агента
       images: list[bytes]           # последние сгенерированные картинки (полное разрешение)
       history: list[dict]           # история итераций [{prompt, image_count, timestamp}]
   ```
2. Словарь `sessions: dict[int, Session]` — ключ `chat_id`
3. Функции: `get_session(chat_id) -> Session`, `reset_session(chat_id)`
4. Сессия живёт в памяти процесса. При `/старт` — сброс.

**Критерий готовности:** unit-тест или ручная проверка — создание, получение, сброс сессии работают.

---

## Этап 3 — Промпт-агент

**Задача:** Gemini Flash получает скетч + гипотезу и возвращает промпт для генерации + подсказки.

**Файл:** `agent.py`

**Действия:**
1. Инициализация клиента:
   ```python
   from google import genai
   from config import GOOGLE_API_KEY, PROMPT_AGENT_MODEL

   client = genai.Client(api_key=GOOGLE_API_KEY)
   ```
2. Функция `generate_prompt(sketch_bytes: bytes, hypothesis: str) -> tuple[str, list[str]]`:
   - Загрузить системный промпт из `prompts/prompt_agent.txt`
   - Вызвать `client.models.generate_content()`:
     - model: `PROMPT_AGENT_MODEL`
     - contents: список из [системный промпт (text), скетч (inline_data image/png или jpeg), гипотеза (text)]
   - Распарсить ответ: извлечь блок после `PROMPT:` и список после `SUGGESTIONS:`
   - Вернуть `(prompt_text, suggestions_list)`
3. Обработка ошибок: ловить исключения API, логировать, возвращать понятное сообщение пользователю

**Интеграция в bot.py:**
- При получении скетча + текста: вызвать `generate_prompt()`, сохранить результат в сессию
- Отправить пользователю: "Промпт готов. Генерирую варианты..." + список подсказок

**Критерий готовности:** отправляешь скетч + "Персонаж в стиле мягкой игрушки" → получаешь осмысленный промпт + подсказки.

---

## Этап 4 — Генерация картинок

**Задача:** по промпту от агента сгенерировать N вариантов через Gemini Image API.

**Файл:** `imagen.py`

**Действия:**
1. Функция `generate_images(prompt: str, sketch_bytes: bytes | None = None, count: int = 4) -> list[bytes]`:
   - Вызвать `client.models.generate_content()`:
     - model: `IMAGE_MODEL` (`gemini-2.5-flash-image`)
     - contents: промпт (+ опционально скетч как reference image)
     - config: `GenerateContentConfig(response_modalities=["TEXT", "IMAGE"])`
   - **Важно:** Gemini Image через `generate_content` возвращает одну картинку за вызов. Для N вариантов нужно N параллельных вызовов
   - Собрать `bytes` из `response.parts` где `part.inline_data` не None
   - Вернуть список байтов картинок
2. Для параллельных вызовов использовать `asyncio.gather()` с async-клиентом (`client.aio.models.generate_content`)
3. Обработка ошибок: safety filter блокировки, таймауты, rate limits (retry с backoff)

**Критерий готовности:** вызов с тестовым промптом возвращает 4 картинки в виде bytes.

---

## Этап 5 — Сборка сетки превью

**Задача:** из N картинок собрать одну сетку-превью с номерами.

**Файл:** `grid.py`

**Действия:**
1. Функция `make_grid(images: list[bytes], columns: int = 2) -> bytes`:
   - Открыть каждую картинку через Pillow
   - Ресайзнуть до единого размера (например, 512×512)
   - Создать canvas: `columns × rows` с отступами
   - Вставить картинки в сетку
   - Нарисовать номер в левом верхнем углу каждой картинки (белый текст с чёрной обводкой, крупный шрифт)
   - Сохранить итоговое изображение в bytes (JPEG, quality=85)
   - Вернуть bytes
2. Для 4 вариантов: сетка 2×2. Для 8: сетка 2×4.

**Критерий готовности:** из 4 тестовых картинок получается одна сетка с номерами 1-4.

---

## Этап 6 — Полный цикл генерации

**Задача:** связать всё вместе: скетч → агент → генерация → сетка → пользователь.

**Файл:** `bot.py` (обновление хэндлеров)

**Действия:**
1. Хэндлер на фото + текст:
   - Отправить typing action
   - `prompt, suggestions = await generate_prompt(sketch, text)`
   - Сохранить в сессию
   - Отправить сообщение: "⏳ Генерирую {N} вариантов..."
   - `images = await generate_images(prompt, sketch, count=VARIANTS_COUNT)`
   - Сохранить картинки в сессию
   - `grid = make_grid(images)`
   - Отправить сетку как фото
   - Отправить подсказки как текстовое сообщение с нумерацией
2. Хэндлер на числа (выбор вариантов):
   - Распарсить номера
   - Достать соответствующие картинки из сессии
   - Отправить каждую как документ (полное разрешение, не как сжатое фото)

**Критерий готовности:** полный цикл от скетча до получения выбранных вариантов в полном разрешении.

---

## Этап 7 — Итерация промпта

**Задача:** команда `/промпт` для просмотра и редактирования текущего промпта.

**Файл:** `bot.py` (обновление хэндлеров)

**Действия:**
1. `/промпт` без аргументов → отправить текущий промпт из сессии
2. `/промпт [правки]` → передать текущий промпт + правки агенту:
   - Вызвать `generate_prompt()` с контекстом: "Текущий промпт: {prompt}. Правки от пользователя: {edits}. Обнови промпт соответственно."
   - Перегенерировать картинки с обновлённым промптом
   - Отправить новую сетку + подсказки
3. Обработка случая, когда сессия пуста (нет промпта) → сообщение "Сначала отправьте скетч"

**Критерий готовности:** после генерации можно написать `/промпт сделай глаза больше` → получить обновлённую сетку.

---

## Этап 8 — Полировка и error handling

**Задача:** сделать бот устойчивым к ошибкам и приятным в использовании.

**Действия:**
1. **Логирование:** добавить `logging` во все модули (INFO для нормального флоу, ERROR для исключений)
2. **Обработка ошибок API:**
   - Rate limit (429) → retry с exponential backoff (3 попытки)
   - Safety filter → сообщить пользователю "Генерация заблокирована фильтрами, попробуйте переформулировать"
   - Таймаут → "Сервер не ответил, попробуйте ещё раз"
3. **Валидация входа:**
   - Проверка, что файл — изображение (не документ, не видео)
   - Ограничение размера (Telegram сжимает фото, но caption может быть пустым)
4. **UX:**
   - Typing indicator пока идёт генерация
   - Время генерации в ответе ("Сгенерировано за 12 сек")
   - `/старт` — полный сброс с подтверждением
5. **README.md** с инструкциями по запуску

**Критерий готовности:** бот корректно обрабатывает ошибки API, не падает при невалидном вводе, логирует всё.

---

## Дополнительные этапы (реализованы после основного плана)

### Доп. 1 — Поддержка медиагрупп (скетч + рефы)
- Telegram отправляет несколько фото как отдельные update
- Буферизация через `job_queue.run_once` с задержкой 1.5 сек
- Первое фото → скетч, остальные → рефы для промпт-агента

### Доп. 2 — Переключение моделей
- 3 модели: Nano Banana (fast), Nano Banana Pro, Nano Banana 2 (quality)
- Конфигурация в `config.py` → `IMAGE_MODELS` dict
- `/model` команда с inline-клавиатурой
- Дефолтная модель сохраняется между перезапусками в `user_data.json`

### Доп. 3 — Меню бота и inline-кнопки
- Команды зарегистрированы через `set_my_commands` в `post_init`
- Inline-кнопки с номерами под сеткой → отправка варианта как документ в фоне (`asyncio.create_task`)
- Кнопка «Ещё 2 варианта» для генерации дополнительных

### Доп. 4 — Grid 2x2 для Pro/Quality моделей
- Один API-вызов вместо четырёх → экономия и скорость
- Промпт-агент использует отдельный системный промпт (`prompt_agent_grid.txt`) с инструкцией про grid
- Разрезка grid-изображения на 4 варианта через Pillow (`_split_grid`)
- Grid-инструкция не теряется при `/prompt_edit`, т.к. вшита в системный промпт агента

### Доп. 5 — Per-model таймауты и retry
- Каждая модель имеет свой таймаут в конфиге (300-600 сек)
- `genai.Client` кэшируется по таймауту через `types.HttpOptions(timeout=...)`
- Retry с exponential backoff (3 попытки) для 429/500/503/timeout
- `GenerationError` с типами: safety_filter, overloaded, timeout

---

## Реализованный этап — Деплой на VPS + разделение prod/beta

### Схема работы

```
VPS (production)                    Локальная машина (beta/dev)
─────────────────                   ──────────────────────────
branch: main                        branch: feature-*, fix-*
bot token: PROD_BOT_TOKEN           bot token: BETA_BOT_TOKEN
├── ~/bots/nano_characters/         Локальный запуск python bot.py
│   ├── .env (prod token)           .env (beta token)
│   └── ...
└── systemd: nano-characters.service
```

**Два отдельных бота в Telegram** (два токена от @BotFather):
- **Prod-бот** — работает на VPS, ветка `main`, основной токен
- **Beta-бот** — работает локально, любая ветка, отдельный токен

Это исключает конфликты: два процесса с одним токеном вызывают ошибку Telegram API (409 Conflict).

### Важно: на VPS уже есть другие боты

- НЕ трогать существующие сервисы и папки
- Создать отдельную директорию (например `~/bots/nano_characters/`)
- Создать отдельный systemd unit `nano-characters.service`
- Для настройки использовать существующий сервис-файл другого бота как образец (попросить у пользователя)

### Шаги деплоя

1. **Создать prod-бота** в @BotFather → получить токен
2. **На VPS:**
   - `mkdir -p ~/bots/nano_characters`
   - `git clone <repo> ~/bots/nano_characters`
   - Создать venv, установить зависимости
   - Создать `.env` с prod-токеном и `GOOGLE_API_KEY`
3. **Systemd unit** `nano-characters.service`:
   - `WorkingDirectory=~/bots/nano_characters`
   - `ExecStart=` с путём к venv python
   - `Restart=on-failure`
   - Включить и запустить: `systemctl enable --now nano-characters`
4. **Обновление prod:** `git pull && systemctl restart nano-characters`
5. **Локально:** `.env` с beta-токеном, работа на любых ветках

### Git workflow

```
main ← только проверенный код, автоматически на VPS
  ↑
feature-* / fix-* ← разработка локально с beta-ботом
```

---

## Реализованный этап — Параллельность и защита

Подробности в `CONCURRENCY_AND_PROTECTION.md`. Все пункты выполнены:

- [x] Семафор `MAX_CONCURRENT_API_CALLS=8` в `imagen.py`
- [x] Session lock — блокировка параллельных генераций одного пользователя
- [x] File lock на `user_data.json` (async, `asyncio.to_thread`)
- [x] Whitelist `ALLOWED_USERS` + декоратор `@authorized`
- [x] Дневной лимит `DAILY_LIMIT_PER_USER=50`
- [x] Логирование генераций: user, model, mode, variants, time
- [x] `concurrent_updates(True)` в ApplicationBuilder
- [x] Сессии по `user_id` (поддержка групповых чатов)

---

## Бэклог

- ❌ Транскрипция голосовых через Gemini Audio
- ❌ Персистентность сессий между перезапусками (картинки, промпты — сейчас in-memory)
- ❌ A/B тест качества промптов Gemini Flash vs Claude Haiku
- ❌ Скрипт автодеплоя (git hook или GitHub Actions → SSH → pull + restart)

---

## Заметки для Claude Code

- **SDK:** используй `google-genai`, **не** `google-generativeai` (deprecated). Импорт: `from google import genai`
- **Клиент:** `client = genai.Client(api_key=API_KEY)` — для Gemini Developer API, не Vertex AI
- **Генерация картинок** через `generate_content`, не через `generate_image` (это Imagen, другой API). Нужен параметр `config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"])`
- **Одна картинка за вызов:** Gemini Image возвращает одну картинку per request. Для 4 вариантов — 4 вызова
- **Async:** `python-telegram-bot` v21+ полностью async. Используй `client.aio` для async-вызовов Google API
- **Парсинг ответа агента:** ответ Gemini Flash — plain text. Парси по маркерам `PROMPT:` и `SUGGESTIONS:`
- **Картинки в ответе:** `response.candidates[0].content.parts` — итерируй, ищи `part.inline_data` с `mime_type` начинающимся на `image/`
- **Триальный аккаунт:** $300 кредитов, не экономим на тестах — но не делай лишних вызовов в циклах
- **Кодировка команд:** команды бота на русском (`/промпт`, `/старт`) — используй UTF-8, проверяй через `message.text.startswith()`
