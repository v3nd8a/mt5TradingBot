"""AI Engine вЂ” РїСЂРѕРіРЅРѕР·РёСЂРѕРІР°РЅРёРµ С‡РµСЂРµР· Kronos (Р»РѕРєР°Р»СЊРЅР°СЏ) + Gemini fallback.

РђРЅР°Р»РёР·РёСЂРѕРІР°С‚СЊ СЂС‹РЅРѕС‡РЅС‹Рµ РґР°РЅРЅС‹Рµ Рё РіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ СЃРёРіРЅР°Р»С‹:
- РџСЂРµРґСЃРєР°Р·Р°РЅРёРµ СЃРІРµС‡РµР№ С‡РµСЂРµР· LSTM РјРѕРґРµР»СЊ Kronos
- Р Р°СЃС‡С‘С‚ С‚РµС…РЅРёС‡РµСЃРєРёС… РёРЅРґРёРєР°С‚РѕСЂРѕРІ
- Fallback РЅР° Gemini API РµСЃР»Рё Р»РѕРєР°Р»СЊРЅР°СЏ РјРѕРґРµР»СЊ РЅРµРґРѕСЃС‚СѓРїРЅР°
"""

import logging
import time
import math
import json
import urllib.error
import urllib.request
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
    """Р Р°СЃС‡С‘С‚ С‚РµС…РЅРёС‡РµСЃРєРёС… РёРЅРґРёРєР°С‚РѕСЂРѕРІ."""

    @staticmethod
    def compute(df: pd.DataFrame, symbol: str = "") -> TechnicalIndicators:
        """Р Р°СЃСЃС‡РёС‚Р°С‚СЊ РІСЃРµ С‚РµС…РЅРёС‡РµСЃРєРёРµ РёРЅРґРёРєР°С‚РѕСЂС‹ РёР· DataFrame СЃРІРµС‡РµР№."""
        if df.empty or len(df) < 200:
            logger.warning(f"Not enough data for analysis: {len(df) if not df.empty else 0} candles")
            return TechnicalIndicators(symbol=symbol, current_price=df.iloc[-1]["close"] if not df.empty else 0)

        indicators = TechnicalIndicators(symbol=symbol)
        
        closes = df["close"]
        highs = df["high"]
        lows = df["low"]
        volumes = df.get("volume", pd.Series([0] * len(df)))
        
        # РўРµРєСѓС‰Р°СЏ С†РµРЅР°
        indicators.current_price = float(closes.iloc[-1])

        # SMA (РїСЂРѕСЃС‚С‹Рµ СЃРєРѕР»СЊР·СЏС‰РёРµ СЃСЂРµРґРЅРёРµ)
        if len(closes) >= 20:
            indicators.sma_20 = float(closes.rolling(20).mean().iloc[-1])
        if len(closes) >= 50:
            indicators.sma_50 = float(closes.rolling(50).mean().iloc[-1])
        if len(closes) >= 200:
            indicators.sma_200 = float(closes.rolling(200).mean().iloc[-1])

        # EMA (СЌРєСЃРїРѕРЅРµРЅС†РёР°Р»СЊРЅС‹Рµ СЃРєРѕР»СЊР·СЏС‰РёРµ СЃСЂРµРґРЅРёРµ)
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
            denominator = denominator.replace(0, np.nan)  # РёР·Р±РµР¶Р°С‚СЊ РґРµР»РµРЅРёСЏ РЅР° РЅРѕР»СЊ
            k_raw = ((df["close"] - low_14) / denominator) * 100
        
            indicators.stoch_k = float(k_raw.iloc[-1]) if not pd.isna(k_raw.iloc[-1]) else 50.0
            
            # %D = SMA РѕС‚ %K Р·Р° 3 РїРµСЂРёРѕРґР°
            indicators.stoch_d = float(k_raw.rolling(3).mean().iloc[-1]) if len(k_raw) >= 3 else 50.0
            
            if indicators.stoch_k >= 80:
                indicators.stoch_signal = "OVERBOUGHT"
            elif indicators.stoch_k <= 20:
                indicators.stoch_signal = "OVERSOLD"

        return indicators

    @staticmethod
    def _rsi(prices: pd.Series, period: int = 14) -> float:
        """Р Р°СЃС‡С‘С‚ RSI."""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        
        if loss.iloc[-1] == 0:
            return 100.0
        
        rs = gain.iloc[-1] / loss.iloc[-1]
        return round(100 - (100 / (1 + rs)), 2)

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> float:
        """Р Р°СЃС‡С‘С‚ ATR."""
        high = df["high"]
        low = df["low"]
        close = df["close"].shift(1)
        
        tr1 = high - low
        tr2 = (high - close).abs()
        tr3 = (low - close).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return round(float(tr.rolling(period).mean().iloc[-1]), 6) if not df.empty else 0.0


class PredictionCache:
    """РљСЌС€ РїРѕСЃР»РµРґРЅРёС… РїСЂРµРґСЃРєР°Р·Р°РЅРёР№ РґР»СЏ РёР·Р±РµР¶Р°РЅРёСЏ РїРѕРІС‚РѕСЂРЅС‹С… РІС‹С‡РёСЃР»РµРЅРёР№."""

    def __init__(self, max_size: int = 20, ttl_sec: int = 300):
        self._cache: OrderedDict[str, tuple[datetime, PredictionResult]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_sec

    def get(self, key: str) -> Optional[PredictionResult]:
        """РџРѕР»СѓС‡РёС‚СЊ РёР· РєСЌС€Р°."""
        if key not in self._cache:
            return None
        
        cached_time, result = self._cache[key]
        if (datetime.now() - cached_time).total_seconds() > self._ttl:
            del self._cache[key]
            return None
        
        self._cache.move_to_end(key)
        return result

    def put(self, key: str, result: PredictionResult):
        """Р”РѕР±Р°РІРёС‚СЊ РІ РєСЌС€."""
        if key in self._cache:
            self._cache.pop(key)
        
        # РЈРґР°Р»СЏРµРј СЃС‚Р°СЂС‹Рµ Р·Р°РїРёСЃРё РµСЃР»Рё РїРµСЂРµРїРѕР»РЅРµРЅ
        while len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)
        
        self._cache[key] = (datetime.now(), result)

    def clear(self):
        """РћС‡РёСЃС‚РёС‚СЊ РєСЌС€."""
        self._cache.clear()


class AIEngine:
    """AI Engine вЂ” Р°РЅР°Р»РёР· СЂС‹РЅРєР° Рё РіРµРЅРµСЂР°С†РёСЏ СЃРёРіРЅР°Р»РѕРІ.
    
    РљРѕРјР±РёРЅРёСЂСѓРµС‚:
    1. РўРµС…РЅРёС‡РµСЃРєРёР№ Р°РЅР°Р»РёР· (RSI, MACD, Bollinger, ATR)
    2. Р›РѕРєР°Р»СЊРЅСѓСЋ LSTM РјРѕРґРµР»СЊ Kronos РґР»СЏ РїСЂРµРґСЃРєР°Р·Р°РЅРёСЏ СЃРІРµС‡РµР№
    3. Gemini API fallback РґР»СЏ РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅРѕРіРѕ Р°РЅР°Р»РёР·Р°
    """

    def __init__(self):
        self._kronos_model = None
        self._kairos_model = None
        self._last_kronos_issue: Optional[str] = None
        self._last_kairos_issue: Optional[str] = None
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
        """Загрузить модуль Kronos."""
        if self._kronos_model is not None:
            return True

        try:
            from engine.kronos import get_kronos_predictor
            self._kronos_model = get_kronos_predictor()
            logger.info("Kronos AI predictor loaded successfully")
            return True
        except Exception as e:
            self._last_kronos_issue = f"predictor initialization failed: {type(e).__name__}: {e}"
            logger.error(f"Failed to load Kronos predictor: {e}")
            return False

    def _predict_with_kronos(self, df: pd.DataFrame, symbol: str = "") -> Optional[PredictionResult]:
        """Предсказание через модель Kronos."""
        self._last_kronos_issue = None
        if not self._load_kronos_model():
            return None

        try:
            result = self._kronos_model.predict(df, symbol=symbol)
            if result is None:
                self._last_kronos_issue = "Kronos returned no forecast; check the preceding warning"
            return result
        except Exception as e:
            self._last_kronos_issue = f"prediction failed: {type(e).__name__}: {e}"
            logger.error(f"Kronos prediction error: {e}")
            return None

    # ==================== Kairos Model ====================

    def _load_kairos_model(self) -> bool:
        """Загрузить модуль Kairos."""
        if self._kairos_model is not None:
            return True

        try:
            from engine.kairos import get_kairos_predictor
            self._kairos_model = get_kairos_predictor()
            logger.info("Kairos AI predictor loaded successfully")
            return True
        except Exception as e:
            self._last_kairos_issue = f"predictor initialization failed: {type(e).__name__}: {e}"
            logger.error(f"Failed to load Kairos predictor: {e}")
            return False

    def _predict_with_kairos(self, df: pd.DataFrame, symbol: str = "") -> Optional[PredictionResult]:
        """Предсказание через модель Kairos."""
        self._last_kairos_issue = None
        if not self._load_kairos_model():
            return None

        try:
            result = self._kairos_model.predict(df, symbol=symbol)
            if result is None:
                self._last_kairos_issue = "Kairos returned no forecast; check the preceding warning"
            return result
        except Exception as e:
            self._last_kairos_issue = f"prediction failed: {type(e).__name__}: {e}"
            logger.error(f"Kairos prediction error: {e}")
            return None

    # ==================== Ollama Fallback ====================

    def _analyze_with_ollama(
        self,
        symbol: str,
        indicators: TechnicalIndicators,
        candles: list[dict],
        kronos: Optional[PredictionResult] = None,
    ) -> Optional[PredictionResult]:
        """Анализ через локальную Ollama-модель."""
        prompt = self._build_ollama_prompt(symbol, indicators, candles, kronos)
        payload = json.dumps({
            "model": settings.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.OLLAMA_TIMEOUT) as response:
                result = json.loads(response.read().decode("utf-8"))
            text = result.get("response", "")
            if text:
                return self._parse_ollama_response(text)
        except urllib.error.URLError as e:
            logger.warning(f"Ollama is unavailable at {settings.OLLAMA_BASE_URL}: {e}")
        except Exception as e:
            logger.warning(f"Ollama API call failed: {e}")

        return None

    def _build_ollama_prompt(
        self,
        symbol: str,
        indicators: TechnicalIndicators,
        candles: list[dict],
        kronos: Optional[PredictionResult] = None,
    ) -> str:
        """Формируем промпт для Ollama/LLM анализа."""
        recent_candles = "\n".join([
            f"  Time: {c['time']}, O:{c['open']} H:{c['high']} L:{c['low']} C:{c['close']} V:{c['volume']}"
            for c in candles[-10:]
        ])

        predictor_type = getattr(settings, "AI_PREDICTOR", "kronos").split("#")[0].strip().lower()
        model_name = "Kairos" if (predictor_type == "kairos" or (kronos and "Kairos" in getattr(kronos, "reason", ""))) else "Kronos"
        kronos_context = (
            f"Сигнал: {kronos.signal.value}; confidence: {kronos.confidence:.3f}; "
            f"target: {kronos.target_price}; SL: {kronos.stop_loss}; TP: {kronos.take_profit}; "
            f"обоснование: {kronos.reason}"
            if kronos else f"{model_name} недоступен"
        )
        prompt = f"""Ты — подтверждающий аналитик для модели {model_name} по символу {symbol}.
    {model_name} — главный источник направления и торговых уровней. Не меняй его BUY/SELL/HOLD.
    Проверь его вывод техническими данными и верни тот же signal. Если {model_name} дал HOLD,
    верни HOLD. Не изобретай новые SL/TP: используй уровни {model_name} или null.

    ВЫВОД {model_name.upper()}:
    {kronos_context}

    ТЕХНИЧЕСКИЕ ИНДИКАТОРЫ:

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
    "target_price": число_цели или null,
    "stop_loss": число_SL или null,
    "take_profit": число_TP или null
}}
"""
        return prompt

    def _parse_ollama_response(self, text: str) -> PredictionResult:
        """Парсить ответ Ollama в PredictionResult."""
        # Извлекаем JSON из текста
        start = text.find("{")
        end = text.rfind("}") + 1
        
        if start == -1 or end == 0:
            logger.warning("Could not find JSON in Ollama response")
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
            logger.warning(f"Failed to parse Ollama JSON: {text[start:end]}")
            return PredictionResult(signal=SignalType.HOLD, confidence=0.0, reason="Parse error")

    # ==================== Core Analysis (Always Available) ====================

    def analyze(
        self,
        candles_df: pd.DataFrame,
        symbol: str = "",
        use_kronos: bool = True,
        use_gemini: bool = True,
    ) -> PredictionResult:
        """РћСЃРЅРѕРІРЅРѕР№ РјРµС‚РѕРґ Р°РЅР°Р»РёР·Р° вЂ” РєРѕРјР±РёРЅРёСЂРѕРІР°РЅРЅС‹Р№ РїРѕРґС…РѕРґ.
        
        РђР»РіРѕСЂРёС‚Рј:
        1. Р Р°СЃСЃС‡РёС‚С‹РІР°РµРј С‚РµС…РЅРёС‡РµСЃРєРёРµ РёРЅРґРёРєР°С‚РѕСЂС‹ (РІСЃРµРіРґР°)
        2. Р“РµРЅРµСЂРёСЂСѓРµРј С‚РµС…РЅРёС‡РµСЃРєРёР№ СЃРёРіРЅР°Р» (РІРµСЃРѕРІРѕР№ РіРѕР»РѕСЃСѓСЋС‰РёР№ СЃРёСЃС‚РµРјРЅС‹Р№ Р°РЅР°Р»РёР·)
        3. Р•СЃР»Рё РґРѕСЃС‚СѓРїРµРЅ вЂ” РґРѕР±Р°РІР»СЏРµРј Kronos РїСЂРµРґСЃРєР°Р·Р°РЅРёРµ
        4. Р•СЃР»Рё РґРѕСЃС‚СѓРїРЅРѕ вЂ” Gemini fallback РґР»СЏ РІР°Р»РёРґР°С†РёРё
        5. Р¤РёРЅР°Р»СЊРЅС‹Р№ СЃРёРіРЅР°Р» = РІР·РІРµС€РµРЅРЅР°СЏ РєРѕРјР±РёРЅР°С†РёСЏ
        """
        if candles_df.empty or len(candles_df) < 20:
            return PredictionResult(signal=SignalType.HOLD, confidence=0.0, reason="РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ РґР°РЅРЅС‹С…")

        # РўРµС…РЅРёС‡РµСЃРєРёР№ Р°РЅР°Р»РёР· РІСЃРµРіРґР° РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ
        indicators = TechnicalAnalysis.compute(candles_df, symbol)
        tech_signal = self._technical_analysis_only(indicators)
        
        # РљСЌС€ РєР»СЋС‡
        cache_key = f"{symbol}_{indicators.current_price:.1f}_{tech_signal.signal.value}"
        cached = self._cache.get(cache_key)
        if cached:
            logger.debug("Cache hit for prediction")
            return cached

        # Первичный AI-анализ (Kronos или Kairos в зависимости от settings.AI_PREDICTOR)
        kronos_signal = None
        kronos_issue = None
        predictor_type = getattr(settings, "AI_PREDICTOR", "kronos").split("#")[0].strip().lower()
        predictor_name = "Kairos" if predictor_type == "kairos" else "Kronos"

        if use_kronos and settings.USE_KRONOS_LOCAL:
            try:
                if predictor_type == "kairos":
                    pred_result = self._predict_with_kairos(candles_df, symbol=symbol)
                    if pred_result and self._kairos_model:
                        calibration_horizon = int(getattr(settings, "KAIROS_FORECAST_HORIZON", settings.KRONOS_FORECAST_HORIZON))
                        calibrated, samples = self._kairos_model.calibrated_confidence(
                            pred_result.confidence,
                            candles_df,
                            symbol,
                            calibration_horizon,
                            int(settings.KRONOS_CALIBRATION_MIN_SAMPLES),
                        )
                        pred_result = PredictionResult(
                            signal=pred_result.signal,
                            confidence=calibrated,
                            reason=f"{pred_result.reason} | calibrated from {samples} samples",
                            target_price=pred_result.target_price,
                            stop_loss=pred_result.stop_loss,
                            take_profit=pred_result.take_profit,
                        )
                    pred_issue = self._last_kairos_issue
                else:
                    pred_result = self._predict_with_kronos(candles_df, symbol=symbol)
                    pred_issue = self._last_kronos_issue

                if pred_result:
                    kronos_signal = pred_result
                else:
                    kronos_issue = pred_issue or f"{predictor_name} returned no forecast"
            except Exception as e:
                kronos_issue = f"analysis failed: {type(e).__name__}: {e}"
                logger.warning(f"{predictor_name} prediction failed, continuing with technical analysis only: {e}")
        else:
            kronos_issue = f"{predictor_name} analysis is disabled"

        # Ollama fallback (РµСЃР»Рё РІРєР»СЋС‡РµРЅРѕ)
        gemini_signal = None
        if use_gemini and settings.USE_OLLAMA:
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
                gemini_result = self._analyze_with_ollama(symbol, indicators, recent_dict, kronos_signal)
                if gemini_result and gemini_result.signal != SignalType.HOLD:
                    gemini_signal = gemini_result
            except Exception as e:
                logger.warning(f"Ollama analysis failed, using technical + Kronos only: {e}")

        # ==================== Р’Р·РІРµС€РµРЅРЅР°СЏ РєРѕРјР±РёРЅР°С†РёСЏ СЃРёРіРЅР°Р»РѕРІ ====================
        final_signal = self._combine_signals(
            tech=tech_signal,
            kronos=kronos_signal,
            gemini=gemini_signal,
            kronos_issue=kronos_issue,
        )
        final_signal = self._apply_risk_levels(
            final_signal,
            candles_df,
            symbol,
            kronos_signal,
            tech_signal,
            gemini_signal,
        )
        
        # РЎРѕС…СЂР°РЅСЏРµРј РІ РєСЌС€
        self._cache.put(cache_key, final_signal)
        
        logger.info(
            f"[{symbol}] Signal: {final_signal.signal.value} | "
            f"Confidence: {final_signal.confidence:.2f} | "
            f"Reason: {final_signal.reason}"
        )
        
        return final_signal

    def _technical_analysis_only(self, indicators: TechnicalIndicators) -> PredictionResult:
        """Р§РёСЃС‚Рѕ С‚РµС…РЅРёС‡РµСЃРєРёР№ Р°РЅР°Р»РёР· (РІРµСЃРѕРІРѕР№ РіРѕР»РѕСЃСѓСЋС‰РёР№ Р°Р»РіРѕСЂРёС‚Рј)."""
        score = 0.0  # -10 (СЃРёР»СЊРЅС‹Р№ SELL) to +10 (СЃРёР»СЊРЅС‹Р№ BUY)
        reasons = []

        # SMA вЂ” С‚СЂРµРЅРґ
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
        
        # EMA вЂ” РєСЂР°С‚РєРѕСЃСЂРѕС‡РЅС‹Р№ С‚СЂРµРЅРґ
        if indicators.ema_12 > indicators.ema_26:
            score += 1.5
        elif indicators.ema_12 < indicators.ema_26:
            score -= 1.5

        # RSI
        if indicators.rsi_signal == "OVERSOLD":
            score += 2.0
            reasons.append(f"RSI oversold ({indicators.rsi_signal})")
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
            score += 2.0  # С†РµРЅР° Сѓ РЅРёР¶РЅРµР№ РіСЂР°РЅРёС†С‹ вЂ” РІРѕР·РјРѕР¶РЅРѕ РѕС‚СЃРєРѕРєР°
            reasons.append("Bollinger lower band bounce")
        elif indicators.bb_position >= 0.9:
            score -= 2.0  # С†РµРЅР° Сѓ РІРµСЂС…РЅРµР№ РіСЂР°РЅРёС†С‹ вЂ” РІРѕР·РјРѕР¶РЅР° РєРѕСЂСЂРµРєС†РёСЏ
            reasons.append("Bollinger upper band rejection")

        # Stochastic
        if indicators.stoch_signal == "OVERSOLD":
            score += 1.5
        elif indicators.stoch_signal == "OVERBOUGHT":
            score -= 1.5

        # Volume confirmation
        if indicators.volume_ratio > 1.5:
            # РџРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ СЃРёРіРЅР°Р»РѕРј РїРѕ РЅР°РїСЂР°РІР»РµРЅРёСЋ С‚СЂРµРЅРґР°
            direction = 1 if score > 0 else -1
            score += 0.5 * direction

        # РќРѕСЂРјР°Р»РёР·Р°С†РёСЏ РІ confidence
        signal = SignalType.HOLD
        if score >= 3.0:
            signal = SignalType.BUY
        elif score <= -3.0:
            signal = SignalType.SELL
        
        confidence = min(abs(score) / 12.0, 1.0)  # РЅРѕСЂРјР°Р»РёР·Р°С†РёСЏ

        return PredictionResult(
            signal=signal,
            confidence=max(confidence, 0.0),
            reason="; ".join(reasons) if reasons else ("Neutral вЂ” no strong signals" if signal == SignalType.HOLD else "Technical analysis"),
            target_price=self._calc_target(signal, indicators),
        )

    def _calc_target(self, direction: str, indicators: TechnicalIndicators) -> dict:
        """Р’С‹С‡РёСЃР»РёС‚СЊ С†РµР»Рё РІС…РѕРґР°/РІС‹С…РѕРґР° РЅР° РѕСЃРЅРѕРІРµ С‚РµС…РЅРёС‡РµСЃРєРёС… РёРЅРґРёРєР°С‚РѕСЂРѕРІ Рё ATR."""
        if not indicators or indicators.current_price <= 0:
            return {"target": None, "sl": None, "tp": None}

        atr = indicators.atr_14 if indicators.atr_14 > 0 else 0.0001  # fallback default
        price = indicators.current_price
        
        # TP РЅР° РѕСЃРЅРѕРІРµ ATR (2x ATR РґР»СЏ РґРѕСЃС‚Р°С‚РѕС‡РЅРѕРіРѕ РїСЂРѕСЃС‚СЂР°РЅСЃС‚РІР°)
        sl_pips = settings.DEFAULT_SL_PIPS
        tp_pips = settings.DEFAULT_TP_PIPS
        
        if direction == SignalType.BUY.value:
            target = price + (tp_pips * 0.0001) if "JPY" not in indicators.symbol else price + (tp_pips * 0.01)
            sl = price - (sl_pips * 0.0001) if "JPY" not in indicators.symbol else price - (sl_pips * 0.01)
            tp_atr = price + (2.0 * atr)
        elif direction == SignalType.SELL.value:
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
        gemini: Optional[PredictionResult],
        kronos_issue: Optional[str] = None,
    ) -> PredictionResult:
        """Главный предиктор (Kronos/Kairos) задает направление; остальные модели только подтверждают его."""
        predictor_type = getattr(settings, "AI_PREDICTOR", "kronos").split("#")[0].strip().lower()
        is_kairos = predictor_type == "kairos" or (kronos and "Kairos" in getattr(kronos, "reason", ""))
        name = "Kairos" if is_kairos else "Kronos"

        if not kronos:
            detail = f": {kronos_issue}" if kronos_issue else ""
            return PredictionResult(
                signal=SignalType.HOLD,
                confidence=0.0,
                reason=f"{name} unavailable{detail}",
            )

        if kronos.signal == SignalType.HOLD:
            return PredictionResult(
                signal=SignalType.HOLD,
                confidence=kronos.confidence,
                reason=f"{name} HOLD; confirmations cannot override {name}. Reason: {kronos.reason}",
            )

        confirmations = [item for item in (tech, gemini) if item and item.signal != SignalType.HOLD]
        aligned = sum(item.confidence for item in confirmations if item.signal == kronos.signal)
        opposed = sum(item.confidence for item in confirmations if item.signal != kronos.signal)
        confirmation_score = (aligned - opposed) / max(len(confirmations), 1)
        final_confidence = min(max(0.7 * kronos.confidence + 0.3 * max(confirmation_score, 0.0), 0.0), 0.99)

        threshold = float(getattr(settings, "CONFIDENCE_THRESHOLD", 0.65))
        if final_confidence < threshold:
            return PredictionResult(
                signal=SignalType.HOLD,
                confidence=final_confidence,
                reason=f"{name} direction below confidence threshold ({final_confidence:.2f} < {threshold:.2f})",
            )

        return PredictionResult(
            signal=kronos.signal,
            confidence=final_confidence,
            reason=f"{name} primary; confirmations: " + "; ".join(item.reason for item in confirmations[:2]),
        )

    def _apply_risk_levels(
        self,
        signal: PredictionResult,
        candles_df: pd.DataFrame,
        symbol: str,
        *sources: Optional[PredictionResult],
    ) -> PredictionResult:
        """Сохранить уровни источника и не допустить слишком тесный SL."""
        if signal.signal == SignalType.HOLD:
            return signal

        price = float(candles_df["close"].iloc[-1])
        atr = TechnicalAnalysis._atr(candles_df, 14)
        minimum_sl_distance = max(
            atr * float(settings.MIN_SL_ATR_MULTIPLIER),
            price * 0.0005,
        )
        direction = 1 if signal.signal == SignalType.BUY else -1
        source = next((item for item in sources if item and item.signal == signal.signal), None)

        levels = source.target_price if source else None
        if isinstance(levels, dict):
            target = levels.get("target")
            take_profit = levels.get("tp")
            stop_loss = levels.get("sl")
        else:
            target = levels
            take_profit = source.take_profit if source else None
            stop_loss = source.stop_loss if source else None

        if not isinstance(target, (int, float)):
            target = None
        if not isinstance(take_profit, (int, float)):
            take_profit = target
        if not isinstance(stop_loss, (int, float)):
            stop_loss = None

        if target is None or (target - price) * direction <= 0:
            target = price + direction * max(
                2.0 * atr,
                minimum_sl_distance * float(settings.FORECAST_RISK_REWARD),
            )
        if take_profit is None or (take_profit - price) * direction <= 0:
            take_profit = target
        if stop_loss is None or (price - stop_loss) * direction < minimum_sl_distance:
            stop_loss = price - direction * minimum_sl_distance

        return PredictionResult(
            signal=signal.signal,
            confidence=signal.confidence,
            reason=signal.reason,
            target_price=round(float(target), 5),
            stop_loss=round(float(stop_loss), 5),
            take_profit=round(float(take_profit), 5),
        )

    def clear_cache(self):
        """РћС‡РёСЃС‚РёС‚СЊ РєСЌС€."""
        self._cache.clear()
        logger.info("AI prediction cache cleared")


# ==================== Singleton ====================
_ai_engine = None


def get_ai_engine() -> AIEngine:
    global _ai_engine
    if _ai_engine is None:
        _ai_engine = AIEngine()
    return _ai_engine
