"""Unit tests для AI Engine (Kronos + Technical Analysis + Cache)."""

import unittest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd

from config.settings import settings
from engine.models import SignalType, PredictionResult, TechnicalIndicators
from engine.ai import TechnicalAnalysis, PredictionCache, AIEngine
from engine.kronos import KronosPredictor


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
        self.predictor = KronosPredictor()
        self.predictor._predictor = MagicMock()
        self.forecast_delta = 0.01
        self.predictor._predictor.predict.side_effect = self._mock_forecast

    def _mock_forecast(self, df, y_timestamp, pred_len, **kwargs):
        current = float(df["close"].iloc[-1])
        closes = current + np.linspace(
            self.forecast_delta / pred_len,
            self.forecast_delta,
            pred_len,
        )
        return pd.DataFrame({"close": closes}, index=y_timestamp)

    def test_forecast_rejects_missing_required_columns(self):
        df = create_sample_candles(60).drop(columns=["time"])
        self.assertIsNone(self.predictor.predict(df, "EURUSD"))
        self.predictor._predictor.predict.assert_not_called()

    def test_forecast_rejects_empty_candles(self):
        self.assertIsNone(self.predictor.predict(pd.DataFrame(), "EURUSD"))
        self.predictor._predictor.predict.assert_not_called()

    def test_loads_configured_pretrained_model_and_tokenizer_once(self):
        upstream_root = Path(__file__).resolve().parents[1] / "vendor" / "Kronos"
        with patch.object(sys, "path", [str(upstream_root), *sys.path]):
            import model as official_model

        loaded_predictor = MagicMock()
        with (
            patch.object(
                official_model.KronosTokenizer,
                "from_pretrained",
                return_value=MagicMock(),
            ) as load_tokenizer,
            patch.object(
                official_model.Kronos,
                "from_pretrained",
                return_value=MagicMock(),
            ) as load_model,
            patch.object(
                official_model,
                "KronosPredictor",
                return_value=loaded_predictor,
            ) as create_predictor,
            patch("torch.cuda.is_available", return_value=True),
        ):
            predictor = KronosPredictor()
            predictor._ensure_model_loaded()
            predictor._ensure_model_loaded()

        load_tokenizer.assert_called_once_with(settings.KRONOS_TOKENIZER_NAME)
        load_model.assert_called_once_with(settings.KRONOS_MODEL_NAME)
        create_predictor.assert_called_once()
        self.assertEqual(create_predictor.call_args.kwargs["device"], "cuda")
        self.assertEqual(
            create_predictor.call_args.kwargs["max_context"],
            settings.KRONOS_MAX_CONTEXT,
        )

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
        self.forecast_delta = -0.01
        df = create_sample_candles(60, trend="bearish")
        result = self.predictor.predict(df, "EURUSD")
        self.assertEqual(result.signal, SignalType.SELL)
        self.assertIsNotNone(result.stop_loss)
        self.assertIsNotNone(result.take_profit)
        self.assertGreater(result.stop_loss, df.iloc[-1]["close"])
        self.assertLess(result.take_profit, df.iloc[-1]["close"])

    def test_prediction_with_horizon(self):
        df = create_sample_candles(120, trend="bullish")
        result = self.predictor.predict(df, "EURUSD", horizon=10)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.target_price)
        self.assertGreater(result.target_price, df.iloc[-1]["close"])
        self.assertIn("10 candles", result.reason)
        self.predictor._predictor.predict.assert_called_once()
        call_kwargs = self.predictor._predictor.predict.call_args.kwargs
        self.assertEqual(call_kwargs["pred_len"], 10)
        self.assertEqual(len(call_kwargs["y_timestamp"]), 10)
        self.assertLessEqual(len(call_kwargs["df"]), settings.KRONOS_MAX_CONTEXT)

    def test_prediction_stop_respects_atr_distance(self):
        df = create_sample_candles(120, trend="bullish")
        result = self.predictor.predict(df, "XAUUSD", horizon=10)
        if result.signal == SignalType.BUY:
            atr = (df["high"] - df["low"]).tail(14).mean()
            self.assertGreaterEqual(df.iloc[-1]["close"] - result.stop_loss, atr * settings.MIN_SL_ATR_MULTIPLIER)

    def test_kronos_target_is_forecast_distance(self):
        df = create_sample_candles(120, trend="bullish")
        result = self.predictor.predict(df, "XAUUSD", horizon=10)
        if result.signal == SignalType.BUY:
            self.assertGreater(result.take_profit, result.target_price - 0.01)
            self.assertGreaterEqual(df.iloc[-1]["close"] - result.stop_loss, 0.0)

    def test_horizon_evaluation_is_walk_forward(self):
        report = self.predictor.evaluate_horizons(
            create_sample_candles(100, trend="bullish"),
            "EURUSD",
            horizons=(1, 5),
        )
        self.assertEqual(set(report), {1, 5})
        for metrics in report.values():
            self.assertIn("directional_accuracy", metrics)
            self.assertIn("profit_factor", metrics)
            self.assertLessEqual(metrics["coverage"], 1.0)

    def test_confidence_calibration_compares_predictions_to_outcomes(self):
        report = self.predictor.calibrate_confidence(
            create_sample_candles(100, trend="bullish"),
            "EURUSD",
            horizon=1,
        )
        self.assertTrue(report)
        for bucket in report:
            self.assertIn("average_confidence", bucket)
            self.assertIn("observed_win_rate", bucket)
            self.assertIn("calibration_error", bucket)

    def test_calibrated_confidence_uses_observed_win_rate(self):
        confidence, samples = self.predictor.calibrated_confidence(
            0.9,
            create_sample_candles(100, trend="bullish"),
            "EURUSD",
            horizon=1,
            min_samples=5,
        )
        self.assertGreater(samples, 0)
        self.assertGreaterEqual(confidence, 0.0)
        self.assertLessEqual(confidence, 0.99)


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
        kronos = PredictionResult(
            signal=SignalType.BUY,
            confidence=0.8,
            reason="pretrained forecast",
            target_price=float(df["close"].iloc[-1]) + 0.01,
        )
        with patch.object(self.engine, "_predict_with_kronos", return_value=kronos):
            result = self.engine.analyze(df, "EURUSD", use_gemini=False)
        self.assertIsInstance(result, PredictionResult)
        self.assertIn(result.signal, [SignalType.BUY, SignalType.SELL, SignalType.HOLD])
        self.assertTrue(0.0 <= result.confidence <= 1.0)
        self.assertTrue(len(result.reason) > 0)
        self.assertNotIn("calibrated from", result.reason)

    def test_threshold_hard_gate(self):
        original = settings.CONFIDENCE_THRESHOLD
        settings.CONFIDENCE_THRESHOLD = 0.9
        try:
            weak_tech = PredictionResult(signal=SignalType.BUY, confidence=0.4, reason="weak")
            weak_kronos = PredictionResult(signal=SignalType.BUY, confidence=0.45, reason="Kronos AI: bullish | forecast for 10 candles ahead")
            result = self.engine._combine_signals(weak_tech, weak_kronos, None)
            self.assertEqual(result.signal, SignalType.HOLD)
            self.assertLess(result.confidence, settings.CONFIDENCE_THRESHOLD)
        finally:
            settings.CONFIDENCE_THRESHOLD = original

    def test_threshold_zero_allows_any_signal(self):
        original = settings.CONFIDENCE_THRESHOLD
        settings.CONFIDENCE_THRESHOLD = 0.0
        try:
            signal = PredictionResult(signal=SignalType.BUY, confidence=0.55, reason="ready")
            self.assertTrue(signal.is_actionable)
        finally:
            settings.CONFIDENCE_THRESHOLD = original

    def test_kronos_direction_cannot_be_overridden(self):
        kronos = PredictionResult(
            signal=SignalType.SELL,
            confidence=0.90,
            reason="Kronos bearish",
            target_price=4300.0,
            stop_loss=4380.0,
            take_profit=4300.0,
        )
        tech = PredictionResult(signal=SignalType.BUY, confidence=0.99, reason="Technical bullish")
        result = self.engine._combine_signals(tech, kronos, None)
        self.assertEqual(result.signal, SignalType.SELL)

    def test_kronos_hold_blocks_other_buy_signal(self):
        kronos = PredictionResult(signal=SignalType.HOLD, confidence=0.8, reason="Kronos consolidation")
        tech = PredictionResult(signal=SignalType.BUY, confidence=0.99, reason="Technical bullish")
        result = self.engine._combine_signals(tech, kronos, None)
        self.assertEqual(result.signal, SignalType.HOLD)
        self.assertIn("Kronos consolidation", result.reason)

    def test_unavailable_kronos_includes_load_failure_reason(self):
        tech = PredictionResult(signal=SignalType.HOLD, confidence=0.0, reason="neutral")
        result = self.engine._combine_signals(
            tech,
            None,
            None,
            kronos_issue="failed to load pretrained checkpoint",
        )
        self.assertEqual(result.signal, SignalType.HOLD)
        self.assertIn("failed to load pretrained checkpoint", result.reason)

    def test_ollama_prompt_contains_kronos_context(self):
        indicators = TechnicalIndicators(symbol="XAUUSD", current_price=4300.0)
        kronos = PredictionResult(
            signal=SignalType.BUY,
            confidence=0.8,
            target_price=4400.0,
            stop_loss=4260.0,
            take_profit=4400.0,
        )
        prompt = self.engine._build_ollama_prompt("XAUUSD", indicators, [], kronos)
        self.assertIn("ВЫВОД KRONOS", prompt)
        self.assertIn("4400.0", prompt)


if __name__ == "__main__":
    unittest.main()
