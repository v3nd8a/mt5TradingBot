"""SQLAlchemy модели для TradingBot."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Column, BigInteger, Double, Integer, String, Text, ForeignKey,
    JSON, DateTime, CheckConstraint, func
)
from sqlalchemy.dialects.postgresql import TIMESTAMPTZ
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ==================== Enums ====================

class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class OrderDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


# ==================== Models ====================

class Candle(Base):
    __tablename__ = "candles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    open_time = Column(TIMESTAMPTZ, nullable=False)
    close_time = Column(TIMESTAMPTZ, nullable=False)
    open_price = Column(Double, nullable=False)
    high_price = Column(Double, nullable=False)
    low_price = Column(Double, nullable=False)
    close_price = Column(Double, nullable=False)
    volume = Column(BigInteger, nullable=False, default=0)
    created_at = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())

    __table_args__ = (
        # UNIQUE(symbol, timeframe, open_time),
    )


class Signal(Base):
    __tablename__ = "signals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    signal_type = Column(String(10), nullable=False)
    confidence = Column(Double, nullable=False)
    reason = Column(Text)
    candle_count = Column(Integer, default=60)
    timeframe = Column(String(10), nullable=False)
    model_version = Column(String(50))
    created_at = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())

    trades = relationship("Trade", back_populates="signal")


class Trade(Base):
    __tablename__ = "trades"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    signal_id = Column(BigInteger, ForeignKey("signals.id"), nullable=True)
    symbol = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)
    order_type = Column(String(20))
    volume = Column(Double, nullable=False)
    entry_price = Column(Double, nullable=False)
    sl_price = Column(Double)
    tp_price = Column(Double)
    status = Column(String(20), nullable=False, default="OPEN")
    close_price = Column(Double)
    close_time = Column(TIMESTAMPTZ)
    profit = Column(Double)
    commission = Column(Double, default=0)
    swap_ = Column("swap", Double, default=0)
    notes = Column(Text)
    created_at = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMPTZ, nullable=False, server_default=func.now(), onupdate=func.now())

    signal = relationship("Signal", back_populates="trades")


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    balance = Column(Double, nullable=False)
    equity = Column(Double, nullable=False)
    margin = Column(Double, default=0)
    free_margin = Column(Double, default=0)
    profit_total = Column(Double, default=0)
    positions_count = Column(Integer, default=0)
    metadata_json = Column(JSON)
    created_at = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())


class Metric(Base):
    __tablename__ = "metrics"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    metric_name = Column(String(50), nullable=False)
    metric_value = Column(Double, nullable=False)
    period_start = Column(TIMESTAMPTZ)
    period_end = Column(TIMESTAMPTZ)
    details_json = Column(JSON)
    created_at = Column(TIMESTAMPTZ, nullable=False, server_default=func.now())
