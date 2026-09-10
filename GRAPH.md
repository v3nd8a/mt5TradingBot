# Project Dependency Graph

## Modules

### config/settings.py — Central config (pydantic-settings)
- **Fields**: MT5 login/server/password, AI params, DB DSN, trading/risk params, bot tokens, logging settings (~25 fields)
- **Singleton**: `settings = Settings()`
- **Also exports**: `BASE_DIR`, `LOGS_DIR`, `DB_SCHEMA_PATH`
- ⚠️ Imported by ALL other modules

### config/logging_config.py
- Functions: `setup_logging() -> Logger`, `get_logger(name) -> Logger`
- Depends on: `config.settings` (LOG_LEVEL, LOGS_DIR, etc.)

### main.py — Entry point
- `parse_args()` → CLI flags (--demo, --bot, -s/--symbol, --analyze)
- `main()` → wiring: setup_logging + TradingLoop() + TelegramBotHandler()
- Depends on: logging_config, settings, trader.trading_loop, bot.bot

### engine/models.py — DTOs + enums
- `SignalType(str, Enum)` → BUY / SELL / HOLD
- `PredictionResult(dataclass)` → signal, confidence, reason, target_price, sl, tp; `.is_actionable`
- `TechnicalIndicators(dataclass)` → 19 fields (SMA, EMA, RSI, MACD, ATR, etc.)
- `CandleData(dataclass)` → timestamp, OHLCV + props: body, is_bullish, is_doji

### engine/ai.py — Analysis engine
- `TechnicalAnalysis` — static class; `.compute(df, symbol) -> TechnicalIndicators`; private `_rsi()`, `_atr()`
- `PredictionCache` — LRU+TTL cache via OrderedDict
- `AIEngine` — `.analyze(candles, symbol, use_kronos, use_gemini) -> PredictionResult`
  - internals: `_technical_analysis_only()`, `_combine_signals()`, `_calc_target()`
  - ML backends: `_predict_with_kronos()` (LSTM), `_analyze_with_gemini()` + prompt parse
- Singleton: `get_ai_engine() -> AIEngine`
- Depends on: engine.models, config.settings, numpy, pandas

### db/engine.py — SQLAlchemy setup
- Variables: `sync_engine`, `async_engine`, `AsyncSessionLocal`
- Functions: `init_db()`, `run_schema_migration()`, `get_db_session() async`, `health_check() -> bool`
- Depends on: config.settings (DB_DSN, DB_SCHEMA_PATH), db.models.Base

### db/models.py — ORM tables
- `Base(DeclarativeBase)`
- Enums: `SignalType(BUY/SELL/HOLD)`, `OrderDirection`, `OrderStatus`
- Tables: `Candle`, `Signal` (→ trades relationship), `Trade` (← signal FK), `PortfolioSnapshot`, `Metric`

### connector/mt5.py — MT5 API wrapper
- Class `MT5Connector`: connect, disconnect, is_connected, last_error
  - Candles: get_candles(), save_candles_to_db(df, symbol, tf)
  - Account: get_account_info(), get_positions(), get_pending_orders()
  - Orders: send_market_order(...), close_all_positions()
- Singleton: `get_mt5() -> MT5Connector`
- Depends on: config.settings, db.models.CableModel, db.engine.sync_engine, MetaTrader5 (external), pandas

### trader/order_executor.py — Order execution logic
- Dataclass: `OrderRequest(symbol, direction, volume, sl?, tp?, reason)`
- Class `OrderExecutor(mt5)`: can_trade(prop), _check_rate_limit(), _calculate_volume(), plan_order(signal), _get_current_price(), execute(order), close_position()
- Singleton: `get_executor(mt5?) -> OrderExecutor`
- Depends on: config.settings, connector.mt5.MT5Connector, engine.models.PredictionResult/SignalType, MetaTrader5 (inline)

### trader/trading_loop.py — Async orchestrator (top of hierarchy)
- Class `TradingLoop`: __init__(mt5+ai+executor), start(async), _trading_cycle(async), stop(), status(prop)
  - wiring inside start(): DB init/migration/health + MT5 connect + candles fetch + portfolio snapshot + signal handlers
  - _trading_cycle(): reconnect → candles → AI.analyze() → save_signal → plan_order → execute → save_trade → save_portfolio_snapshot
- Singleton: `get_trading_loop() -> TradingLoop`
- Depends on: config.settings, connector.mt5.MT5Connector, engine.ai.AIEngine, trader.order_executor, db.engine + db.models

### bot/bot.py — Telegram monitoring/control interface
- Class `AdminStates(StatesGroup)`: WAITING_SYMBOL
- Class `TelegramBotHandler`: start(), stop(), _setup_handlers(), send_notification()
- Singleton: `get_bot_token() -> TelegramBotHandler`
- Depends on: config.settings, trader.trading_loop, connector.mt5.MT5Connector, engine.ai.AIEngine, aiogram (external)

## Dependency Edges (compact)

```
main.py
  ├── logging_config.setup_logging()   → config/settings
  ├── settings                         → config/settings
  ├── TradingLoop()                    → mt5 + ai + order_executor + db
  └── get_bot_token().start()          → bot.telegram + aiogram

config/settings.py  ←⬅  ALL modules (universal dep)

engine/models.py ──▶ engine/ai.py   (PredictionResult, SignalType, TechnicalIndicators, CandleData)
                      │
                      └──▶ db/models.py  (SignalType duplicate — not imported)

engine/ai.py     ──▶ config/settings  (cache/risk params)
connector/mt5.py ──▶ db/engine       (save_candles_to_db uses sync_engine)
connector/mt5.py ──▶ db/models.Candle(CableModel)
                   ──▶ MetaTrader5    (external pkg)

trader/order_executor.py  ──▶ connector.mt5.MT5Connector   (constructor injection)
                            ──▶ engine.models.PredictionResult, SignalType
                            ──▶ config.settings

trader/trading_loop.py ← orchestrator (top of hierarchy)
  ├── MT5Connector()            → connector/mt5
  ├── AIEngine()                → engine/ai
  ├── OrderExecutor(mt5)        → trader/order_executor
  ├── DB init/migration/health  → db/engine + db/models
  └── _trading_cycle: candles→AI.analyze→plan→execute→persist

db/engine.py ← config/settings (DSN) + db/models.Base
db/models.py ← standalone (SQLAlchemy models)
               SignalType duplicate vs engine/models.SignalType
```

## Architecture Notes
- `config/settings.py` is the universal leaf dependency — no module depends on it from within
- `trading_loop.py` is the top-level orchestrator; all subsystems are its leaves
- `SignalType` defined in both `engine/models.py` and `db/models.py` — consolidation recommended
- `connector/mt5.py` writes to DB (`save_candles_to_db`) → creates edge connector→db
