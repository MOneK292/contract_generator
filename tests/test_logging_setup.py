"""Tests for logging setup."""

from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from src.services.config.settings_loader import LoggingConfig
from src.services.logging.setup import LoggingSetup


class LoggingSetupTest(unittest.TestCase):
    """Logging setup behavior."""

    def test_configures_daily_log_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            logs_dir = Path(temp_dir)
            logger = LoggingSetup.configure(
                LoggingConfig(level="INFO", file_date_format="%Y-%m-%d"),
                logs_dir,
                logger_name="test.contract_generator",
            )

            try:
                logger.info("hello config")
                log_file = logs_dir / f"{date.today().strftime('%Y-%m-%d')}.log"

                self.assertTrue(log_file.exists())
                self.assertIn("hello config", log_file.read_text(encoding="utf-8"))
            finally:
                for handler in logger.handlers[:]:
                    logger.removeHandler(handler)
                    handler.close()


if __name__ == "__main__":
    unittest.main()
