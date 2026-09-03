"""Tests for production composition root."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.core.contract_engine import ContractEngine
from src.services.pdf.converter import PdfConverter
from src.main import ApplicationComposition, create_application, create_pdf_converter


class MainCompositionTest(unittest.TestCase):
    """Composition root behavior."""

    def test_create_application_builds_contract_engine(self) -> None:
        config = SimpleNamespace(
            logging=SimpleNamespace(level="INFO", file_date_format="%Y-%m-%d"),
            paths=SimpleNamespace(logs_dir=Path("logs"), temp_dir=Path("tmp")),
            libreoffice=SimpleNamespace(executable_path=Path("missing-soffice.exe")),
        )

        with patch("src.main.SettingsLoader") as loader_class:
            with patch("src.main.LoggingSetup") as logging_setup:
                with patch("src.main.GoogleAuth") as auth_class:
                    with patch("src.main.GoogleDriveService") as drive_service_class:
                        with patch("src.main.GoogleDriveCatalogService") as catalog_service_class:
                            with patch("src.main.TemplateCache") as template_cache_class:
                                loader_class.return_value.load.return_value = config
                                auth_class.return_value.create_drive_client.return_value = Mock()
                                catalog = Mock()
                                catalog_service_class.return_value.load_catalog.return_value = catalog

                                engine = create_application()

        self.assertIsInstance(engine, ApplicationComposition)
        self.assertIsInstance(engine.contract_engine, ContractEngine)
        logging_setup.configure.assert_called_once_with(config.logging, config.paths.logs_dir)
        catalog_service_class.return_value.load_catalog.assert_called_once_with()
        template_cache_class.assert_called_once()

    def test_create_pdf_converter_always_returns_converter(self) -> None:
        config = SimpleNamespace(
            libreoffice=SimpleNamespace(executable_path=None),
        )

        converter = create_pdf_converter(config)

        self.assertIsInstance(converter, PdfConverter)

    def test_create_application_builds_engine_with_pdf_converter(self) -> None:
        config = SimpleNamespace(
            logging=SimpleNamespace(level="INFO", file_date_format="%Y-%m-%d"),
            paths=SimpleNamespace(logs_dir=Path("logs"), temp_dir=Path("tmp")),
            libreoffice=SimpleNamespace(executable_path=None),
        )

        with patch("src.main.LoggingSetup"):
            with patch("src.main.GoogleAuth") as auth_class:
                with patch("src.main.GoogleDriveService"):
                    with patch("src.main.GoogleDriveCatalogService") as catalog_service_class:
                        with patch("src.main.TemplateCache"):
                            auth_class.return_value.create_drive_client.return_value = Mock()
                            catalog_service_class.return_value.load_catalog.return_value = Mock()

                            application = create_application(config)

        self.assertIsInstance(application.contract_engine.pdf_converter, PdfConverter)


if __name__ == "__main__":
    unittest.main()
