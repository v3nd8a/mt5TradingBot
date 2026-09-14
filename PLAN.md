# 📋 План проекта TradingBot "Крон"

## MVP — минимальный работающий цикл

**Цель**: MT5 → анализ через Kronos → сигнал → ордер. Всё остальное потом.

### Этап M1: Основа MVP
- [x] **Структура проекта** — модули: `connector/` (MT5), `engine/` (Kronos AI), `trader/` (торговый цикл), `db/` (PostgreSQL схема), `config/`, `logs/`
- [x] **PostgreSQL MVP schema** — таблицы: `candles` (история OHLCV), `signals` (AI сигналы), `trades` (исполненные ордера), `portfolio` (текущий баланс и позиции)
- [x] **Конфигурация** — pydantic-settings из .env, базовое логирование в файлы

### Этап M2: MT5 Connector (ядро)
- [x] Подключение через `MetaTrader5` пакет
- [x] Загрузка исторических candles (OHLCV) для выбранного символа
- [x] Мониторинг текущих позиций и баланса
- [x] Отправка ордеров (buy/sell/close SL/TP)

### Этап M3: AI Engine + Kronos (ядро)
- [x] Интеграция **Kronos** — локальная модель для candle prediction
- [x] Предобработка сырых данных из MT5 в формат модели
- [x] Генерация сигнала: `BUY` / `SELL` / `HOLD` с confidence score
- [x] Простая cache/кэш последних предсказаний чтобы не перегружать модель

### Этап M4: Trading Loop (сборка MVP)
- [x] Периодический цикл (tick каждые N минут) — fetch candles → predict → signal → execute
- [x] Логика исполнения: только если confidence > threshold, проверка что уже нет позиции в ту же сторону
- [x] Запись всех сигналов и сделок в БД
- [x] Логирование всего в `logs/`

---

## ПЕРЕХОДНОЙ ЭТАП (после MVP)
*Можно добавить до запуска на реале*

### Этап P1: Безопасность
- [x] Проверка доступности MT5 терминала перед стартом
- [x] Rate limiting ордеров (не чаще X в минуту)
- [x] Фолбэк если Kronos упал — не торговать, писать в лог
- [x] Шифрование/разделение чувствительных данных из .env (config/security.py)

### Этап P2: Аналитика (средний приоритет)
- [x] Таблицы: `metrics` для статистики (P&L, win rate, drawdown, Sharpe)
- [x] Генерация отчётов в текстовом виде / CSV (analytics/reporter.py)
- [x] Простые графики портфеля (analytics/reporter.py)

### Этап P3: Telegram Bot (низкий приоритет)
- [x] Управление ботом через `/status`, `/balance`, `/analyze`
- [x] Уведомления о сделках и сигналах
- [x] Команда `/manual <symbol> <direction>` для ручного запуска анализа

### Этап P4: Деплой и production
- [x] Docker-compose для PostgreSQL
- [x] systemd / Windows service (start.bat)
- [x] README.md документация

---

## Технологический стек
- **MT5**: MetaTrader5 Python пакет (XMGlobal demo/real)
- **AI**: Kronos (https://github.com/shiyu-coder/Kronos) — локальная модель, Google Gemini fallback для анализа
- **DB**: PostgreSQL 16+
- **Бот**: aiogram 3.x
- **Конфиг**: pydantic-settings
- **Логирование**: Python logging с файловым ротейтингом

## Состояние .env данных (из текущего файла)
- MT5: логин 401397663, сервер XMGlobal-MT5 15 (реал), демо AMarkets
- PostgreSQL: localhost:5432, база trading_db
- Gemini API ключ для fallback анализа
