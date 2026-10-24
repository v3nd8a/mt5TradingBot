"""Конфигурация приложения через pydantic-settings из .env (с fallback на pydantic.BaseModel)."""

import os
from pathlib import Path
try:
    from dotenv import load_dotenv, dotenv_values
except ImportError:
    def load_dotenv(*args, **kwargs):
        pass

    def dotenv_values(*args, **kwargs):
        return {}

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# Единственный источник истины для порога принятия сигнала.
# Меняете эту строку — меняется порог по всему проекту.
DEFAULT_CONFIDENCE_THRESHOLD = 0.40

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Settings(BaseSettings):
        # ==================== MT5 (Real) ====================
        MT5_LOGIN: str = ""
        MT5_PASSWORD: str = ""
        MT5_SERVER: str = ""
        MT5_PATH: str = "C:/Program Files/MetaTrader 5/terminal64.exe"
        
        # Демо аккаунт (AMarkets Demo)
        MT5_DEMO_LOGIN: str = ""
        MT5_DEMO_PASSWORD: str = ""
        MT5_DEMO_SERVER: str = "AMarkets-Demo"

        # Аккаунт по умолчанию — AMarkets Demo.
        # Это не отключает реальные заявки внутри демо-счёта.
        MT5_DEMO_MODE: bool = True
        MT5_SIMULATION_MODE: bool = False

        # ==================== Ollama / AI ====================
        OLLAMA_BASE_URL: str = "http://localhost:11434"
        OLLAMA_MODEL: str = "qwen2.5-coder:7b-instruct"
        USE_OLLAMA: bool = True  # использовать Ollama для анализа
        OLLAMA_TIMEOUT: int = 60  # таймаут запроса к Ollama (сек)

        # ==================== Gemini / AI (deprecated, kept for compat) ====================
        GEMINI_API_KEY: str = ""
        GEMINI_MODEL: str = "gemini-2.5-flash"
        USE_KRONOS_LOCAL: bool = True  # локальная модель Kronos
        USE_GEMINI_FALLBACK: bool = False  # deprecated — используем Ollama вместо этого
        KRONOS_FORECAST_HORIZON: int = 10  # горизонта прогноза в свечах (10–15 обычно)
        KRONOS_HISTORY_CANDLES: int = 1000
        KRONOS_CALIBRATION_MIN_SAMPLES: int = 20

        # ==================== Database ====================
        DB_DSN: str = "postgresql+psycopg2://postgres:password@localhost:5432/trading_db"

        # ==================== Trading ====================
        DEFAULT_SYMBOL: str = "XAUUSD"
        TRADING_SYMBOLS: str = ""
        TICK_INTERVAL_SEC: int = 5          # интервал опроса тиков
        ANALYSIS_INTERVAL_MIN: int = 2     # интервал анализа (минуты)
        MIN_ANALYSIS_INTERVAL_MIN: int = 5  # минимальный интервал при высокой волатильности
        CONFIDENCE_THRESHOLD: float = DEFAULT_CONFIDENCE_THRESHOLD  # мин. confidence для сигнала
        MAX_POSITIONS: int = 20              # макс. обычных открытых позиций на счёте
        MAX_POSITIONS_PER_SYMBOL: int = 20   # макс. обычных открытых позиций на тикер
        
        # Risk management
        RISK_PER_TRADE_PCT: float = 2.0      # % депозита на сделку
        DEFAULT_SL_PIPS: float = 50.0        # Stop Loss в пипсах
        DEFAULT_TP_PIPS: float = 50.0       # Take Profit в пипсах
        FORECAST_RISK_REWARD: float = 2.0
        MIN_SL_ATR_MULTIPLIER: float = 1.5
        TRAILING_STOP_ENABLED: bool = True
        TRAILING_STOP_PIPS: float = 30.0
        TRAILING_ACTIVATION_PIPS: float = 30.0
        HEDGE_ENABLED: bool = False
        HEDGE_TRIGGER_PIPS: float = 50.0
        HEDGE_VOLUME_RATIO: float = 0.5
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
            env_file=str(ENV_PATH),
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="ignore",
        )

except ImportError:
    from pydantic import BaseModel

    class Settings(BaseModel):
        # ==================== MT5 (Real) ====================
        MT5_LOGIN: str = ""
        MT5_PASSWORD: str = ""
        MT5_SERVER: str = ""
        MT5_PATH: str = "C:/Program Files/MetaTrader 5/terminal64.exe"
        
        # Демо аккаунт (AMarkets Demo)
        MT5_DEMO_LOGIN: str = ""
        MT5_DEMO_PASSWORD: str = ""
        MT5_DEMO_SERVER: str = "AMarkets-Demo"
        MT5_DEMO_MODE: bool = True
        MT5_SIMULATION_MODE: bool = False

        # ==================== Ollama / AI ====================
        OLLAMA_BASE_URL: str = "http://localhost:11434"
        OLLAMA_MODEL: str = "qwen2.5-coder:7b-instruct"
        USE_OLLAMA: bool = True
        OLLAMA_TIMEOUT: int = 60

        # ==================== Gemini / AI (deprecated, kept for compat) ====================
        GEMINI_API_KEY: str = ""
        GEMINI_MODEL: str = "gemini-2.0-flash"
        USE_KRONOS_LOCAL: bool = True
        USE_GEMINI_FALLBACK: bool = False
        KRONOS_FORECAST_HORIZON: int = 10
        KRONOS_HISTORY_CANDLES: int = 1000
        KRONOS_CALIBRATION_MIN_SAMPLES: int = 20

        # ==================== Database ====================
        DB_DSN: str = "postgresql+psycopg2://postgres:password@localhost:5432/trading_db"

        # ==================== Trading ====================
        DEFAULT_SYMBOL: str = "EURUSD"
        TRADING_SYMBOLS: str = ""
        TICK_INTERVAL_SEC: int = 5
        ANALYSIS_INTERVAL_MIN: int = 15
        MIN_ANALYSIS_INTERVAL_MIN: int = 5
        CONFIDENCE_THRESHOLD: float = DEFAULT_CONFIDENCE_THRESHOLD
        MAX_POSITIONS: int = 20
        MAX_POSITIONS_PER_SYMBOL: int = 20

        # Risk management
        RISK_PER_TRADE_PCT: float = 1.0
        DEFAULT_SL_PIPS: float = 50.0
        DEFAULT_TP_PIPS: float = 100.0
        FORECAST_RISK_REWARD: float = 2.0
        MIN_SL_ATR_MULTIPLIER: float = 1.5
        TRAILING_STOP_ENABLED: bool = True
        TRAILING_STOP_PIPS: float = 50.0
        TRAILING_ACTIVATION_PIPS: float = 50.0
        HEDGE_ENABLED: bool = False
        HEDGE_TRIGGER_PIPS: float = 100.0
        HEDGE_VOLUME_RATIO: float = 0.5
        MAX_ORDERS_PER_MIN: int = 3

        # ==================== Bot ====================
        BOT_TOKEN: str = ""
        ADMIN_ID: str = ""

        # ==================== Logging ====================
        LOG_LEVEL: str = "INFO"
        LOG_DIR: str = "logs"
        LOG_MAX_BYTES: int = 10 * 1024 * 1024
        LOG_BACKUP_COUNT: int = 10

        # ==================== Cache ====================
        PREDICTION_CACHE_TTL_SEC: int = 300
        PREDICTION_CACHE_MAX: int = 20

        def __init__(self, **kwargs):
            env_vals = {k: v for k, v in os.environ.items()}
            env_file_vals = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
            merged = {**env_file_vals, **env_vals, **kwargs}
            init_dict = {}
            for field_name in self.model_fields:
                val = merged.get(field_name) or merged.get(field_name.lower())
                if val is not None:
                    init_dict[field_name] = val
            super().__init__(**init_dict)


settings = Settings()

# Path helpers
LOGS_DIR = BASE_DIR / settings.LOG_DIR
DB_SCHEMA_PATH = BASE_DIR / "db" / "schema.sql"
