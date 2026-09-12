# MT5 Trading Bot — Project Knowledge Graph

## Entry Point
- **main.py** → `asyncio.run(main())` guarded by `if __name__ == '__main__'`
- Parses CLI args: `--demo`, `--bot`, `-s/--symbol`, `--analyze`
- Three modes: Telegram bot, symbol analysis, full trading loop

---

## Module Map

### config (settings, logging_config)
- **Settings** (pydantic-settings): 28 fields — MT5 creds, Gemini API key, DB DSN, trading params (confidence threshold 0.65, risk 1%, SL/TP pips 50/100), bot tokens, cache TTL (300s, max 20 entries)
- **settings**: singleton instantiated at import time from .env
- **setup_logging()**: console + RotatingFileHandler per module
- **get_logger(name)**: named logger factory

### connector (mt5.py)
- **MT5Connector**: wrapper around MetaTrader5 Python API
  - Lifecycle: `connect()`, `disconnect()`, `is_connected()`
  - Data: `get_candles(symbol, timeframe, count)`, `save_candles_to_db(df)` (stubbed)
  - Account: `get_account_info()`, `get_positions(symbol)`, `get_pending_orders(symbol)`
  - Execution: `send_market_order(symbol, direction, volume, sl, tp)`, `close_all_positions(symbol)`
- **get_mt5()**: singleton accessor

### engine (ai.py, models.py)
- **models.py** — dataclasses/enums:
  - `SignalType`: BUY/SELL/HOLD
  - `PredictionResult` (dataclass): signal, confidence, reason, target_price, stop_loss, take_profit; `.is_actionable` property
  - `TechnicalIndicators` (dataclass): ~20 fields — SMA(20/50/200), EMA(12/26), RSI-14, MACD, Bollinger Bands, ATR, Volume ratio, Stochastic
  - `CandleData` (dataclass): OHLCV with `.body`, `.is_bullish`, `.is_doji` properties
- **ai.py** — AI analysis engine:
  - `TechnicalAnalysis.compute(df, symbol)` → TechnicalIndicators (static methods for RSI, MACD, SMA/EMA, Bollinger, ATR, Volume, Stochastic)
  - `PredictionCache`: LRU cache with per-entry TTL (default 5 min, 20 max)
  - `AIEngine` (core): weighted voting from technical analysis + optional Kronos LSTM + optional Gemini API fallback
    - `analyze(candles_df, symbol, use_kronos, use_gemini)` → PredictionResult
    - `_technical_analysis_only(indicators)` → weighted vote BUY/SELL/HOLD
    - `_analyze_with_gemini(symbol, indicators, candles)` → sends to Gemini API
    - `_predict_with_kronos(df)` → LSTM prediction (placeholder)
    - `_combine_signals(tech, kronos, gemini)` → weighted: tech=0.5, kronos=0.25, gemini=0.25
  - **Bug**: `_calc_target()` expects 2 params but called with 1 from `_technical_analysis_only` — will raise TypeError at runtime

### trader (order_executor.py, trading_loop.py)
- **OrderRequest** (dataclass): symbol, direction, volume, sl_price, tp_price, reason
- **OrderExecutor**: order execution with rate limiting, volume calc based on risk%, SL/TP planning, duplicate position avoidance
  - `plan_order(signal, symbol)` → OrderRequest or None
  - `execute(order_request)` → MT5 response dict
  - `close_position(ticket, symbol)`
- **TradingLoop** (main orchestrator):
  - `_trading_cycle()`: connect → load candles → AI analyze → plan order → execute → save to DB
  - Saves: Signal, Trade, PortfolioSnapshot, Metric records
  - Singleton via `get_trading_loop()`

### bot (bot.py)
- **TelegramBotHandler**: aiogram-based Telegram bot
  - Lifecycle: `start()`, `stop()` — creates Bot + Dispatcher, registers handlers
  - Commands: /start, /status, /balance, /analyze, /positions
  - Lazy imports of trader/connector/engine inside handlers
  - Singleton via `get_bot_token()`
- **AdminStates**: FSM states group (only WAITING_SYMBOL defined)
- **Bug**: __init__.py imports `TelegramBot` from bot.bot but class is named `TelegramBotHandler` — ImportError at runtime

### db (models.py, engine.py, schema.sql)
- **ORM Models** (SQLAlchemy declarative):
  - `Candle`: OHLCV data, UNIQUE(symbol, timeframe, open_time)
  - `Signal`: AI signal with confidence (0-1), one-to-many to Trade
  - `Trade`: executed trade linked to Signal, tracks SL/TP/profit/commission/swap
  - `PortfolioSnapshot`: point-in-time balance/equity/margin capture
  - `Metric`: analytics metric, UNIQUE(metric_name, period_start)
- **engine.py**: sync engine (Alembic), async engine (runtime), `get_db_session()` context manager
- **schema.sql**: raw DDL for all tables with indexes and dedup migration

### tests (test_settings.py)
- TestSettings: 4 tests for MT5 creds, Gemini key, DB DSN format, risk params
- TestTradingConfig: 2 tests for confidence threshold range, MAX_POSITIONS minimum
- **Note**: line 25 references `DEFAULT_TP_PIPS` bare instead of `settings.DEFAULT_TP_PIPS` — likely bug

---

## Data Flow (Trading Cycle)
```
main.py → TradingLoop.start()
    ↓
[1] MT5Connector.connect() → connect to MT5 terminal
[2] MT5Connector.get_candles(symbol, H1, 100+) → pandas DataFrame
[3] AIEngine.analyze(candles_df, symbol)
    ├── TechnicalAnalysis.compute(df, symbol) → TechnicalIndicators
    ├── [optional] Kronos LSTM prediction (placeholder — not implemented)
    └── [optional] Gemini API analysis (if USE_GEMINI_FALLBACK)
    ↓ weighted combine (tech=0.5, kronos=0.25, gemini=0.25)
[4] OrderExecutor.plan_order(signal, symbol) → OrderRequest or None
[5] OrderExecutor.execute(order_request) → MT5 API order response
[6] db save: Signal, Trade, PortfolioSnapshot via get_db_session()
```

## Cross-Module Dependencies (Internal)
| Module | Depends On |
|--------|-----------|
| main.py | config.settings, config.logging_config, trader.trading_loop.TradingLoop, bot.bot.TelegramBotHandler |
| bot | config.settings, trader.trading_loop, connector.mt5, engine.ai |
| connector | config.settings, db.models.Candle |
| engine | config.settings (cache/risk params), engine.models |
| trader | config.settings, connector.mt5.MT5Connector, engine.ai.AIEngine, engine.models, db.engine, db.models |
| db | config.settings (DSN) |

## External Dependencies
- **Trading**: MetaTrader5 >= 5.0.45
- **Config**: pydantic-settings >= 2.0.0, python-dotenv >= 1.0.0
- **DB**: SQLAlchemy >= 2.0.0, psycopg2-binary >= 2.9.9, asyncpg
- **AI**: google-generativeai >= 0.3.0, torch >= 2.0.0, transformers >= 4.30.0
- **Compute**: numpy >= 1.24.0, pandas >= 2.0.0
- **Bot**: aiogram >= 3.0.0
- **Utils**: loguru >= 0.7.0, aiohttp >= 3.9.0, matplotlib >= 3.8.0, tabulate >= 0.9.0

## Known Bugs
1. `_calc_target()` in engine/ai.py line 474: expects `(self, direction, indicators)` but called with only `(self, direction)` from `_technical_analysis_only` — TypeError at runtime
2. bot/__init__.py imports `TelegramBot` but class is named `TelegramBotHandler` — ImportError
3. `get_ai_engine()` in engine/ai.py: never assigns to `_ai_engine`, so no singleton behavior — creates new instance each call
4. tests/test_settings.py line 25: references bare `DEFAULT_TP_PIPS` instead of `settings.DEFAULT_TP_PIPS`
