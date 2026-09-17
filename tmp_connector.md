# MT5 Connector Analysis

## Files Analyzed

- `connector/mt5.py` (424 lines)
- `connector/__init__.py` (3 lines)

---

## 1. Classes

### `MT5Connector`

**Fields:**
- `_initialized: bool` — tracks whether connect() succeeded
- `_last_error: Optional[str]` — stores the most recent error message

**Methods:**

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `()` | Initializes `_initialized=False`, `_last_error=None` |
| `connect` | `(self) -> bool` | Initializes MT5, logs in with credentials from settings, verifies account info |
| `disconnect` | `(self)` | Calls `mt5_module.shutdown()`, resets `_initialized` |
| `get_candles` | `(symbol: str=None, timeframe: str="H1", count: int=300, since: datetime=None) -> pd.DataFrame` | Fetches OHLCV candles via `copy_rates_range` or `copy_rates_from_pos` |
| `save_candles_to_db` | `(df: pd.DataFrame, symbol: str, timeframe: str) -> int` | Upserts candles to PostgreSQL using SQLAlchemy + `insert().on_conflict_do_update()` |
| `get_account_info` | `(self) -> Optional[dict]` | Returns account info (login, balance, equity, margin, etc.) |
| `get_positions` | `(symbol: str=None) -> list[dict]` | Returns active positions with ticket, symbol, type, volume, SL/TP, profit |
| `get_pending_orders` | `(symbol: str=None) -> list[dict]` | Returns pending orders with ticket, type, volume, price, SL/TP |
| `send_market_order` | `(symbol: str, direction: str, volume: float, sl_price: float=None, tp_price: float=None, comment: str="", deviation: int=20) -> Optional[dict]` | Sends market order via `order_send()` with TRADE_ACTION_DEAL; supports SL/TP |
| `close_all_positions` | `(symbol: str=None) -> int` | Closes all positions by sending opposite-market orders; returns count of closed |

**Properties:**
- `is_connected: bool` — returns `_initialized`
- `last_error: Optional[str]` — returns `_last_error`

**Static methods:**
- `_tf_minutes(tf: str) -> int` — maps timeframe string to minutes (M1=1, M5=5, M15=15, M30=30, H1=60, H4=240, D1=1440)

### `MT5Connector` in `__init__.py`

- Exports only `MT5Connector` via `__all__ = ["MT5Connector"]`. No class wrapping or additional logic.

---

## 2. Key Functions (Module-level)

| Function | Signature | Description |
|----------|-----------|-------------|
| `get_mt5` | `() -> MT5Connector` | Module-level singleton accessor — creates instance on first call, returns same one thereafter |

---

## 3. Singleton Pattern

**Implementation: lazy module-global variable**

```python
_mt5_instance = None

def get_mt5() -> MT5Connector:
    global _mt5_instance
    if _mt5_instance is None:
        _mt5_instance = MT5Connector()
    return _mt5_instance
```

- Pattern name: **Module-level lazy singleton**.
- No thread safety (`global` without a lock).
- Singleton lives at module scope in `connector/mt5.py`.
- Accessed via `get_mt5()` or directly by instantiating `MT5Connector()`.

---

## 4. External Dependencies

| Dependency | Usage |
|------------|-------|
| `MetaTrader5` (pip package) | Core API: `initialize()`, `login()`, `shutdown()`, `copy_rates_*()`, `positions_get()`, `orders_get()`, `symbol_info()`, `order_send()`, constants like `TIMEFRAME_*`, `ORDER_TYPE_*`, `TRADE_ACTION_DEAL`, `ORDER_TIME_GTC`, `ORDER_FILLING_IOC`, `TRADE_RETCODE_DONE` |
| `pandas` (pd.DataFrame) | Candle data returned as DataFrame; conversion from MT5 numpy array via `pd.DataFrame(rates)`; datetime parsing with `pd.to_datetime(..., unit="s")` |
| `sqlalchemy.dialects.postgresql.insert` (`pg_insert`) | Upsert logic in `save_candles_to_db` using PostgreSQL conflict resolution |
| Project imports: `config.settings.settings` | Environment-based settings (.env) for MT5 credentials, demo mode flag, default symbol |
| Project imports: `db.models.Candle`, `db.engine.sync_engine` | SQLAlchemy ORM model and sync engine for PostgreSQL persistence |

---

## 5. Connection Flow (Credentials -> Initialization)

```
MT5Connector.connect()
  |
  +-> mt5_module.initialize()       # Launch/connect to MT5 terminal process
  |    on failure: _last_error = last_error(), return False
  |
  +-> Check settings.MT5_DEMO_MODE
  |    if True: use DEMO login/password/server from settings
  |    if False: use REAL login/password/server from settings
  |
  +-> mt5_module.login(login, password, server)
  |    on failure: _last_error = last_error(), return False
  |
  +-> mt5_module.account_info()
  |    on None: return False
  |
  +-> _initialized = True
  +-> log connection details (login, server, name, balance)
  +-> return True
```

**Credential sources (from `config.settings.settings`):**
- Demo mode: `MT5_DEMO_MODE`, `MT5_DEMO_LOGIN`, `MT5_DEMO_PASSWORD`, `MT5_DEMO_SERVER`
- Real mode: `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`
- Default symbol: `DEFAULT_SYMBOL`

**No explicit validation of connection state before operations** — `send_market_order` checks `self.is_connected`, but candle/position queries call `mt5_module.*` directly without checking.

---

## 6. Error Handling Approach

| Area | Strategy |
|------|----------|
| `connect()` | Wrapped in `try/except Exception`; logs error to `_last_error` and returns `False`; also checks return values of `initialize()`, `login()`, `account_info()` individually |
| `disconnect()` | Wrapped in `try/except`; always tries `shutdown()` even if already disconnected |
| `get_candles()` | If MT5 returns None/empty, logs warning and returns empty DataFrame; catches exceptions and returns empty DataFrame |
| `save_candles_to_db()` | Catches DB exceptions, logs warning, returns 0 (graceful degradation) |
| `send_market_order()` | Checks demo mode first (skips actual sending); checks `is_connected`; checks price validity; checks `result.retcode != TRADE_RETCODE_DONE` for failure; returns `None` on any failure |
| `close_all_positions()` | Skips symbols where price is None/0; checks each result's retcode individually |
| `get_account_info()` | Returns `None` if MT5 API returns None; uses `getattr` with fallbacks for API version compatibility (`margin_free` vs `free_margin`) |
| `get_positions()`, `get_pending_orders()` | Return `[]` (empty list) if MT5 returns None; no exception handling per-iteration |

**Key observation:** Demo mode bypasses real order sending entirely — `send_market_order` and `close_all_positions` return early with logged messages when `settings.MT5_DEMO_MODE` is True.

---

## 7. Key Observations

1. **No thread safety** in singleton creation or MT5 state checks.
2. **Demo mode detection** at runtime, not compile time — allows easy testing without config changes to underlying order logic.
3. **Magic number hardcoded**: `magic=234567` on all orders.
4. **Order filling type fixed** to `ORDER_FILLING_IOC` (Immediate-or-Cancel).
5. **Candle column rename logic is fragile**: the second rename (lines 159-167) checks for a `"time"` column and no `"open"` — this handles an older MT5 API format but the condition could trigger incorrectly if data already has both formats.
6. **`save_candles_to_db` uses import-on-call** (`from db.engine import sync_engine`) rather than top-level import, avoiding circular imports.
7. **No reconnection logic**: once `disconnect()` is called, `_initialized=False` but the underlying MT5 process may still be running; a subsequent `connect()` call still runs `initialize()`.
