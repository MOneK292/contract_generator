"""Tests for application settings loading."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.exceptions import ConfigurationError
from src.services.config.settings_loader import SettingsLoader


class SettingsLoaderTest(unittest.TestCase):
    """Settings loader behavior."""

    def test_loads_env_yaml_templates_and_creates_directories(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            credentials = root / "credentials.json"
            libreoffice = root / "soffice.exe"
            credentials.write_text("{}", encoding="utf-8")
            libreoffice.write_text("", encoding="utf-8")
            self._write_project_files(root, credentials, libreoffice)

            config = SettingsLoader(root_dir=root).load()

            self.assertEqual(config.google.credentials_path, credentials)
            self.assertEqual(config.libreoffice.executable_path, libreoffice)
            self.assertEqual(config.google.drive_root_folder_id, "drive-root")
            self.assertTrue(config.paths.cache_dir.is_dir())
            self.assertTrue(config.paths.template_cache_dir.is_dir())
            self.assertTrue(config.paths.metadata_cache_dir.is_dir())
            self.assertTrue(config.paths.temp_dir.is_dir())
            self.assertTrue(config.paths.logs_dir.is_dir())
            self.assertEqual(config.templates.get_template("contract").name, "Contract")
            self.assertEqual(config.auth.authorized_users, ())
            self.assertEqual(config.schedule.notification_start_time, "09:00")
            self.assertEqual(config.schedule.notification_end_time, "20:00")

    def test_missing_libreoffice_does_not_block_loading(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            credentials = root / "credentials.json"
            missing_libreoffice = root / "missing-soffice.exe"
            credentials.write_text("{}", encoding="utf-8")
            self._write_project_files(root, credentials, missing_libreoffice)

            config = SettingsLoader(root_dir=root).load()

            self.assertEqual(config.libreoffice.executable_path, missing_libreoffice)

    def test_empty_libreoffice_path_does_not_block_loading(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            credentials = root / "credentials.json"
            credentials.write_text("{}", encoding="utf-8")
            self._write_project_files(root, credentials, None)

            config = SettingsLoader(root_dir=root).load()

            self.assertIsNone(config.libreoffice.executable_path)

    def test_validates_required_external_paths(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            missing_credentials = root / "missing-credentials.json"
            libreoffice = root / "soffice.exe"
            libreoffice.write_text("", encoding="utf-8")
            self._write_project_files(root, missing_credentials, libreoffice)

            with self.assertRaises(ConfigurationError):
                SettingsLoader(root_dir=root).load()

    def _write_project_files(
        self,
        root: Path,
        credentials: Path,
        libreoffice: Path | None,
    ) -> None:
        (root / "config").mkdir()
        (root / ".env").write_text(
            "\n".join(
                [
                    f"TEST_GOOGLE_CREDENTIALS={credentials}",
                    "TEST_GOOGLE_DRIVE_ROOT_FOLDER_ID=drive-root",
                    f"TEST_LIBREOFFICE_PATH={libreoffice or ''}",
                ]
            ),
            encoding="utf-8",
        )
        (root / "config" / "settings.yaml").write_text(
            """
google:
  credentials_path: ${TEST_GOOGLE_CREDENTIALS}
  drive_root_folder_id: ${TEST_GOOGLE_DRIVE_ROOT_FOLDER_ID}

libreoffice:
  executable_path: ${TEST_LIBREOFFICE_PATH}
  timeout_seconds: 60

paths:
  cache_dir: cache
  template_cache_dir: cache/templates
  metadata_cache_dir: cache/metadata
  temp_dir: tmp
  logs_dir: logs

logging:
  level: INFO
  file_date_format: "%Y-%m-%d"

pdf:
  delete_temp_docx: true
  delete_temp_pdf_after_delivery: true
  keep_temp_files_on_error: true
""",
            encoding="utf-8",
        )
        (root / "config" / "templates.yaml").write_text(
            """
projects:
  - id: demo
    name: Demo
    vacancies:
      - id: manager
        name: Manager
        template_id: contract
templates:
  - id: contract
    name: Contract
    google_drive_file_id: drive-file
""",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
