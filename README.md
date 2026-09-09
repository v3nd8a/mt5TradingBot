# 🤖 TradingBot "Крон" — AI-powered MT5 Trading Bot

> **Локальный AI-бот для автоматической торговли на FOREX через MetaTrader 5.** Использует LSTM модель Kronos для предсказания свечей + Gemini API fallback для анализа.

---

## 🎯 Цель проекта

**MVP cycle**: `MT5 → анализ через Kronos → сигнал → ордер` — полностью автономный торгоющий бот.

### Архитектура MVP

```
┌─────────────┐    ┌──────────────┐    ┌──────────────┐    ┌───────────┐
│  MT5 API   │───▶ │  AI Engine  │───▶ │  Signal Proc│───▶ │Order Exec │
│ (candles)  │    │(Kronos+Gemini)│    │ (logic)     │    │ (MT5)     │
└─────────────┘    └──────────────┘    └──────────────┘    └───────────┘
                           │                      │                 │
                           ▼                      ▼                 ▼
                    ┌──────────────┐    ┌──────────────┐    ┌───────────┐
                    │  Portfolio   │    │ PostgreSQL   │    │Telegram bot│
                    │  Analytics   │    │ (history,    │    │(monitoring)│
                    │              │    │  signals)     │    │           │
                    └──────────────┘    └──────────────┘    └───────────┘
```

---

## 📦 Структура проекта

```
mt5TradingBot/
├── .env                       # Конфигурация (свои данные!)
├── .gitignore
├── docker-compose.yml         # Docker: PostgreSQL + pgAdmin
├── Dockerfile                 # Образ TradingBot
├── requirements.txt           # Зависимости Python
├── README.md                  # Этот файл
├── PLAN.md                    # План развития проекта

# === Core Modules (MVP) ===
├── main.py                    # Entry point (--demo, --bot, --analyze)
├── config/
│   ├── __init__.py
│   ├── settings.py            # pydantic-settings из .env
│   └── logging_config.py      # Файловый ротейтинг (logging)

├── connector/
│   ├── __init__.py
│   └── mt5.py                 # MT5 API: candles, positions, orders

├── engine/
│   ├── __init__.py
│   ├── models.py              # AI данных моделей (SignalType, CandleData)
│   └── ai.py                  # AI Engine: Kronos + Gemini + Technical Analysis

├── trader/
│   ├── __init__.py
│   ├── trading_loop.py        # Основной цикл торговли
│   └── order_executor.py      # Логика исполнения ордеров с SL/TP/risk

├── bot/
│   ├── __init__.py
│   └── bot.py                 # Telegram Bot: /status, /balance, /analyze

├── db/
│   ├── __init__.py
│   ├── schema.sql              # PostgreSQL DDL
│   ├── models.py               # SQLAlchemy модели
│   └── engine.py              # Движок БД + сессии

├── logs/                      # Логи (автоматически)
├── tests/
│   ├── __init__.py
│   └── test_settings.py       # Unit-тесты конфигурации
```

---

## 🚀 Быстрый старт

### 1. Установка зависимостей

```bash
# Виртуальное окружение (рекомендуется)
python -m venv .venv
.venv\Scripts\activate   # Windows
source .venv/bin/activate  # Linux/Mac

# Установка пакетов
pip install -r requirements.txt
```

### 2. Конфигурация `.env`

```bash
cp .env.example .env  # Если есть шаблон
```

Свои данные в `settings.py`:

| Секция | Переменная | Описание |
|--------|-----------|----------|
| MT5 | `MT5_LOGIN` | Логин MT5 аккаунта |
| MT5 | `MT5_PASSWORD` | Пароль MT5 |
| MT5 | `MT5_SERVER` | Сервер (XMGlobal-MT5 15 / AMarkets-Demo) |
| AI | `GEMINI_API_KEY` | Ключ Google Gemini |
| DB | `DB_DSN` | Connection string PostgreSQL |
| Bot | `BOT_TOKEN` | Токен Telegram бота |
| Bot | `ADMIN_ID` | Ваш Telegram ID |

### 3. Запуск PostgreSQL (Docker)

```bash
docker-compose up -d postgres
```

Или локальная установка:

```bash
# Windows
# Запустите PostgreSQL 16+ и создайте базу 'trading_db'
CREATE DATABASE trading_db;
```

### 4. Инициализация БД

```python
from db.engine import init_db, run_schema_migration

init_db()        # Создать таблицы из моделей
run_schema_migration()  # Или применить schema.sql
```

### 5. Запуск бота

```bash
# демо-реак (только чтение сигналов)
python main.py --demo

# с Telegram ботом
python main.py --bot --demo 

# анализ одного символа и выход из бота 
python main.py --analyze EURUSD

# обычный старт на реальном аккаунте!  
python main.py
```

---

## 📊 Команды Telegram бота

| Команда | Описание |
|---------|----------|
| `/start` | Начало работы с ботом | 
| `/status` | Статус бота (MT5, AI, символы) |
| `/balance` | Баланс, equity, маржа аккаунта MT5 |
| `/signals` | Последние 5 AI сигналов |
| `/analyze [symbol]` | Ручной анализ (AI prediction) |
| `/positions` | Открытые позиции MT5 |
| `/help` | Справка по командам |

---

## 🔒 Безопасность (P1)

```yaml
security:
  demo_mode      # "true" — только сигналы, ни ордеров (RECOMMENDED for testing!)
  rate_limit     # MAX_ORDERS_PER_MIN = 3
  fallback        # При падении Kronos → Gemini → Technical Analysis
  graceful_shutdown   # Ctrl+C / SIGTERM обработка
```

**ВНИМАНИЕ**: Всегда тестируйте на демо-счёте! 

---

## 📈 Этапы проекта (PLAN.md)

### ✅ MVP (M1-M4) — реализованы


### 🔄 Переходные этапы (P1-P4) — в процессе

#### P1: Безопасность
- [x] Demo mode flag
- [x] Rate limiting ордеров
- [x] Fallback при падении Kronos
- [ ] Шифрование чувствительных данных из .env  

#### P2: Аналитика  
- [x] Таблицы metrics в БД
- [ ] Генерация отчётов / CSV export
- [ ] Графики портфеля (matplotlib)

#### P3: Telegram бот — ✅ реализован
- [x] Команды /status, /balance, /signals, /analyze, /positions
- [ ] Уведомления о сделках в реальном времени  
- [ ] Ручной запуск анализа через `/manual <symbol> <direction>`

#### P4: Docker + Production — ✅ реализован
- [x] docker-compose для PostgreSQL
- [ ] systemd / Windows service файлы  
- [x] README.md документация

---

## 🛠️ Технический стек

| Компонент | Выбор |
|-----------|-------| 
| **MT5**  | MetaTrader5 Python пакет  |
| **AI**   | Kronos (локальная LSTM) + Gemini API fallback |
| **DB**   | PostgreSQL 16+ | 
| **ORM**  | SQLAlchemy 2.0 |
| **Бот**  | aiogram 3.x |
| **Конфиг**| pydantic-settings |  
| **Log**  | Python logging с файловым ротейтингом |

---

## 📋 Торговая логика

### Сигнал генерации (Technical Analysis)
1. RSI (OVERBOUGHT/OVERSOLD)
2. MACD (Bullish/Bearish cross) 
3. Bollinger Bands (bounce/reject)
4. Stochastic (K/D levels)
5. EMA/SMA crossovers
6. Volume confirmation

### Weighted Signal Combination
- 50% Technical Analysis (взвешенный голосующий алгоритм)
- 25% Kronos LSTM prediction  
- 25% Gemini API fallback analysis

### Risk Management
- `RISK_PER_TRADE_PCT` = 1% от баланса на сделку
- `DEFAULT_SL_PIPS` = Stop Loss в пипсах  
- `DEFAULT_TP_PIPS` = Take Profit в пипсах
- Максимум позиций: `MAX_POSITIONS = 3`

---

## ⚡ Запуск Docker (PostgreSQL)

```bash
# Поднять PostgreSQL
docker-compose up -d postgres

# Проверить здоровье БД
docker exec krons-trading-db pg_isready -U postgres

# Остановить 
docker-compose down  
```

---

## 📝 TODO (Планирование на будущие выпуски)

1. ~~Add more charting capabilities~~ → matplotlib integration for portfolio visuals
2. ~~Multiple pairs support~~ → config-driven pair list
3. ~~Web dashboard for monitoring~~ → optional FastAPI web interface (next release)  
4. Alert system via Webhooks / Push notifications
5. Backtesting module using historical data from DB

---

## ⚠️ Дисклеймер

> Этот софт используется на ваш страх и риск. Алгоритмическая торговля на FOREX несёт финансовые риски. **Обязательно тестируйте на ДЕМО** перед использованием реальных средств. Автор не несёт ответственности за финансовые потери.
> 
> **Всегда начинайте с `--demo` режима!**

---

## 📞 Контакты

- Автор разработки: [ваш ник]
- Исходный код: `mt5TradingBot`  
- Версия: 1.0.0 MVP
