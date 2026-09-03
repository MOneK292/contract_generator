"""Logging configuration."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from src.core.exceptions import ConfigurationError
from src.services.config.settings_loader import LoggingConfig


class LoggingSetup:
    """Configures date-based log files using the standard logging package."""

    LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

    @classmethod
    def configure(
        cls,
        config: LoggingConfig,
        logs_dir: str | Path,
        *,
        logger_name: str | None = None,
    ) -> logging.Logger:
        """Configure console and daily file logging."""
        logs_path = Path(logs_dir)
        logs_path.mkdir(parents=True, exist_ok=True)

        level = cls._level(config.level)
        log_file = logs_path / f"{date.today().strftime(config.file_date_format)}.log"

        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        cls._clear_handlers(logger)
        logger.propagate = False

        formatter = logging.Formatter(cls.LOG_FORMAT)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger

    @staticmethod
    def _clear_handlers(logger: logging.Logger) -> None:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()

    @staticmethod
    def _level(level_name: str) -> int:
        level = logging.getLevelName(level_name.upper())
        if not isinstance(level, int):
            raise ConfigurationError(f"Invalid logging level: {level_name}")
        return level
