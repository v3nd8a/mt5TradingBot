"""Unit tests для AI Engine (Kronos + Technical Analysis + Cache)."""

import unittest
import numpy as np
import pandas as pd

from engine.models import SignalType, PredictionResult, TechnicalIndicators
from engine.ai import TechnicalAnalysis, PredictionCache, AIEngine
from engine.kronos import KronosDataPreprocessor, KronosPredictor, get_kronos_predictor


def create_sample_candles(n: int = 250, trend: str = "bullish") -> pd.DataFrame:
    """Создать синтетический датасет свечей для тестирования."""
    dates = pd.date_range("2025-01-01", periods=n, freq="h")
    if trend == "bullish":
        base = np.linspace(1.1000, 1.1500, n)
    elif trend == "bearish":
        base = np.linspace(1.1500, 1.1000, n)
    else:
        base = np.full(n, 1.1200)

    noise = np.random.RandomState(42).randn(n) * 0.0005
    closes = base + noise
    opens = closes - 0.0003 if trend == "bullish" else closes + 0.0003
    highs = np.maximum(opens, closes) + 0.0005
    lows = np.minimum(opens, closes) - 0.0005
    volumes = np.random.RandomState(42).randint(100, 1000, n)

    return pd.DataFrame({
        "time": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


class TestTechnicalAnalysis(unittest.TestCase):
    """Тестирование расчета технических индикаторов."""

    def test_compute_indicators_on_sufficient_data(self):
        df = create_sample_candles(250)
        indicators = TechnicalAnalysis.compute(df, "EURUSD")

        self.assertIsInstance(indicators, TechnicalIndicators)
        self.assertGreater(indicators.current_price, 0)
        self.assertIsNotNone(indicators.sma_20)
        self.assertIsNotNone(indicators.sma_50)
        self.assertIsNotNone(indicators.sma_200)
        self.assertIsNotNone(indicators.rsi_14)
        self.assertTrue(0 <= indicators.rsi_14 <= 100)
        self.assertIsNotNone(indicators.atr_14)
        self.assertGreater(indicators.atr_14, 0)

    def test_compute_insufficient_data(self):
        df = create_sample_candles(50)
        indicators = TechnicalAnalysis.compute(df, "EURUSD")
        self.assertIsInstance(indicators, TechnicalIndicators)


class TestKronosPredictor(unittest.TestCase):
    """Тестирование Kronos AI модуля."""

    def setUp(self):
        self.predictor = get_kronos_predictor()

    def test_preprocessor_features(self):
        df = create_sample_candles(60)
        features = KronosDataPreprocessor.preprocess(df)
        self.assertIsNotNone(features)
        self.assertEqual(len(features.body_pct), 60)
        self.assertEqual(len(features.returns), 60)
        self.assertGreater(features.volatility, 0)

    def test_preprocessor_insufficient_candles(self):
        df = create_sample_candles(10)
        features = KronosDataPreprocessor.preprocess(df)
        self.assertIsNone(features)

    def test_bullish_prediction(self):
        df = create_sample_candles(60, trend="bullish")
        result = self.predictor.predict(df, "EURUSD")
        self.assertIsNotNone(result)
        self.assertIn(result.signal, [SignalType.BUY, SignalType.HOLD])
        self.assertTrue(0.0 <= result.confidence <= 1.0)
        if result.signal == SignalType.BUY:
            self.assertIsNotNone(result.stop_loss)
            self.assertIsNotNone(result.take_profit)
            self.assertLess(result.stop_loss, df.iloc[-1]["close"])
            self.assertGreater(result.take_profit, df.iloc[-1]["close"])

    def test_bearish_prediction(self):
        df = create_sample_candles(60, trend="bearish")
        result = self.predictor.predict(df, "EURUSD")
        self.assertIsNotNone(result)
        self.assertIn(result.signal, [SignalType.SELL, SignalType.HOLD])
        if result.signal == SignalType.SELL:
            self.assertIsNotNone(result.stop_loss)
            self.assertIsNotNone(result.take_profit)
            self.assertGreater(result.stop_loss, df.iloc[-1]["close"])
            self.assertLess(result.take_profit, df.iloc[-1]["close"])


class TestPredictionCache(unittest.TestCase):
    """Тестирование кэширования сигналов."""

    def test_cache_put_and_get(self):
        cache = PredictionCache(max_size=3, ttl_sec=60)
        res = PredictionResult(signal=SignalType.BUY, confidence=0.8, reason="Test")
        cache.put("EURUSD_1.10_BUY", res)

        cached = cache.get("EURUSD_1.10_BUY")
        self.assertIsNotNone(cached)
        self.assertEqual(cached.signal, SignalType.BUY)
        self.assertEqual(cached.confidence, 0.8)

    def test_cache_lru_eviction(self):
        cache = PredictionCache(max_size=2, ttl_sec=60)
        res1 = PredictionResult(signal=SignalType.BUY, confidence=0.7)
        res2 = PredictionResult(signal=SignalType.SELL, confidence=0.8)
        res3 = PredictionResult(signal=SignalType.HOLD, confidence=0.5)

        cache.put("k1", res1)
        cache.put("k2", res2)
        cache.put("k3", res3)

        self.assertIsNone(cache.get("k1"))
        self.assertIsNotNone(cache.get("k2"))
        self.assertIsNotNone(cache.get("k3"))


class TestAIEngine(unittest.TestCase):
    """Тестирование основного движка AIEngine."""

    def setUp(self):
        self.engine = AIEngine()

    def test_analyze_pipeline(self):
        df = create_sample_candles(250, trend="bullish")
        result = self.engine.analyze(df, "EURUSD", use_gemini=False)
        self.assertIsInstance(result, PredictionResult)
        self.assertIn(result.signal, [SignalType.BUY, SignalType.SELL, SignalType.HOLD])
        self.assertTrue(0.0 <= result.confidence <= 1.0)
        self.assertTrue(len(result.reason) > 0)


if __name__ == "__main__":
    unittest.main()
