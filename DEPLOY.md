# 🚀 TradingBot "Крон" — Руководство по деплою на Linux сервер

## Оглавление
1. [Архитектура](#архитектура)
2. [Требования к серверу](#требования-к-серверу)
3. [Подготовка (пошагово)](#подготовка-пошагово)
4. [Деплой на сервер](#деплой-на-сервер)
5. [GitHub Actions CI/CD](#github-actions-cicd)
6. [Управление ботом](#управление-ботом)
7. [Мониторинг и отладка](#мониторинг-и-отладка)
8. [FAQ и решение проблем](#faq-и-решение-проблем)

---

## Архитектура

```
┌─────────────────── Linux Server (VPS/VDS) ───────────────────┐
│                                                               │
│  ┌─────────────── Docker Container: mt5-bot ───────────────┐  │
│  │                                                         │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │  supervisord (управляет всеми процессами)        │   │  │
│  │  └──────────┬──────────────┬────────────────────────┘   │  │
│  │             │              │                             │  │
│  │  ┌──────────▼─────┐  ┌────▼────────────────────────┐   │  │
│  │  │  Xvfb :99      │  │  MT5 Terminal (Wine)        │   │  │
│  │  │  (virtual      │  │  + RPyC Server (port 18812) │   │  │
│  │  │   display)     │  │  + AutoTrading = ON         │   │  │
│  │  └────────────────┘  └──────────▲──────────────────┘   │  │
│  │                                 │ RPyC                  │  │
│  │  ┌──────────────────────────────┴──────────────────┐   │  │
│  │  │  Python Trading Bot (main.py)                   │   │  │
│  │  │  - Kronos/Kairos AI предикторы                  │   │  │
│  │  │  - MT5 Bridge (connector/mt5_bridge.py)         │   │  │
│  │  │  - Telegram Bot (опционально)                   │   │  │
│  │  └──────────────────────────────────────────────────┘   │  │
│  └─────────────────────────────────────────────────────────┘  │
│                              │                                │
│  ┌───────────────────────────▼─────────────────────────────┐  │
│  │  Docker Container: postgres                             │  │
│  │  PostgreSQL 16 (trading_db)                             │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

**Как это работает:**
- **Wine** запускает `terminal64.exe` (MetaTrader 5) в headless-режиме на Linux
- **Xvfb** создаёт виртуальный дисплей для Wine (MT5 требует GUI)
- **RPyC Server** — мост между Windows MT5 API и Linux Python
- **mt5_bridge.py** автоматически определяет ОС:
  - Windows → нативный `MetaTrader5` пакет
  - Linux/Docker → RPyC мост к Wine MT5
- **AutoTrading** включается автоматически через `common.ini` при старте

---

## Требования к серверу

| Параметр | Минимум | Рекомендуется |
|----------|---------|---------------|
| **CPU** | 2 ядра | 4 ядра |
| **RAM** | 4 GB | 8 GB |
| **Диск** | 30 GB SSD | 50 GB SSD |
| **ОС** | Ubuntu 22.04 LTS | Ubuntu 22.04/24.04 LTS |
| **Arch** | x86_64 (**обязательно!**) | x86_64 |

> [!CAUTION]
> **ARM серверы НЕ поддерживаются!** (AWS Graviton, Apple Silicon и т.д.)
> Wine и MT5 требуют x86_64 архитектуру.

> [!IMPORTANT]
> **Рекомендованные хостинги (VPS/VDS):**
> - Hetzner Cloud (CX32 — €7.50/мес, Германия)
> - Contabo VPS (от €6/мес)
> - DigitalOcean (от $24/мес, 4GB RAM)
> - Vultr ($24/мес, 4GB RAM)
> - TimeWeb (от 500₽/мес, Россия)

---

## Подготовка (пошагово)

### Шаг 1: Арендовать VPS/VDS сервер

1. Зарегистрируйтесь на любом хостинге (Hetzner/Contabo/другой)
2. Создайте сервер с **Ubuntu 22.04 LTS x86_64**, минимум 4 GB RAM
3. Запишите **IP адрес сервера** и **root пароль** (или SSH ключ)

### Шаг 2: Настроить SSH доступ

```bash
# На СВОЕЙ машине (Windows — в PowerShell/Git Bash):
# Генерируем SSH ключ (если нет)
ssh-keygen -t ed25519 -C "tradingbot-deploy"

# Копируем ключ на сервер
ssh-copy-id -i ~/.ssh/id_ed25519 root@ВАШ_IP_СЕРВЕРА

# Проверяем подключение
ssh root@ВАШ_IP_СЕРВЕРА
```

### Шаг 3: Настроить сервер

```bash
# Вариант А: Через deploy.sh (автоматически)
# Сначала задайте IP сервера:
export DEPLOY_HOST=ВАШ_IP_СЕРВЕРА
export DEPLOY_USER=root
export DEPLOY_SSH_KEY=~/.ssh/id_ed25519

# Запускаем настройку:
bash deploy.sh --setup
```

Или **вручную** по SSH на сервере:

```bash
ssh root@ВАШ_IP_СЕРВЕРА

# Обновление системы
apt update && apt upgrade -y

# Установка Docker
curl -fsSL https://get.docker.com | sh
systemctl enable docker && systemctl start docker

# Установка Docker Compose
apt install -y docker-compose-plugin

# Проверка
docker --version
docker compose version

# Создание swap (если RAM < 8GB)
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# Создание директории
mkdir -p /opt/tradingbot
```

### Шаг 4: Подготовить .env файл

```bash
# На СВОЁМ компьютере, в корне проекта:
# Убедитесь что .env заполнен правильно!

# Проверьте критичные поля:
# - MT5_LOGIN / MT5_PASSWORD / MT5_SERVER (или демо-версии)
# - BOT_TOKEN (Telegram бот)
# - ADMIN_ID (ваш Telegram ID)
# - DB_PASS (пароль БД)
```

> [!WARNING]
> **НЕ коммитьте .env в Git!** Он содержит пароли.
> Файл `.env` уже в `.gitignore`.

### Шаг 5: Загрузить проект на GitHub

```bash
# На СВОЁМ компьютере:
cd путь/к/mt5TradingBot

# Инициализация git (если ещё нет)
git init
git remote add origin https://github.com/ВАШ_USERNAME/mt5TradingBot.git

# Первый коммит
git add -A
git commit -m "feat: add Docker deployment infrastructure"
git push -u origin main
```

---

## Деплой на сервер

### Вариант А: Через deploy.sh (рекомендуется для первого раза)

```bash
# Задаём переменные
export DEPLOY_HOST=ВАШ_IP_СЕРВЕРА
export DEPLOY_USER=root
export DEPLOY_SSH_KEY=~/.ssh/id_ed25519

# Полный деплой
bash deploy.sh
```

### Вариант Б: Вручную через SSH

```bash
# 1. Клонируем репозиторий на сервер
ssh root@ВАШ_IP

cd /opt/tradingbot
git clone https://github.com/ВАШ_USERNAME/mt5TradingBot.git app
cd app

# 2. Создаём .env
nano .env
# Вставьте содержимое вашего .env файла

# 3. Собираем и запускаем
docker compose build   # ~15-30 минут при первой сборке!
docker compose up -d

# 4. Проверяем
docker compose ps
docker compose logs -f mt5-bot
```

### Вариант В: Через GitHub Actions (автоматически)

См. раздел [GitHub Actions CI/CD](#github-actions-cicd) ниже.

---

## GitHub Actions CI/CD

### Настройка Secrets

Идём в GitHub → Settings → Secrets and variables → Actions → New repository secret:

| Secret | Значение | Пример |
|--------|----------|--------|
| `DEPLOY_HOST` | IP адрес сервера | `185.123.45.67` |
| `DEPLOY_USER` | SSH пользователь | `root` |
| `DEPLOY_SSH_KEY` | Содержимое SSH приватного ключа | `-----BEGIN OPENSSH...` |
| `DEPLOY_PORT` | Порт SSH (если не 22) | `22` |

```bash
# Получить содержимое SSH ключа для GitHub Secret:
cat ~/.ssh/id_ed25519
# Скопируйте ВСЁ содержимое (включая BEGIN/END строки)
```

### Настройка Environment

1. GitHub → Settings → Environments → New environment → `production`
2. Добавьте protection rules (опционально):
   - Required reviewers
   - Wait timer (5 минут — чтобы успеть отменить)

### Как работает CI/CD

```
Push to main → Lint & Test → Build Docker Image → Deploy to Server
       ↓              ↓               ↓                    ↓
   Trigger       Python 3.11      GHCR Push         SSH + Compose
```

**При каждом пуше в `main`:**
1. ✅ Линтинг кода (flake8)
2. ✅ Запуск тестов (pytest)
3. 🐳 Сборка Docker образа → GitHub Container Registry
4. 🚀 Деплой на сервер через SSH

---

## Управление ботом

### Команды deploy.sh

```bash
# Показать статус контейнеров
bash deploy.sh --status

# Показать логи бота
bash deploy.sh --logs

# Показать логи PostgreSQL
bash deploy.sh --logs postgres

# Перезапустить бота
bash deploy.sh --restart

# Остановить всё
bash deploy.sh --stop

# Обновить код (без пересборки Docker)
bash deploy.sh --update
```

### Команды Docker (на сервере)

```bash
ssh root@ВАШ_IP
cd /opt/tradingbot/app

# Статус
docker compose ps

# Логи в реальном времени
docker compose logs -f mt5-bot

# Перезапуск только бота
docker compose restart mt5-bot

# Пересборка после изменений
docker compose build mt5-bot && docker compose up -d mt5-bot

# Полная остановка
docker compose down

# Запуск с pgAdmin для мониторинга БД
docker compose --profile monitoring up -d

# Зайти в контейнер (для отладки)
docker compose exec mt5-bot bash

# Проверить MT5 подключение
docker compose exec mt5-bot python3 docker/healthcheck.py
```

---

## Мониторинг и отладка

### Просмотр логов

```bash
# На сервере:
# Логи бота
docker compose logs -f --tail=50 mt5-bot

# Или напрямую из volume:
docker compose exec mt5-bot cat /app/logs/tradingbot.log
docker compose exec mt5-bot cat /app/logs/mt5_terminal.log

# Логи supervisord (все процессы)
docker compose exec mt5-bot cat /app/logs/supervisord.log
```

### Telegram уведомления

Бот запускается с флагом `--bot` и отправляет уведомления о сделках в Telegram.
Убедитесь что `BOT_TOKEN` и `ADMIN_ID` заданы в `.env`.

### pgAdmin

```bash
# Запуск с pgAdmin
docker compose --profile monitoring up -d

# Доступ: http://ВАШ_IP:5050
# Email: admin@kronstrading.com (или что в PGADMIN_EMAIL)
# Password: admin123 (или что в PGADMIN_PASSWORD)
```

### Health Check RPyC Bridge

```bash
# На сервере:
docker compose exec mt5-bot python3 docker/healthcheck.py
```

---

## FAQ и решение проблем

### ❓ MT5 не подключается к брокеру

```bash
# Проверяем логи MT5 терминала
docker compose exec mt5-bot cat /app/logs/mt5_terminal.log

# Проверяем Wine логи
docker compose exec mt5-bot cat /app/logs/mt5_terminal_err.log

# Частые причины:
# 1. Неправильный MT5_SERVER в .env
# 2. Брокер блокирует IP вашего VPS
# 3. Нужно первый раз залогиниться вручную через VNC
```

### ❓ Как залогиниться в MT5 вручную (первый раз)?

Некоторые брокеры требуют ручного первого логина. В этом случае:

```bash
# Добавьте noVNC для визуального доступа:
# В docker-compose.yml добавьте порт:
#   ports:
#     - "6901:6901"

# Или используйте отдельный VNC контейнер:
docker run -d --network krons-net \
  -p 6901:6901 \
  --name mt5-vnc \
  hudsonventura/mt5:latest

# Откройте в браузере: http://ВАШ_IP:6901
# Залогиньтесь в MT5, включите AlgoTrading
# После этого остановите VNC: docker stop mt5-vnc && docker rm mt5-vnc
```

### ❓ AutoTrading не включается

```bash
# Проверяем конфиг
docker compose exec mt5-bot cat "/root/.wine/drive_c/Program Files/MetaTrader 5/config/common.ini"

# Должно быть:
# [Common]
# AutoTrading=1
# AutoTradingGlobal=1

# Если нет — перезапустите контейнер:
docker compose restart mt5-bot
```

### ❓ RPyC bridge не отвечает

```bash
# Проверяем порт
docker compose exec mt5-bot ss -tlnp | grep 18812

# Перезапуск MT5 процессов внутри контейнера
docker compose exec mt5-bot supervisorctl restart mt5-terminal

# Полный перезапуск
docker compose restart mt5-bot
```

### ❓ Нехватка памяти

```bash
# Проверка
free -h

# Добавить swap
fallocate -l 4G /swapfile2
chmod 600 /swapfile2
mkswap /swapfile2 && swapon /swapfile2

# Уменьшить лимит памяти Docker в docker-compose.yml:
# deploy.resources.limits.memory: 2G
```

### ❓ Образ слишком долго собирается

Первая сборка Docker образа занимает **15-30 минут** из-за:
- Установки Wine
- Скачивания Windows Python
- Установки MT5

Последующие пересборки используют кэш и занимают 2-5 минут.

> [!TIP]
> **Собирайте образ НА СЕРВЕРЕ**, а не локально. Загружать образ размером 5+ GB через интернет дольше.

### ❓ Как обновить только код бота (без пересборки MT5)?

```bash
bash deploy.sh --update
# Это пересоберёт только слой с Python-кодом (быстро)
```

### ❓ Как запустить в демо-режиме?

```bash
# В .env:
MT5_DEMO_MODE=true
MT5_DEMO_LOGIN=ваш_демо_логин
MT5_DEMO_PASSWORD=ваш_демо_пароль
MT5_DEMO_SERVER=AMarkets-Demo

# Или добавьте --simulate для бумажной торговли:
# В docker/supervisord.conf измените command для tradingbot:
# command=python3 -m main --bot --simulate
```

---

## Структура файлов деплоя

```
mt5TradingBot/
├── .github/workflows/
│   └── deploy.yml              # GitHub Actions CI/CD
├── docker/
│   ├── mt5_rpyc_server.py      # RPyC мост (работает в Wine Python)
│   ├── mt5_startup.sh          # Скрипт запуска MT5 + AutoTrading
│   ├── supervisord.conf        # Управление процессами
│   ├── docker-compose.dev.yml  # Dev override (только БД)
│   └── healthcheck.py          # Проверка здоровья
├── connector/
│   ├── mt5.py                  # Коннектор (обновлён для bridge)
│   └── mt5_bridge.py           # RPyC bridge (Linux ↔ Wine MT5)
├── Dockerfile                  # Multi-stage: Wine + MT5 + Python
├── docker-compose.yml          # Production compose
├── .dockerignore               # Исключения для Docker
├── requirements.docker.txt     # Зависимости для Linux (без MetaTrader5)
├── deploy.sh                   # Скрипт деплоя
└── .env.example                # Шаблон переменных окружения
```
