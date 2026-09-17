"""Модели данных AI Engine."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from config.settings import settings


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class PredictionResult:
    """Результат предсказания модели."""
    signal: SignalType
    confidence: float              # 0.0 — 1.0
    reason: str = ""
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    
    @property
    def is_actionable(self) -> bool:
        threshold = float(getattr(settings, "CONFIDENCE_THRESHOLD", 0.65))
        return self.signal != SignalType.HOLD and self.confidence >= max(0.0, threshold)


@dataclass 
class TechnicalIndicators:
    """Технические индикаторы для анализа."""
    symbol: str = ""
    
    # Цена
    current_price: float = 0.0
    sma_20: float = 0.0
    sma_50: float = 0.0
    sma_200: float = 0.0
    
    # RSI
    rsi_14: float = 50.0
    rsi_signal: str = "NEUTRAL"  # OVERBOUGHT / OVERSOLD / NEUTRAL
    
    # MACD
    macd_line: float = 0.0
    macd_signal_line: float = 0.0
    macd_histogram: float = 0.0
    macd_signal: str = "NEUTRAL"
    
    # Bollinger Bands
    bb_upper: float = 0.0
    bb_middle: float = 0.0
    bb_lower: float = 0.0
    bb_position: float = 0.5     # 0=lower, 1=upper
    
    # ATR
    atr_14: float = 0.0
    
    # EMA
    ema_12: float = 0.0
    ema_26: float = 0.0
    
    # Volume
    volume_avg: int = 0
    volume_current: int = 0
    volume_ratio: float = 1.0
    
    # Stochastic
    stoch_k: float = 50.0
    stoch_d: float = 50.0
    stoch_signal: str = "NEUTRAL"


@dataclass
class CandleData:
    """Данные свечи для анализа."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    
    @property
    def body(self) -> float:
        return abs(self.close - self.open)
    
    @property
    def is_bullish(self) -> bool:
        return self.close > self.open
    
    @property
    def is_doji(self) -> bool:
        return self.body / (self.high - self.low) < 0.1 if self.high != self.low else False
