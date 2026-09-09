"""Настройка логирования с файловым ротейтингом."""

import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from config.settings import settings, LOGS_DIR


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
    root_logger.addHandler(console_handler)

    # === File handlers (one per module) ===
    modules = {
        "root": "tradingbot.log",
        "mt5_connector": "mt5_connector.log",
        "ai_engine": "ai_engine.log",
        "trader": "trader.log",
        "db_logger": "database.log",
        "telegram_bot": "telegram_bot.log",
    }

    for logger_name, filename in modules.items():
        file_handler = RotatingFileHandler(
            LOGS_DIR / filename,
            maxBytes=settings.LOG_MAX_BYTES,
            backupCount=settings.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(log_format)
        
        logger = logging.getLogger(logger_name)
        logger.addHandler(file_handler)
        logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Получить логгер по имени модуля."""
    return logging.getLogger(name)
