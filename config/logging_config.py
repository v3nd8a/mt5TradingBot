"""Настройка логирования с файловым ротейтингом."""

import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from config.settings import settings, LOGS_DIR


class ConsoleNoiseFilter(logging.Filter):
    """Скрывает техническую диагностику свечей только из консоли."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage().lower()
        if record.name == "mt5_connector" and (
            message.startswith("fetched ") or message.startswith("saved ")
        ):
            return False
        if record.name == "trader" and "initial candles" in message:
            return False
        return True


def setup_logging() -> logging.Logger:
    """Инициализация логирования — консоль + файлы с ротейтингом."""
    LOGS_DIR.mkdir(exist_ok=True)

    log_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    # === Console handler ===
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(ConsoleNoiseFilter())
    root_logger.addHandler(console_handler)

    # === File handler (single consolidated log) ===
    file_handler = RotatingFileHandler(
        LOGS_DIR / "tradingbot.log",
        maxBytes=settings.LOG_MAX_BYTES,
        backupCount=settings.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(log_format)
    root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Получить логгер по имени модуля."""
    return logging.getLogger(name)
