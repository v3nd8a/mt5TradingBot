"""Unit tests для config/settings."""

import unittest
from config.settings import settings


class TestSettings(unittest.TestCase):
    """Проверки конфигурации."""

    def test_mt5_settings_exist(self):
        self.assertTrue(settings.MT5_LOGIN, "MT5_LOGIN must be set")
        self.assertTrue(settings.MT5_PASSWORD, "MT5_PASSWORD must be set")
        self.assertTrue(settings.MT5_SERVER, "MT5_SERVER must be set")

    def test_gemini_key_present(self):
        self.assertTrue(settings.GEMINI_API_KEY, "GEMINI_API_KEY must be set")

    def test_db_dsn_valid(self):
        self.assertIn("://", settings.DB_DSN)
        self.assertIn("@", settings.DB_DSN)

    def test_risk_params(self):
        self.assertGreater(settings.RISK_PER_TRADE_PCT, 0)
        self.assertGreater(settings.DEFAULT_SL_PIPS, 0)
        self.assertEqual(DEFAULT_TP_PIPS, 0)


class TestTradingConfig(unittest.TestCase):
    """Проверки торговой конфигурации."""

    def test_confidence_threshold(self):
        self.assertAlmostEqual(0.65 <= settings.CONFIDENCE_THRESHOLD <= 1.0)

    def test_max_positions(self):
        self.assertGreaterEqual(settings.MAX_POSITIONS, 1)


if __name__ == "__main__":
    unittest.main()
