# CLAUDE.md

Телеграм-бот «курьер» для пайплайна разработки персонажей.
Принимает скетч + рефы (опционально) + гипотезу → генерирует промпт (Gemini Flash) → генерирует варианты картинок (Gemini Image) → возвращает сетку с номерами и inline-кнопками → итерирует по обратной связи.

## Документация

Перед началом работы прочитай файлы в `doc/`:
- `doc/CHARACTER_PIPELINE_BOT.md` — архитектура, агенты, команды, модели, известные особенности
- `doc/DEVELOPMENT_PLAN.md` — пошаговый план, реализованные этапы, заметки по SDK
- `doc/VPS_OPS.md` — сервер, деплой, systemd, логи
- `doc/CONCURRENCY_AND_PROTECTION.md` — параллельность, whitelist, rate limiting (план)
- `doc/GROUP_MODE.md` — работа в группах: @mention trigger, reply-итерации
- `doc/BOT_TOV.md` — тон бота: статусы, ошибки, подсказки-вопросы, ритм диалога (реализовано)

## Ключевые решения

- **SDK:** `google-genai` (не `google-generativeai`, он deprecated). Импорт: `from google import genai`
- **Промпт-агент:** `gemini-2.5-flash`. Два системных промпта: `prompt_agent.txt` (fast-модель) и `prompt_agent_grid.txt` (Pro/Quality с grid 2x2)
- **Генерация картинок:** три модели, переключение через `/model`:
  - `gemini-2.5-flash-image` — fast, 4 параллельных вызова, 1K
  - `gemini-3-pro-image-preview` — Pro, grid 2x2, один вызов, 2K
  - `gemini-3.1-flash-image-preview` — Quality, grid 2x2, один вызов, 2K
- **Grid 2x2:** Pro и Quality модели получают grid-инструкцию в промпте, возвращают одно изображение, бот разрезает на 4 варианта через Pillow
- **Telegram:** `python-telegram-bot` v21+ (async). Команды латинские (`/start`, `/prompt`, `/prompt_edit`, `/model`, `/more`), кириллические алиасы через текстовый хэндлер
- **Inline-кнопки:** выбор вариантов + «Ещё 2» + подсказки-вопросы под сеткой, отправка документов в фоне через `asyncio.create_task`. Подсказки хранятся в сессии по индексу (`suggest:0`), нажатие = новая итерация
- **StatusMessage:** класс в `bot.py` — одно сообщение с анимацией точек, edit-in-place. Фазы: `PROMPT` (📝) → `IMAGE` (🎨). После генерации удаляется
- **TOV:** все сообщения бота в моноспейсе (backticks + `parse_mode="Markdown"`). Ошибки — короткие, формат «факт — действие». Реакция 👀 на скетч
- **Медиагруппы:** буферизация через `job_queue.run_once` с задержкой 1.5 сек, первое фото = скетч, остальные = рефы
- **Персистентность:** дефолтная модель в `user_data.json`, сессии in-memory (сбрасываются при перезапуске)

## Запуск

```bash
pip install -r requirements.txt
# заполнить .env: TELEGRAM_BOT_TOKEN, GOOGLE_API_KEY
python bot.py
```

## Структура

```
bot.py           — точка входа, хэндлеры Telegram, StatusMessage, inline-кнопки
agent.py         — промпт-агент (Gemini Flash), выбор промпта по режиму модели
imagen.py        — генерация картинок, retry, grid split
grid.py          — сборка сетки превью с номерами (Pillow)
session.py       — состояние сессии + персистентная дефолтная модель
config.py        — загрузка .env, константы, конфигурация моделей
prompts/         — системные промпты (обычный + grid)
doc/             — архитектура, план, VPS, concurrency
user_data.json   — сохранённые настройки (в .gitignore)
```

## VPS (production)

```bash
# Обновление
ssh petrick@38.180.200.88 "cd ~/nano_characters && git pull && sudo systemctl restart nano-characters"

# Логи
ssh petrick@38.180.200.88 "journalctl -u nano-characters -f"
```

## Важно

- `thinking_level` не поддерживается image-моделями — только текстовыми
- Кириллические команды (`/старт`, `/промпт`) обрабатываются через `handle_text`, не через `CommandHandler`
- Два отдельных бота (prod/beta) — два токена от BotFather, иначе 409 Conflict
- Telegram httpx таймауты увеличены: read=60, write=60, connect=30
