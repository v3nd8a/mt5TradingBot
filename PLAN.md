# 📋 План проекта TradingBot "Крон"

## MVP — минимальный работающий цикл

**Цель**: MT5 → анализ через Kronos → сигнал → ордер. Всё остальное потом.

### Этап M1: Основа MVP
- [ ] **Структура проекта** — модули: `connector/` (MT5), `engine/` (Kronos AI), `trader/` (торговый цикл), `db/` (PostgreSQL схема), `config/`, `logs/`
- [ ] **PostgreSQL MVP schema** — таблицы: `candles` (история OHLCV), `signals` (AI сигналы), `trades` (исполненные ордера), `portfolio` (текущий баланс и позиции)
- [ ] **Конфигурация** — pydantic-settings из .env, базовое логирование в файлы

### Этап M2: MT5 Connector (ядро)
- [ ] Подключение через `MetaTrader5` пакет
- [ ] Загрузка исторических candles (OHLCV) для выбранного символа
- [ ] Мониторинг текущих позиций и баланса
- [ ] Отправка ордеров (buy/sell/close SL/TP)

### Этап M3: AI Engine + Kronos (ядро)
- [ ] Интеграция **Kronos** — локальная модель для candle prediction
- [ ] Предобработка сырых данных из MT5 в формат модели
- [ ] Генерация сигнала: `BUY` / `SELL` / `HOLD` с confidence score
- [ ] Простая cache/кэш последних предсказаний чтобы не перегружать модель

### Этап M4: Trading Loop (сборка MVP)
- [ ] Периодический цикл (tick каждые N минут) — fetch candles → predict → signal → execute
- [ ] Логика исполнения: только если confidence > threshold, проверка что уже нет позиции в ту же сторону
- [ ] Запись всех сигналов и сделок в БД
- [ ] Логирование всего в `logs/`

---

## ПЕРЕХОДНОЙ ЭТАП (после MVP)
*Можно добавить до запуска на реале*

### Этап P1: Безопасность
- [ ] Проверка доступности MT5 терминала перед стартом
- [ ] Rate limiting ордеров (не чаще X в минуту)
- [ ] Фолбэк если Kronos упал — не торговать, писать в лог
- [ ] Шифрование/разделение чувствительных данных из .env

### Этап P2: Аналитика (средний приоритет)
- [ ] Таблицы: `metrics` для статистики (P&L, win rate, drawdown, Sharpe)
- [ ] Генерация отчётов в текстовом виде / CSV
- [ ] Простые графики портфеля

### Этап P3: Telegram Bot (низкий приоритет)
- [ ] Управление ботом через `/status`, `/balance`, `/analyze`
- [ ] Уведомления о сделках и сигналах
- [ ] Команда `/manual <symbol> <direction>` для ручного запуска анализа

### Этап P4: Деплой и production
- [ ] Docker-compose для PostgreSQL
- [ ] systemd / Windows service
- [ ] README.md документация

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
