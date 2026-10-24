"""Unit tests для OrderExecutor (исполнение ордеров, управление рисками и rate limiting)."""

import unittest
from unittest.mock import MagicMock
import time

from config.settings import settings
from engine.models import PredictionResult, SignalType
from trader.order_executor import OrderExecutor, OrderRequest


class TestOrderExecutor(unittest.TestCase):
    """Тестирование OrderExecutor."""

    def setUp(self):
        self.mock_mt5 = MagicMock()
        self.mock_mt5.is_connected = True
        self.mock_mt5.get_account_info.return_value = {
            "login": 123456,
            "server": "DemoServer",
            "balance": 10000.0,
            "equity": 10000.0,
            "margin": 0.0,
            "free_margin": 10000.0,
            "profit": 0.0,
            "margin_level": 0.0,
            "trade_mode": 0,
        }
        self.mock_mt5.get_positions.return_value = []
        self.mock_mt5.send_market_order.return_value = {
            "retcode": 10009,
            "order": 99999,
            "deal": 88888,
            "price": 1.1000,
            "volume": 0.1,
        }

        self.executor = OrderExecutor(self.mock_mt5)

    def test_can_trade_connected(self):
        self.assertTrue(self.executor.can_trade)

    def test_cannot_trade_disconnected(self):
        self.mock_mt5.is_connected = False
        self.assertFalse(self.executor.can_trade)

    def test_rate_limiting(self):
        self.executor._order_count_window = []
        # settings.MAX_ORDERS_PER_MIN = 3
        self.assertTrue(self.executor._check_rate_limit())
        self.assertTrue(self.executor._check_rate_limit())
        self.assertTrue(self.executor._check_rate_limit())
        # Четвертый ордер в течение минуты должен быть заблокирован
        self.assertFalse(self.executor._check_rate_limit())

    def test_plan_order_actionable_signal(self):
        # Порог confidence = 0.65
        signal = PredictionResult(
            signal=SignalType.BUY,
            confidence=0.80,
            reason="Strong bullish momentum",
            stop_loss=1.0950,
            take_profit=1.1100,
        )
        self.mock_mt5.get_positions.return_value = []

        with unittest.mock.patch.object(self.executor, "_get_current_price", return_value=1.1000):
            order = self.executor.plan_order(signal, "EURUSD")
            self.assertIsNotNone(order)
            self.assertEqual(order.symbol, "EURUSD")
            self.assertEqual(order.direction, "BUY")
            self.assertEqual(order.sl_price, 1.0950)
            self.assertEqual(order.tp_price, 1.1100)

    def test_plan_order_hold_signal_not_actionable(self):
        signal = PredictionResult(
            signal=SignalType.HOLD,
            confidence=0.20,
            reason="Consolidation",
        )
        order = self.executor.plan_order(signal, "EURUSD")
        self.assertIsNone(order)

    def test_plan_order_uses_forecast_distance(self):
        signal = PredictionResult(
            signal=SignalType.BUY,
            confidence=0.80,
            target_price=1.1200,
            reason="Forecast target",
        )
        with unittest.mock.patch.object(self.executor, "_get_current_price", return_value=1.1000):
            order = self.executor.plan_order(signal, "EURUSD")
        self.assertEqual(order.tp_price, 1.12)
        self.assertEqual(order.sl_price, 1.09)

    def test_trailing_stop_moves_only_in_profit(self):
        position = {
            "ticket": 1, "symbol": "EURUSD", "type": "BUY", "volume": 0.1,
            "price_open": 1.1000, "price_current": 1.1100, "sl": 1.1010, "tp": 1.1300,
        }
        self.mock_mt5.get_positions.return_value = [position]
        with unittest.mock.patch("MetaTrader5.symbol_info", return_value=unittest.mock.Mock(point=0.0001)):
            result = self.executor.manage_open_positions("EURUSD")
        self.assertEqual(result["trailed"], 1)
        self.mock_mt5.modify_position.assert_called_once()

    def test_existing_tight_stop_is_widened(self):
        position = {
            "ticket": 2, "symbol": "XAUUSD", "type": "BUY", "volume": 0.1,
            "price_open": 4340.0, "price_current": 4348.0, "sl": 4347.0, "tp": 4380.0,
        }
        self.mock_mt5.get_positions.return_value = [position]
        with unittest.mock.patch("MetaTrader5.symbol_info", return_value=unittest.mock.Mock(point=0.01)):
            result = self.executor.manage_open_positions("XAUUSD", minimum_sl_distance=29.5)
        self.assertEqual(result["trailed"], 1)
        self.mock_mt5.modify_position.assert_called_once_with(2, 4318.5, 4380.0)

    def test_execute_allows_same_direction_position(self):
        req = OrderRequest(
            symbol="EURUSD",
            direction="BUY",
            volume=0.1,
            sl_price=1.0900,
            tp_price=1.1100,
            reason="Test",
        )
        # Имитируем существующую BUY позицию
        self.mock_mt5.get_positions.return_value = [
            {"symbol": "EURUSD", "type": "BUY", "volume": 0.1}
        ]

        result = self.executor.execute(req)
        self.assertIsNotNone(result)
        self.mock_mt5.send_market_order.assert_called_once()

    def test_execute_rejects_when_symbol_position_limit_reached(self):
        req = OrderRequest(
            symbol="EURUSD",
            direction="SELL",
            volume=0.1,
            reason="Test",
        )
        self.mock_mt5.get_positions.return_value = [
            {"symbol": "EURUSD", "type": "BUY", "volume": 0.1}
            for _ in range(settings.MAX_POSITIONS_PER_SYMBOL)
        ]

        result = self.executor.execute(req)
        self.assertIsNone(result)
        self.mock_mt5.send_market_order.assert_not_called()

    def test_hedges_do_not_count_toward_position_limits(self):
        req = OrderRequest(
            symbol="EURUSD",
            direction="SELL",
            volume=0.1,
            reason="Test",
        )
        self.mock_mt5.get_positions.return_value = [
            {"symbol": "EURUSD", "type": "BUY", "volume": 0.1, "comment": "Kronos HEDGE"}
            for _ in range(settings.MAX_POSITIONS)
        ]

        result = self.executor.execute(req)
        self.assertIsNotNone(result)
        self.mock_mt5.send_market_order.assert_called_once()

    def test_execute_rejects_when_account_position_limit_reached(self):
        req = OrderRequest(
            symbol="EURUSD",
            direction="BUY",
            volume=0.1,
            reason="Test",
        )
        self.mock_mt5.get_positions.return_value = [
            {"symbol": "GBPUSD", "type": "BUY", "volume": 0.1}
            for _ in range(settings.MAX_POSITIONS)
        ]

        result = self.executor.execute(req)
        self.assertIsNone(result)
        self.mock_mt5.send_market_order.assert_not_called()

    def test_close_on_reversal_closes_only_opposite_positions(self):
        signal = PredictionResult(signal=SignalType.BUY, confidence=0.8, reason="Kronos reversal")
        self.mock_mt5.get_positions.return_value = [
            {"ticket": 11, "symbol": "XAUUSD", "type": "SELL", "volume": 0.1},
            {"ticket": 12, "symbol": "XAUUSD", "type": "BUY", "volume": 0.1},
        ]
        self.mock_mt5.close_all_positions.return_value = 1
        closed = self.executor.close_on_reversal(signal, "XAUUSD")
        self.assertEqual(closed, 1)
        self.mock_mt5.close_all_positions.assert_called_once_with("XAUUSD", ticket=11)

    def test_hold_does_not_close_positions(self):
        signal = PredictionResult(signal=SignalType.HOLD, confidence=0.9, reason="Kronos HOLD")
        self.assertEqual(self.executor.close_on_reversal(signal, "XAUUSD"), 0)
        self.mock_mt5.get_positions.assert_not_called()

    def test_execute_in_demo_mode(self):
        original_simulation = settings.MT5_SIMULATION_MODE
        try:
            settings.MT5_SIMULATION_MODE = True
            req = OrderRequest(
                symbol="EURUSD",
                direction="BUY",
                volume=0.1,
                sl_price=1.0900,
                tp_price=1.1100,
                reason="Test Demo",
            )
            self.mock_mt5.get_positions.return_value = []
            res = self.executor.execute(req)
            self.assertIsNotNone(res)
            self.assertTrue(res.get("demo", False))
        finally:
            settings.MT5_SIMULATION_MODE = original_simulation


if __name__ == "__main__":
    unittest.main()
