"""Тесты адаптивного анализа и независимого мониторинга позиций."""

import unittest
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd

from config.settings import settings
from engine.models import PredictionResult, SignalType
from trader.trading_loop import TradingLoop


def candles_with_range(recent_range: float) -> pd.DataFrame:
    count = 120
    ranges = np.full(count, 1.0)
    ranges[-14:] = recent_range
    close = np.linspace(100.0, 110.0, count)
    return pd.DataFrame({
        "high": close + ranges / 2,
        "low": close - ranges / 2,
        "close": close,
    })


class TestTradingLoop(unittest.TestCase):
    def test_parse_symbols_normalizes_and_deduplicates(self):
        self.assertEqual(
            TradingLoop._parse_symbols(" btcusd, XAUUSD, BTCUSD, "),
            ["BTCUSD", "XAUUSD"],
        )

    def test_normal_activity_keeps_default_interval(self):
        self.assertEqual(
            TradingLoop._analysis_interval_for_activity(candles_with_range(1.0)),
            float(settings.ANALYSIS_INTERVAL_MIN),
        )

    def test_high_activity_reaches_minimum_interval(self):
        self.assertEqual(
            TradingLoop._analysis_interval_for_activity(candles_with_range(2.0)),
            float(settings.MIN_ANALYSIS_INTERVAL_MIN),
        )

    def test_minimum_sl_distance_uses_recent_true_range(self):
        distance = TradingLoop._minimum_sl_distance(candles_with_range(2.0))
        self.assertAlmostEqual(distance, 2.0 * settings.MIN_SL_ATR_MULTIPLIER)


class TestTradingLoopMultiSymbol(unittest.IsolatedAsyncioTestCase):
    async def test_cycle_processes_each_configured_symbol(self):
        trading_loop = TradingLoop()
        trading_loop._symbols = ["BTCUSD", "XAUUSD"]
        processed_symbols = []

        async def process_current_symbol():
            processed_symbols.append(trading_loop._current_symbol)

        trading_loop._trading_cycle_for_symbol = AsyncMock(side_effect=process_current_symbol)

        await trading_loop._trading_cycle()

        self.assertEqual(processed_symbols, ["BTCUSD", "XAUUSD"])
        self.assertEqual(trading_loop._total_cycles, 1)

    async def test_hold_analysis_updates_status(self):
        trading_loop = TradingLoop()
        trading_loop.mt5 = MagicMock()
        trading_loop.mt5.is_connected = True
        trading_loop.mt5.get_candles = lambda **kwargs: candles_with_range(1.0)
        trading_loop.ai.analyze = lambda **kwargs: PredictionResult(
            signal=SignalType.HOLD,
            confidence=0.32,
            reason="Kronos consolidation",
        )

        await trading_loop._trading_cycle_for_symbol()

        status = trading_loop.status
        self.assertEqual(status["signals_generated"], 1)
        self.assertEqual(status["last_signal"], "HOLD")
        self.assertEqual(status["last_confidence"], 0.32)
        self.assertEqual(status["last_reason"], "Kronos consolidation")
        self.assertEqual(status["last_candle_count"], 120)
        self.assertIsNotNone(status["last_analysis_at"])


if __name__ == "__main__":
    unittest.main()
