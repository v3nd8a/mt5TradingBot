import unittest

from db.engine import _sync_database_url


class TestSyncDatabaseUrl(unittest.TestCase):
    def test_psycopg2_dsn_uses_pg8000(self):
        url = _sync_database_url("postgresql+psycopg2://user:secret@localhost:5432/trading_db")
        self.assertEqual(url.drivername, "postgresql+pg8000")

    def test_plain_postgresql_dsn_uses_pg8000(self):
        url = _sync_database_url("postgresql://user:secret@localhost:5432/trading_db")
        self.assertEqual(url.drivername, "postgresql+pg8000")


if __name__ == "__main__":
    unittest.main()