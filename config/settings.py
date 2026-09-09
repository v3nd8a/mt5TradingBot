"""Конфигурация приложения через pydantic-settings из .env."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ==================== MT5 ====================
    MT5_LOGIN: str
    MT5_PASSWORD: str
    MT5_SERVER: str
    MT5_PATH: str = "C:/Program Files/MetaTrader 5/terminal64.exe"
    
    # Демо режим (true = только чтение сигналов, без ордеров)
    MT5_DEMO_MODE: bool = False

    # ==================== Gemini / AI ====================
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-2.0-flash"
    USE_KRONOS_LOCAL: bool = True  # локальная модель Kronos
    USE_GEMINI_FALLBACK: bool = True  # fallback на Gemini если Kronos упал

    # ==================== Database ====================
    DB_DSN: str = "postgresql+psycopg2://postgres:password@localhost:5432/trading_db"

    # ==================== Trading ====================
    DEFAULT_SYMBOL: str = "EURUSD"
    TICK_INTERVAL_SEC: int = 5          # интервал опроса тиков
    ANALYSIS_INTERVAL_MIN: int = 15     # интервал анализа (минуты)
    CONFIDENCE_THRESHOLD: float = 0.65  # мин. confidence для сигнала
    MAX_POSITIONS: int = 3               # макс. открытых позиций
    
    # Risk management
    RISK_PER_TRADE_PCT: float = 1.0      # % депозита на сделку
    DEFAULT_SL_PIPS: float = 50.0        # Stop Loss в пипсах
    DEFAULT_TP_PIPS: float = 100.0       # Take Profit в пипсах
    MAX_ORDERS_PER_MIN: int = 3           # rate limiting
    
    # ==================== Bot ====================
    BOT_TOKEN: str = ""
    ADMIN_ID: str = ""

    # ==================== Logging ====================
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"
    LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB
    LOG_BACKUP_COUNT: int = 10

    # ==================== Cache ====================
    PREDICTION_CACHE_TTL_SEC: int = 300     # 5 мин кэш предсказаний
    PREDICTION_CACHE_MAX: int = 20           # макс. записей в кэше

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()


# Path helpers
BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / settings.LOG_DIR
DB_SCHEMA_PATH = BASE_DIR / "db" / "schema.sql"
