# VPS — эксплуатация и шпаргалка

## Сервер

| Параметр | Значение |
|---|---|
| Хостинг | Hetzner UK |
| IP | 38.180.200.88 |
| OS | Ubuntu 22.04.4 LTS |
| RAM | 1 GB |
| Пользователь бота | `petrick` (пароль в личных записях) |
| Root-пароль | в личных записях |

---

## Подключение по SSH

С Windows (PowerShell или Terminal):

```powershell
ssh petrick@38.180.200.88
```

Или под root (для системных операций):

```powershell
ssh root@38.180.200.88
```

---

## Управление сервисом

```bash
# Статус
systemctl status petrick-bot

# Перезапуск (например после обновления .env или кода)
systemctl restart petrick-bot

# Остановить
systemctl stop petrick-bot

# Запустить
systemctl start petrick-bot
```

---

## Логи

```bash
# Логи в реальном времени
journalctl -u petrick-bot -f

# Последние 50 строк
journalctl -u petrick-bot -n 50

# Логи за сегодня
journalctl -u petrick-bot --since today
```

---

## Обновление кода (git pull)

```bash
su - petrick
cd ~/petrick-bot
git pull
systemctl restart petrick-bot
```

---

## Обновление .env (смена токена, канала и т.д.)

Отредактировать прямо на сервере:

```bash
nano /home/petrick/petrick-bot/.env
```

Затем перезапустить:

```bash
systemctl restart petrick-bot
```

Или перезаписать файл с локальной Windows (PowerShell):

```powershell
scp ".env" petrick@38.180.200.88:/home/petrick/petrick-bot/.env
```

После этого — перезапустить сервис.

---

## Смена CHANNEL_ID (переезд с группы на канал)

1. Добавь бота администратором в канал
2. Получи ID канала (начинается с `-100...`)
3. Обнови `.env` на сервере:

```bash
sed -i 's/^CHANNEL_ID=.*/CHANNEL_ID=-100xxxxxxxxxx/' /home/petrick/petrick-bot/.env
systemctl restart petrick-bot
```

---

## Где что лежит на сервере

| Путь | Что это |
|---|---|
| `/home/petrick/petrick-bot/` | Корень проекта |
| `/home/petrick/petrick-bot/venv/` | Виртуальное окружение Python |
| `/home/petrick/petrick-bot/.env` | Credentials (не в git) |
| `/home/petrick/petrick-bot/data/state.json` | Счётчик, использованные имена и фразы |
| `/home/petrick/petrick-bot/output/` | Сохранённые PNG (можно чистить) |
| `/etc/systemd/system/petrick-bot.service` | Systemd unit-файл |

---

## Пополнение контента

Отредактировать TSV-файлы локально → закоммитить в git → сделать `git pull` на сервере → перезапустить бота.

| Файл | Что добавлять |
|---|---|
| `data/phrases.tsv` | Новые строки: `фраза_м\tфраза_ж` |
| `data/names.tsv` | Новые строки: `Имя\tМ` или `Имя\tЖ` |

Бот предупредит в дебаг-чате, когда фраз останется меньше 10.

---

## Ручная публикация прямо сейчас

Из дебаг-чата: `/preview` — пришлёт картинку без записи в state.

Если нужна полноценная публикация в канал прямо сейчас:

```bash
su - petrick
cd ~/petrick-bot
source venv/bin/activate
python generate_mascot.py
```

---

## Бэкап state.json

`data/state.json` не в git. Если нужно сохранить состояние (счётчик публикаций, использованные имена):

```powershell
# С сервера на локальную машину (PowerShell)
scp petrick@38.180.200.88:/home/petrick/petrick-bot/data/state.json ./data/state.json
```

---

## SSH-ключ бота (GitHub deploy key)

Ключ хранится на сервере: `/home/petrick/.ssh/id_ed25519`

Добавлен в репозиторий как deploy key (только чтение).
Если нужно добавить тот же ключ в другой репозиторий:

```bash
cat /home/petrick/.ssh/id_ed25519.pub
```
