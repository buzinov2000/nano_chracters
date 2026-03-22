# CLAUDE.md

Телеграм-бот «курьер» для пайплайна разработки персонажей.
Принимает скетч + гипотезу → генерирует промпт (Gemini Flash) → генерирует варианты картинок (Gemini Image) → возвращает сетку с номерами → итерирует по обратной связи.

## Документация

Перед началом работы прочитай файлы в `doc/`:
- `doc/CHARACTER_PIPELINE_BOT.md` — архитектура, агенты, команды бота, стек
- `doc/DEVELOPMENT_PLAN.md` — пошаговый план разработки, структура проекта, заметки по SDK

## Ключевые решения

- **SDK:** `google-genai` (не `google-generativeai`, он deprecated). Импорт: `from google import genai`
- **Промпт-агент:** `gemini-2.5-flash` — переводит скетч + текст в промпт для генератора
- **Генерация картинок:** `gemini-2.5-flash-image` через `generate_content` с `response_modalities=["TEXT", "IMAGE"]`. Одна картинка за вызов — для N вариантов нужно N параллельных вызовов через `client.aio`
- **Telegram:** `python-telegram-bot` v21+ (полностью async)
- **Команды бота:** на русском (`/промпт`, `/старт`)

## Запуск

```bash
pip install -r requirements.txt
# заполнить .env: TELEGRAM_BOT_TOKEN, GOOGLE_API_KEY
python bot.py
```

## Структура

```
bot.py       — точка входа, хэндлеры Telegram
agent.py     — промпт-агент (Gemini Flash)
imagen.py    — генерация картинок (Gemini Image)
grid.py      — сборка сетки превью с номерами (Pillow)
session.py   — состояние сессии (in-memory)
config.py    — загрузка .env, константы
prompts/     — системные промпты
doc/         — архитектура и план разработки
```
