"""Unit tests для OrderExecutor (исполнение ордеров, управление рисками и rate limiting)."""

import unittest
from unittest.mock import MagicMock, patch
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

    def test_execute_rejects_when_account_sell_half_limit_reached_even_with_zero_buy_positions(self):
        # 10 позиций SELL из 20 возможных всего (половина выделена под SELL). 0 позиций BUY.
        self.mock_mt5.get_positions.return_value = [
            {"symbol": f"SYM_{i}", "type": "SELL", "volume": 0.1}
            for i in range(settings.max_sell_positions)
        ]

        sell_req = OrderRequest(symbol="EURUSD", direction="SELL", volume=0.1, reason="Test Sell")
        res_sell = self.executor.execute(sell_req)
        self.assertIsNone(res_sell)
        self.mock_mt5.send_market_order.assert_not_called()

        # При этом BUY ордер должен успешно исполняться
        buy_req = OrderRequest(symbol="EURUSD", direction="BUY", volume=0.1, reason="Test Buy")
        res_buy = self.executor.execute(buy_req)
        self.assertIsNotNone(res_buy)
        self.mock_mt5.send_market_order.assert_called_once()

    def test_execute_rejects_when_symbol_direction_limit_reached(self):
        # Достигнут лимит SELL для конкретного символа EURUSD
        self.mock_mt5.get_positions.return_value = [
            {"symbol": "EURUSD", "type": "SELL", "volume": 0.1}
            for _ in range(settings.max_sell_positions_per_symbol)
        ]

        sell_req = OrderRequest(symbol="EURUSD", direction="SELL", volume=0.1, reason="Test Sell")
        res_sell = self.executor.execute(sell_req)
        self.assertIsNone(res_sell)
        self.mock_mt5.send_market_order.assert_not_called()

        # BUY для этого же символа должен исполняться, пока есть лимит BUY
        buy_req = OrderRequest(symbol="EURUSD", direction="BUY", volume=0.1, reason="Test Buy")
        res_buy = self.executor.execute(buy_req)
        self.assertIsNotNone(res_buy)
        self.mock_mt5.send_market_order.assert_called_once()

    @patch("connector.mt5.mt5_module")
    def test_mt5_close_position_sends_position_ticket_and_broker_filling(self, mock_mt5_module):
        from connector.mt5 import MT5Connector
        connector = MT5Connector()
        connector.get_positions = MagicMock(return_value=[
            {"ticket": 777, "symbol": "XAUUSD", "type": "BUY", "volume": 0.05}
        ])
        mock_info = MagicMock()
        mock_info.bid = 2000.50
        mock_info.ask = 2000.80
        mock_info.digits = 2
        mock_info.filling_mode = 2  # IOC
        mock_mt5_module.symbol_info.return_value = mock_info
        mock_order_result = MagicMock()
        mock_order_result.retcode = 10009  # TRADE_RETCODE_DONE
        mock_mt5_module.order_send.return_value = mock_order_result
        mock_mt5_module.TRADE_RETCODE_DONE = 10009
        mock_mt5_module.TRADE_ACTION_DEAL = 1
        mock_mt5_module.ORDER_TYPE_SELL = 1
        mock_mt5_module.ORDER_FILLING_IOC = 1

        closed = connector.close_all_positions("XAUUSD", ticket=777)
        self.assertEqual(closed, 1)
        mock_mt5_module.order_send.assert_called_once()
        req = mock_mt5_module.order_send.call_args[0][0]
        # Главная проверка: тикет ОБЯЗАН быть в поле position запроса
        self.assertEqual(req["position"], 777)
        self.assertEqual(req["symbol"], "XAUUSD")
        self.assertEqual(req["volume"], 0.05)
        self.assertEqual(req["type_filling"], 1)


if __name__ == "__main__":
    unittest.main()
