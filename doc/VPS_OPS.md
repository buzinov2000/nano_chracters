# VPS — эксплуатация nano_characters

## Сервер

| Параметр | Значение |
|---|---|
| Хостинг | Hetzner UK |
| IP | 38.180.200.88 |
| OS | Ubuntu 22.04.4 LTS |
| Пользователь | `petrick` |
| Root-пароль | в личных записях |

---

## Подключение по SSH

```powershell
ssh petrick@38.180.200.88
```

Или под root (для systemd-операций):

```powershell
ssh root@38.180.200.88
```

---

## Где что лежит на сервере

| Путь | Что это |
|---|---|
| `/home/petrick/petrick-bot/` | Другой бот (НЕ ТРОГАТЬ) |
| `/home/petrick/nano_characters/` | Этот проект |
| `/home/petrick/nano_characters/venv/` | Виртуальное окружение Python |
| `/home/petrick/nano_characters/.env` | Credentials (PROD-токен, не в git) |
| `/home/petrick/nano_characters/user_data.json` | Сохранённая дефолтная модель |
| `/etc/systemd/system/petrick-bot.service` | Systemd unit petrick-bot (НЕ ТРОГАТЬ) |
| `/etc/systemd/system/nano-characters.service` | Systemd unit этого бота |

---

## Два бота — prod и beta

| | Prod (VPS) | Beta (локально) |
|---|---|---|
| Ветка | `main` | `feature-*`, `fix-*` |
| Токен | `TELEGRAM_BOT_TOKEN` в `.env` на VPS | Другой токен в `.env` локально |
| Запуск | systemd `nano-characters.service` | `python bot.py` |

Два разных токена от @BotFather — иначе Telegram выдаёт 409 Conflict.

---

## Первоначальный деплой

```bash
# Под пользователем petrick
su - petrick
cd ~

# Клонировать репозиторий
git clone git@github.com:buzinov2000/nano_chracters.git nano_characters

# Виртуальное окружение
cd nano_characters
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Создать .env с prod-токенами
nano .env
# TELEGRAM_BOT_TOKEN=<prod-токен от @BotFather>
# GOOGLE_API_KEY=<ключ Google AI Studio>
```

SSH-ключ для GitHub уже есть на сервере (`/home/petrick/.ssh/id_ed25519`), добавлен как deploy key в petrick-bot. Нужно добавить тот же ключ как deploy key в репозиторий nano_characters:

```bash
cat /home/petrick/.ssh/id_ed25519.pub
# → скопировать и добавить в Settings → Deploy keys репозитория
```

---

## Systemd unit

Создать `/etc/systemd/system/nano-characters.service` (под root):

```ini
[Unit]
Description=Nano Characters Telegram Bot
After=network.target

[Service]
Type=simple
User=petrick
WorkingDirectory=/home/petrick/nano_characters
ExecStart=/home/petrick/nano_characters/venv/bin/python bot.py
Restart=on-failure
RestartSec=10
EnvironmentFile=/home/petrick/nano_characters/.env

[Install]
WantedBy=multi-user.target
```

Активировать:

```bash
systemctl daemon-reload
systemctl enable nano-characters
systemctl start nano-characters
```

---

## Управление сервисом

```bash
# Статус
systemctl status nano-characters

# Перезапуск (после обновления кода или .env)
systemctl restart nano-characters

# Остановить / запустить
systemctl stop nano-characters
systemctl start nano-characters
```

---

## Логи

```bash
# В реальном времени
journalctl -u nano-characters -f

# Последние 50 строк
journalctl -u nano-characters -n 50

# За сегодня
journalctl -u nano-characters --since today
```

---

## Обновление кода (git pull)

```bash
su - petrick
cd ~/nano_characters
git pull
systemctl restart nano-characters
```

Или одной командой через SSH с локальной машины:

```powershell
ssh petrick@38.180.200.88 "cd ~/nano_characters && git pull && sudo systemctl restart nano-characters"
```

---

## Обновление .env

```bash
nano /home/petrick/nano_characters/.env
systemctl restart nano-characters
```

Или перезаписать с локальной машины:

```powershell
scp ".env.prod" petrick@38.180.200.88:/home/petrick/nano_characters/.env
ssh root@38.180.200.88 "systemctl restart nano-characters"
```
