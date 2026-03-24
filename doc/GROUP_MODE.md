# Режим работы в группах (@mention trigger)

> Дополнение к архитектуре. Добавить как этап после concurrency/whitelist.

---

## Задача

В группах/каналах бот не должен реагировать на все фотографии — только когда к нему явно обратились. В личном чате — поведение не меняется.

---

## Правила срабатывания

| Контекст | Условие | Реакция бота |
|---|---|---|
| Личный чат | Фото + caption | Генерация (как сейчас) |
| Личный чат | Текст | Обработка команд (как сейчас) |
| Группа | Фото + caption с `@bot_username` | Генерация |
| Группа | Текст с `@bot_username` | Обработка команд |
| Группа | Reply на сообщение бота + текст | Итерация промпта |
| Группа | Reply на сообщение бота + числа | Выбор вариантов |
| Группа | Inline-кнопка | Отправка варианта (работает без изменений) |
| Группа | Любое другое сообщение | **Игнорировать** |

---

## Реализация

### 1. Определение контекста: личный чат или группа

```python
def _is_private(update) -> bool:
    return update.effective_chat.type == "private"
```

### 2. Проверка, обращаются ли к боту (для групп)

```python
def _is_addressed_to_bot(update, context) -> bool:
    """Проверить, что сообщение адресовано боту в группе."""
    # Личный чат — всегда адресовано
    if _is_private(update):
        return True

    message = update.effective_message

    # Reply на сообщение бота — считаем обращением
    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.id == context.bot.id:
            return True

    # Упоминание @bot_username в тексте или caption
    bot_username = context.bot.username  # без @
    text = message.text or message.caption or ""
    if f"@{bot_username}" in text:
        return True

    return False
```

### 3. Очистка текста от @mention

Перед отправкой в промпт-агент — убрать `@bot_username` из текста, чтобы оно не попало в промпт.

```python
def _clean_mention(text: str, bot_username: str) -> str:
    """Убрать @bot_username из текста."""
    return text.replace(f"@{bot_username}", "").strip()
```

### 4. Применение в хэндлерах

```python
async def handle_photo(update, context):
    if not _is_addressed_to_bot(update, context):
        return  # молча игнорируем

    caption = update.message.caption or ""
    caption = _clean_mention(caption, context.bot.username)

    if not caption:
        await update.message.reply_text("Добавьте описание гипотезы после @упоминания.")
        return

    # ... дальше как сейчас: генерация промпта, картинок, сетка

async def handle_text(update, context):
    if not _is_addressed_to_bot(update, context):
        return  # молча игнорируем

    text = _clean_mention(update.message.text, context.bot.username)
    # ... дальше как сейчас
```

### 5. Медиагруппы в группах

Медиагруппы (несколько фото) в группах работают так же — буферизация через `job_queue.run_once`. Проверка `_is_addressed_to_bot` происходит при получении первого фото с caption. Если caption есть и содержит `@bot_username` — обрабатываем всю группу. Если нет — игнорируем.

```python
async def handle_photo(update, context):
    if not _is_addressed_to_bot(update, context):
        return

    # ... буферизация медиагруппы как сейчас
```

### 6. Callback query (inline-кнопки)

Inline-кнопки не требуют изменений — они привязаны к конкретному сообщению бота и вызываются только через UI.

### 7. Команды в группах

Telegram автоматически добавляет `@bot_username` к командам в группах: `/start@nanocharbot`. `CommandHandler` в `python-telegram-bot` обрабатывает это автоматически — никаких изменений не нужно.

Для кириллических алиасов (`/старт`, `/промпт`) в `handle_text` — проверка `_is_addressed_to_bot` уже покроет случай, когда алиас написан без упоминания.

---

## Настройки бота в BotFather

### Privacy Mode (Group Privacy)

**Отключить Group Privacy** (уже сделано), чтобы бот видел все сообщения в группе. Иначе бот увидит только:
- Сообщения с `/команда`
- Сообщения, где бот упомянут
- Reply на сообщения бота

Проблема: без Group Privacy бот не увидит обычные фото с caption содержащим `@bot`, если caption не начинается с `/`.

> **Важно:** после отключения Group Privacy бот нужно удалить из группы и добавить заново, чтобы изменение вступило в силу.

### Короткий username

Если текущий username длинный — поменять через BotFather на короткий:
- `@ncbot` — 5 символов
- `@nanocharbot` — 12 символов
- `@nano_bot` — 8 символов (если свободен)

---

## Чек-лист

- [ ] Функция `_is_private(update)` 
- [ ] Функция `_is_addressed_to_bot(update, context)` — проверка mention + reply
- [ ] Функция `_clean_mention(text, bot_username)` — очистка текста
- [ ] Обновить `handle_photo` — проверка перед обработкой
- [ ] Обновить `handle_text` — проверка перед обработкой
- [ ] Обновить медиагруппы — проверка caption первого фото
- [ ] Проверить, что inline-кнопки работают без изменений
- [ ] Проверить, что CommandHandler обрабатывает `/command@bot_username`
- [ ] Рассмотреть смену username на короткий
- [ ] Проверить Group Privacy в BotFather
