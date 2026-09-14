"""Unit tests для модулей Analytics и Security (Этапы P1, P2)."""

import unittest
import os
from pathlib import Path

from config.security import mask_secret, SecretVault
from analytics.reporter import PerformanceMetrics, ReportGenerator


class TestSecurity(unittest.TestCase):
    """Тестирование маскирования и шифрования."""

    def test_mask_secret(self):
        masked = mask_secret("xpl_b30f5afa8e1919d0b189c834dff1865825cf5c2d", 4, 4)
        self.assertTrue(masked.startswith("xpl_"))
        self.assertTrue(masked.endswith("5c2d"))
        self.assertIn("****", masked)

    def test_secret_vault_encryption_decryption(self):
        vault = SecretVault("custom_test_key_12345")
        original = "super_secret_mt5_password_987"
        encrypted = vault.encrypt(original)

        self.assertNotEqual(original, encrypted)
        decrypted = vault.decrypt(encrypted)
        self.assertEqual(original, decrypted)


class TestAnalytics(unittest.TestCase):
    """Тестирование расчета метрик и отчетов."""

    def setUp(self):
        self.trades = [
            {"symbol": "EURUSD", "profit": 150.0, "volume": 0.1},
            {"symbol": "EURUSD", "profit": -50.0, "volume": 0.1},
            {"symbol": "EURUSD", "profit": 200.0, "volume": 0.1},
            {"symbol": "EURUSD", "profit": -80.0, "volume": 0.1},
        ]

    def test_performance_metrics(self):
        metrics = PerformanceMetrics.calculate(self.trades)
        self.assertEqual(metrics["total_trades"], 4)
        self.assertEqual(metrics["profitable_trades"], 2)
        self.assertEqual(metrics["loss_trades"], 2)
        self.assertEqual(metrics["win_rate_pct"], 50.0)
        self.assertEqual(metrics["net_profit"], 220.0)
        self.assertGreater(metrics["profit_factor"], 1.0)

    def test_generate_text_summary(self):
        metrics = PerformanceMetrics.calculate(self.trades)
        summary = ReportGenerator.generate_text_summary(metrics)
        self.assertIn("Всего сделок", summary)
        self.assertIn("Чистый P&L", summary)

    def test_export_to_csv(self):
        csv_path = "logs/test_trades.csv"
        success = ReportGenerator.export_to_csv(self.trades, csv_path)
        self.assertTrue(success)
        self.assertTrue(os.path.exists(csv_path))
        if os.path.exists(csv_path):
            os.remove(csv_path)

    def test_plot_portfolio_equity(self):
        chart_path = "logs/test_chart.png"
        equity = [10000.0, 10150.0, 10100.0, 10300.0, 10220.0]
        success = ReportGenerator.plot_portfolio_equity(equity, output_path=chart_path)
        self.assertTrue(success)
        self.assertTrue(os.path.exists(chart_path))
        if os.path.exists(chart_path):
            os.remove(chart_path)


if __name__ == "__main__":
    unittest.main()
