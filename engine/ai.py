"""AI Engine — прогнозирование через Kronos (локальная) + Gemini fallback.

Анализировать рыночные данные и генерировать сигналы:
- Предсказание свечей через LSTM модель Kronos
- Расчёт технических индикаторов
- Fallback на Gemini API если локальная модель недоступна
"""

import logging
import time
import math
from datetime import datetime
from collections import OrderedDict
from typing import Optional

import numpy as np
import pandas as pd

from config.settings import settings
from engine.models import (
    PredictionResult, SignalType, TechnicalIndicators, CandleData
)

logger = logging.getLogger("ai_engine")


class TechnicalAnalysis:
    """Расчёт технических индикаторов."""

    @staticmethod
    def compute(df: pd.DataFrame, symbol: str = "") -> TechnicalIndicators:
        """Рассчитать все технические индикаторы из DataFrame свечей."""
        if df.empty or len(df) < 200:
            logger.warning(f"Not enough data for analysis: {len(df) if not df.empty else 0} candles")
            return TechnicalIndicators(symbol=symbol, current_price=df.iloc[-1]["close"] if not df.empty else 0)

        indicators = TechnicalIndicators(symbol=symbol)
        
        closes = df["close"]
        highs = df["high"]
        lows = df["low"]
        volumes = df.get("volume", pd.Series([0] * len(df)))
        
        # Текущая цена
        indicators.current_price = float(closes.iloc[-1])

        # SMA (простые скользящие средние)
        if len(closes) >= 20:
            indicators.sma_20 = float(closes.rolling(20).mean().iloc[-1])
        if len(closes) >= 50:
            indicators.sma_50 = float(closes.rolling(50).mean().iloc[-1])
        if len(closes) >= 200:
            indicators.sma_200 = float(closes.rolling(200).mean().iloc[-1])

        # EMA (экспоненциальные скользящие средние)
        if len(closes) >= 12:
            indicators.ema_12 = float(closes.ewm(span=12).mean().iloc[-1])
        if len(closes) >= 26:
            indicators.ema_26 = float(closes.ewm(span=26).mean().iloc[-1])

        # RSI (Relative Strength Index)
        indicators.rsi_14 = TechnicalAnalysis._rsi(closes, 14)
        if indicators.rsi_14 >= 70:
            indicators.rsi_signal = "OVERBOUGHT"
        elif indicators.rsi_14 <= 30:
            indicators.rsi_signal = "OVERSOLD"

        # MACD
        if len(closes) >= 26:
            ema_12 = closes.ewm(span=12).mean()
            ema_26 = closes.ewm(span=26).mean()
            macd_line = ema_12 - ema_26
            macd_signal_line = macd_line.ewm(span=9).mean()
            indicators.macd_line = float(macd_line.iloc[-1])
            indicators.macd_signal_line = float(macd_signal_line.iloc[-1])
            indicators.macd_histogram = float(macd_line.iloc[-1] - macd_signal_line.iloc[-1])
            if indicators.macd_line > indicators.macd_signal_line:
                indicators.macd_signal = "BULLISH"
            elif indicators.macd_line < indicators.macd_signal_line:
                indicators.macd_signal = "BEARISH"

        # Bollinger Bands
        if len(closes) >= 20:
            sma_20 = closes.rolling(20).mean()
            std_20 = closes.rolling(20).std()
            bb_upper = sma_20 + (2 * std_20)
            bb_lower = sma_20 - (2 * std_20)
            indicators.bb_upper = float(bb_upper.iloc[-1])
            indicators.bb_middle = float(sma_20.iloc[-1])
            indicators.bb_lower = float(bb_lower.iloc[-1])
            range_bb = indicators.bb_upper - indicators.bb_lower
            if range_bb > 0:
                indicators.bb_position = (indicators.current_price - indicators.bb_lower) / range_bb

        # ATR (Average True Range)
        indicators.atr_14 = TechnicalAnalysis._atr(df, 14)

        # Volume analysis
        if len(volumes) >= 20:
            indicators.volume_avg = float(volumes.rolling(20).mean().iloc[-1])
        indicators.volume_current = int(volumes.iloc[-1])
        if indicators.volume_avg > 0:
            indicators.volume_ratio = indicators.volume_current / indicators.volume_avg

        # Stochastic %K and %D
        if len(df) >= 14:
            low_14 = lows.rolling(14).min()
            high_14 = highs.rolling(14).max()
            denominator = high_14 - low_14
            denominator = denominator.replace(0, np.nan)  # избежать деления на ноль
            k_raw = ((df["close"] - low_14) / denominator) * 100
        
            indicators.stoch_k = float(k_raw.iloc[-1]) if not pd.isna(k_raw.iloc[-1]) else 50.0
            
            # %D = SMA от %K за 3 периода
            indicators.stoch_d = float(k_raw.rolling(3).mean().iloc[-1]) if len(k_raw) >= 3 else 50.0
            
            if indicators.stoch_k >= 80:
                indicators.stoch_signal = "OVERBOUGHT"
            elif indicators.stoch_k <= 20:
                indicators.stoch_signal = "OVERSOLD"

        return indicators

    @staticmethod
    def _rsi(prices: pd.Series, period: int = 14) -> float:
        """Расчёт RSI."""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        
        if loss.iloc[-1] == 0:
            return 100.0
        
        rs = gain.iloc[-1] / loss.iloc[-1]
        return round(100 - (100 / (1 + rs)), 2)

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> float:
        """Расчёт ATR."""
        high = df["high"]
        low = df["low"]
        close = df["close"].shift(1)
        
        tr1 = high - low
        tr2 = (high - close).abs()
        tr3 = (low - close).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return round(float(tr.rolling(period).mean().iloc[-1]), 6) if not df.empty else 0.0


class PredictionCache:
    """Кэш последних предсказаний для избежания повторных вычислений."""

    def __init__(self, max_size: int = 20, ttl_sec: int = 300):
        self._cache: OrderedDict[str, tuple[datetime, PredictionResult]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_sec

    def get(self, key: str) -> Optional[PredictionResult]:
        """Получить из кэша."""
        if key not in self._cache:
            return None
        
        cached_time, result = self._cache[key]
        if (datetime.now() - cached_time).total_seconds() > self._ttl:
            del self._cache[key]
            return None
        
        self._cache.move_to_end(key)
        return result

    def put(self, key: str, result: PredictionResult):
        """Добавить в кэш."""
        if key in self._cache:
            self._cache.pop(key)
        
        # Удаляем старые записи если переполнен
        while len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)
        
        self._cache[key] = (datetime.now(), result)

    def clear(self):
        """Очистить кэш."""
        self._cache.clear()


class AIEngine:
    """AI Engine — анализ рынка и генерация сигналов.
    
    Комбинирует:
    1. Технический анализ (RSI, MACD, Bollinger, ATR)
    2. Локальную LSTM модель Kronos для предсказания свечей
    3. Gemini API fallback для дополнительного анализа
    """

    def __init__(self):
        self._kronos_model = None
        self._cache = PredictionCache(
            max_size=settings.PREDICTION_CACHE_MAX,
            ttl_sec=settings.PREDICTION_CACHE_TTL_SEC
        )
        logger.info("AI Engine initialized")

    @property
    def is_ready(self) -> bool:
        return True  # Технический анализ всегда работает

    # ==================== Kronos Model ====================

    def _load_kronos_model(self):
        """Загрузить локальную модель Kronos (if available)."""
        if self._kronos_model is not None:
            return True

        try:
            # Определяем путь к модели
            # В реальном использовании здесь будет загрузка из файла/директории
            logger.info("Kronos model support — implement Kronos integration")
            return False
        except Exception as e:
            logger.error(f"Failed to load Kronos model: {e}")
            return False

    def _predict_with_kronos(self, df: pd.DataFrame) -> Optional[PredictionResult]:
        """Предсказание через Kronos LSTM модель."""
        if not self._load_kronos_model():
            return None
        
        # Здесь будет интеграция с реальной моделью Kronos:
        # https://github.com/shiyu-coder/Kronos
        # Модель принимает последовательность цен и предсказывает будущие значения
        pass

    # ==================== Gemini Fallback ====================

    def _analyze_with_gemini(self, symbol: str, indicators: TechnicalIndicators, candles: list[dict]) -> Optional[PredictionResult]:
        """Анализ через Gemini API (fallback)."""
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            
            model = genai.GenerativeModel(settings.GEMINI_MODEL)
            
            prompt = self._build_gemini_prompt(symbol, indicators, candles)
            response = model.generate_content(prompt)
            
            return self._parse_gemini_response(response.text)
        except Exception as e:
            logger.error(f"Gemini analysis failed: {e}")
            return None

    def _build_gemini_prompt(self, symbol: str, indicators: TechnicalIndicators, candles: list[dict]) -> str:
        """Сформировать промпт для Gemini."""
        recent_candles = "\n".join([
            f"  Time: {c['time']}, O:{c['open']} H:{c['high']} L:{c['low']} C:{c['close']} V:{c['volume']}"
            for c in candles[-10:]
        ])
        
        prompt = f"""Ты — профессиональный трейдер и аналитик. Проанализируй символ {symbol} на основе технических индикаторов:

ТЕКУЩИЕ ДАННЫЕ (цены ~{indicators.current_price}):
- SMA20: {indicators.sma_20:.4f}, SMA50: {indicators.sma_50:.4f}, SMA200: {indicators.sma_200:.4f}
- EMA12: {indicators.ema_12:.4f}, EMA26: {indicators.ema_26:.4f}
- RSI(14): {indicators.rsi_14:.2f} ({indicators.rsi_signal})
- MACD: {indicators.macd_line:.4f}, Signal: {indicators.macd_signal_line:.4f}, Histogram: {indicators.macd_histogram:.6f} ({indicators.macd_signal})
- Bollinger: Lower={indicators.bb_lower:.4f}, Middle={indicators.bb_middle:.4f}, Upper={indicators.bb_upper:.4f}, Position={indicators.bb_position:.1%}
- ATR(14): {indicators.atr_14:.6f}
- Stoch: K={indicators.stoch_k:.1f}, D={indicators.stoch_d:.1f} ({indicators.stoch_signal})
- Volume Ratio: {indicators.volume_ratio:.2f}

ПОСЛЕДНИЕ 10 СВЕЧЕЙ:
{recent_candles}

Верни ТОЛЬКО JSON без текста:
{{
    "signal": "BUY" | "SELL" | "HOLD",
    "confidence": 0.0-1.0,
    "reason": "краткое обоснование (до 50 символов)",
    "target_price": цена_цели или null,
    "stop_loss": цена_SL или null,
    "take_profit": цена_TP или null
}}
"""
        return prompt

    def _parse_gemini_response(self, text: str) -> PredictionResult:
        """Парсить ответ Gemini в PredictionResult."""
        import json
        
        # Извлекаем JSON из текста
        start = text.find("{")
        end = text.rfind("}") + 1
        
        if start == -1 or end == 0:
            logger.warning("Could not find JSON in Gemini response")
            return PredictionResult(signal=SignalType.HOLD, confidence=0.0, reason="No valid signal from AI")

        try:
            data = json.loads(text[start:end])
            return PredictionResult(
                signal=SignalType(data.get("signal", "HOLD")),
                confidence=min(max(data.get("confidence", 0), 0), 1),
                reason=data.get("reason", ""),
                target_price=data.get("target_price"),
                stop_loss=data.get("stop_loss"),
                take_profit=data.get("take_profit"),
            )
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse Gemini JSON: {text[start:end]}")
            return PredictionResult(signal=SignalType.HOLD, confidence=0.0, reason="Parse error")

    # ==================== Core Analysis (Always Available) ====================

    def analyze(
        self,
        candles_df: pd.DataFrame,
        symbol: str = "",
        use_kronos: bool = True,
        use_gemini: bool = True,
    ) -> PredictionResult:
        """Основной метод анализа — комбинированный подход.
        
        Алгоритм:
        1. Рассчитываем технические индикаторы (всегда)
        2. Генерируем технический сигнал (весовой голосующий системный анализ)
        3. Если доступен — добавляем Kronos предсказание
        4. Если доступно — Gemini fallback для валидации
        5. Финальный сигнал = взвешенная комбинация
        """
        if candles_df.empty or len(candles_df) < 20:
            return PredictionResult(signal=SignalType.HOLD, confidence=0.0, reason="Недостаточно данных")

        # Технический анализ всегда выполняется
        indicators = TechnicalAnalysis.compute(candles_df, symbol)
        tech_signal = self._technical_analysis_only(indicators)
        
        # Кэш ключ
        cache_key = f"{symbol}_{indicators.current_price:.1f}_{tech_signal.signal.value}"
        cached = self._cache.get(cache_key)
        if cached:
            logger.debug("Cache hit for prediction")
            return cached

        # Kronos предсказание (если включено и модель загружена)
        kronos_signal = None
        if use_kronos and settings.USE_KRONOS_LOCAL:
            try:
                kronos_result = self._predict_with_kronos(candles_df)
                if kronos_result and kronos_result.signal != SignalType.HOLD:
                    kronos_signal = kronos_result
            except Exception as e:
                logger.warning(f"Kronos prediction failed, continuing with technical analysis only: {e}")

        # Gemini fallback (если включено)
        gemini_signal = None
        if use_gemini and settings.USE_GEMINI_FALLBACK:
            try:
                recent_df = candles_df.tail(20).copy()
                recent_dict = []
                for _, row in recent_df.iterrows():
                    recent_dict.append({
                        "time": str(row["time"]),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": int(row.get("volume", 0)),
                    })
                gemini_result = self._analyze_with_gemini(symbol, indicators, recent_dict)
                if gemini_result and gemini_result.signal != SignalType.HOLD:
                    gemini_signal = gemini_result
            except Exception as e:
                logger.warning(f"Gemini analysis failed, using technical + Kronos only: {e}")

        # ==================== Взвешенная комбинация сигналов ====================
        final_signal = self._combine_signals(
            tech=tech_signal,
            kronos=kronos_signal,
            gemini=gemini_signal,
        )
        
        # Сохраняем в кэш
        self._cache.put(cache_key, final_signal)
        
        logger.info(
            f"[{symbol}] Signal: {final_signal.signal.value} | "
            f"Confidence: {final_signal.confidence:.2f} | "
            f"Reason: {final_signal.reason}"
        )
        
        return final_signal

    def _technical_analysis_only(self, indicators: TechnicalIndicators) -> PredictionResult:
        """Чисто технический анализ (весовой голосующий алгоритм)."""
        score = 0.0  # -10 (сильный SELL) to +10 (сильный BUY)
        reasons = []

        # SMA — тренд
        if indicators.sma_20 > indicators.sma_50:
            score += 1.5
            reasons.append("Bullish MA cross")
        elif indicators.sma_20 < indicators.sma_50:
            score -= 1.5
            reasons.append("Bearish MA cross")

        if indicators.current_price > indicators.sma_20:
            score += 1.0
        elif indicators.current_price < indicators.sma_20:
            score -= 1.0
        
        # EMA — краткосрочный тренд
        if indicators.ema_12 > indicators.ema_26:
            score += 1.5
        elif indicators.ema_12 < indicators.ema_26:
            score -= 1.5

        # RSI
        if indicators.rsi_signal == "OVERSOLD":
            score += 2.0
            reasons.append(f"RSI overbought {indicators.rsi_signal}")
        elif indicators.rsi_signal == "OVERBOUGHT":
            score -= 2.0

        # MACD
        if indicators.macd_signal == "BULLISH":
            score += 1.5
        elif indicators.macd_signal == "BEARISH":
            score -= 1.5
        
        if indicators.macd_histogram > abs(indicators.macd_signal_line) * 0.1:
            score += 0.5
        elif indicators.macd_histogram < -abs(indicators.macd_signal_line) * 0.1:
            score -= 0.5

        # Bollinger Bands
        if indicators.bb_position <= 0.1:
            score += 2.0  # цена у нижней границы — возможно отскока
            reasons.append("Bollinger lower band bounce")
        elif indicators.bb_position >= 0.9:
            score -= 2.0  # цена у верхней границы — возможна коррекция
            reasons.append("Bollinger upper band rejection")

        # Stochastic
        if indicators.stoch_signal == "OVERSOLD":
            score += 1.5
        elif indicators.stoch_signal == "OVERBOUGHT":
            score -= 1.5

        # Volume confirmation
        if indicators.volume_ratio > 1.5:
            # Подтверждение сигналом по направлению тренда
            direction = 1 if score > 0 else -1
            score += 0.5 * direction

        # Нормализация в confidence
        signal = SignalType.HOLD
        if score >= 3.0:
            signal = SignalType.BUY
        elif score <= -3.0:
            signal = SignalType.SELL
        
        confidence = min(abs(score) / 12.0, 1.0)  # нормализация

        return PredictionResult(
            signal=signal,
            confidence=max(confidence, 0.0),
            reason="; ".join(reasons) if reasons else ("Neutral — no strong signals" if signal == SignalType.HOLD else "Technical analysis"),
            target_price=self._calc_target(indicators.signal.value),
        )

    def _calc_target(self, direction: str, indicators: TechnicalIndicators) -> dict:
        """Вычислить цели входа/выхода на основе технических индикаторов и ATR."""
        if not indicators or indicators.current_price <= 0:
            return {"target": None, "sl": None, "tp": None}

        atr = indicators.atr_14 if indicators.atr_14 > 0 else 0.0001  # fallback default
        price = indicators.current_price
        
        # TP на основе ATR (2x ATR для достаточного пространства)
        sl_pips = settings.DEFAULT_SL_PIPS
        tp_pips = settings.DEFAULT_TP_PIPS
        
        if direction == SignalType.BUY:
            target = price + (tp_pips * 0.0001) if "JPY" not in indicators.symbol else price + (tp_pips * 0.01)
            sl = price - (sl_pips * 0.0001) if "JPY" not in indicators.symbol else price - (sl_pips * 0.01)
            tp_atr = price + (2.0 * atr)
        elif direction == SignalType.SELL:
            target = price - (tp_pips * 0.0001) if "JPY" not in indicators.symbol else price - (tp_pips * 0.01)
            sl = price + (sl_pips * 0.0001) if "JPY" not in indicators.symbol else price + (sl_pips * 0.01)
            tp_atr = price - (2.0 * atr)
        else:
            return {"target": None, "sl": None, "tp": None}

        return {
            "target": round(target, indicators.symbol.count('.') + 4 if '.' in indicators.symbol else 5),
            "sl": round(sl, 5),
            "tp": round(tp_atr, 5),
        }
    
    def _combine_signals(
        self,
        tech: PredictionResult,
        kronos: Optional[PredictionResult],
        gemini: Optional[PredictionResult]
    ) -> PredictionResult:
        """Комбинировать сигналы с весами."""
        weights = {
            "tech": 0.5,
            "kronos": 0.25 if settings.USE_KRONOS_LOCAL else 0,
            "gemini": 0.25 if settings.USE_GEMINI_FALLBACK else 0,
        }
        
        total_weight = sum(weights.values())
        if total_weight == 0:
            return PredictionResult(signal=SignalType.HOLD, confidence=0.0, reason="No analysis methods available")
            
        score_sum = tech.confidence * (1 if tech.signal == SignalType.BUY else (-1 if tech.signal == SignalType.SELL else 0)) * weights["tech"]
        all_reasons = [tech.reason]
        
        if kronos and kronos.signal != SignalType.HOLD:
            score_sum += kronos.confidence * (1 if kronos.signal == SignalType.BUY else -1) * weights["kronos"]
            all_reasons.append(kronos.reason)
            
        if gemini and gemini.signal != SignalType.HOLD:
            score_sum += gemini.confidence * (1 if gemini.signal == SignalType.BUY else -1) * weights["gemini"]
            all_reasons.append(gemini.reason)

        final_score = score_sum / total_weight
        
        # Определяем сигнал
        if abs(final_score) < 0.3:
            return PredictionResult(
                signal=SignalType.HOLD,
                confidence=max(abs(final_score), 0.1),
                reason="Mixed signals — no clear direction",
            )

        signal = SignalType.BUY if final_score > 0 else SignalType.SELL
        final_confidence = min(max(abs(final_score), 0.35), 0.99)

        return PredictionResult(
            signal=signal,
            confidence=final_confidence,
            reason="; ".join(all_reasons[:3]),
        )

    def clear_cache(self):
        """Очистить кэш."""
        self._cache.clear()
        logger.info("AI prediction cache cleared")


# ==================== Singleton ====================
_ai_engine = None


def get_ai_engine() -> AIEngine:
    return _ai_engine if _ai_engine else AIEngine()
