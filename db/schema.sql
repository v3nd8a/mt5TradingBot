-- ============================================================
-- TradingBot "Крон" — PostgreSQL Schema MVP
-- ============================================================

-- Candles (история OHLCV)
CREATE TABLE IF NOT EXISTS candles (
    id          BIGSERIAL PRIMARY KEY,
    symbol      VARCHAR(20)  NOT NULL,
    timeframe   VARCHAR(10)  NOT NULL,   -- M1, M5, M15, H1, ...
    open_time   TIMESTAMPTZ  NOT NULL,
    close_time  TIMESTAMPTZ  NOT NULL,
    open_price  DOUBLE PRECISION NOT NULL,
    high_price  DOUBLE PRECISION NOT NULL,
    low_price   DOUBLE PRECISION NOT NULL,
    close_price DOUBLE PRECISION NOT NULL,
    volume      BIGINT       NOT NULL DEFAULT 0,
    
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    
    UNIQUE(symbol, timeframe, open_time)
);

CREATE INDEX idx_candles_symbol ON candles(symbol, timeframe, open_time DESC);

-- AI Signals (сигналы модели)
CREATE TABLE IF NOT EXISTS signals (
    id              BIGSERIAL PRIMARY KEY,
    symbol          VARCHAR(20)  NOT NULL,
    signal_type     VARCHAR(10)  NOT NULL,   -- BUY / SELL / HOLD
    confidence      DOUBLE PRECISION NOT NULL,
    reason          TEXT,                        -- объяснение сигнала
    candle_count    INTEGER        NOT NULL DEFAULT 60,
    timeframe       VARCHAR(10)  NOT NULL,
    model_version   VARCHAR(50),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CHECK (confidence BETWEEN 0 AND 1)
);

CREATE INDEX idx_signals_symbol ON signals(symbol, created_at DESC);
CREATE INDEX idx_signals_type ON signals(signal_type, created_at DESC);

-- Trades (исполненные ордера)
CREATE TABLE IF NOT EXISTS trades (
    id                  BIGSERIAL PRIMARY KEY,
    signal_id           BIGINT REFERENCES signals(id),
    symbol              VARCHAR(20)  NOT NULL,
    direction           VARCHAR(10)  NOT NULL,   -- BUY / SELL
    order_type          VARCHAR(20),               -- MARKET / LIMIT / STOP
    volume              DOUBLE PRECISION NOT NULL,
    entry_price         DOUBLE PRECISION NOT NULL,
    sl_price            DOUBLE PRECISION,
    tp_price            DOUBLE PRECISION,
    status              VARCHAR(20)  NOT NULL DEFAULT 'OPEN',  -- OPEN / CLOSED / CANCELLED
    close_price         DOUBLE PRECISION,
    close_time          TIMESTAMPTZ,
    profit              DOUBLE PRECISION,           -- P&L в валюте счета
    commission          DOUBLE PRECISION DEFAULT 0,
    swap                DOUBLE PRECISION DEFAULT 0,
    notes               TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CHECK (volume > 0)
);

CREATE INDEX idx_trades_symbol ON trades(symbol, created_at DESC);
CREATE INDEX idx_trades_status ON trades(status);

-- Portfolio snapshot (моментальный снимок портфеля)
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    balance         DOUBLE PRECISION NOT NULL,
    equity          DOUBLE PRECISION NOT NULL,
    margin          DOUBLE PRECISION DEFAULT 0,
    free_margin     DOUBLE PRECISION DEFAULT 0,
    profit_total    DOUBLE PRECISION DEFAULT 0,
    positions_count INTEGER       NOT NULL DEFAULT 0,
    metadata_json   JSONB,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_portfolio_created ON portfolio_snapshots(created_at DESC);

-- Metrics (аналитика — ПЕРЕХОДНЫЙ ЭТАП P2)
CREATE TABLE IF NOT EXISTS metrics (
    id              BIGSERIAL PRIMARY KEY,
    metric_name     VARCHAR(50)  NOT NULL,
    metric_value    DOUBLE PRECISION NOT NULL,
    period_start    TIMESTAMPTZ,
    period_end      TIMESTAMPTZ,
    details_json    JSONB,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),

    UNIQUE(metric_name, period_start)
);

-- ============================================================
-- Миграция: удалить дубликаты candles
-- ============================================================
DO $$ BEGIN
        IF EXISTS (
            SELECT FROM pg_constraints
            WHERE conname = 'candles_symbol_timeframe_open_ukey'
        ) THEN
            ALTER TABLE candles ADD CONSTRAINT candles_symbol_timeframe_open_ukey
                UNIQUE(symbol, timeframe, open_time);
        END IF;
    END $$;
