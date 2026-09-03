"""Tests for backend diagnostics command."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from tempfile import TemporaryDirectory

from src.diagnostics import DiagnosticsReport, DiagnosticsRunner
from src.core.exceptions import RenderingError
from src.services.config import TemplateCatalog
from src.services.google import GoogleFileMetadata


class DiagnosticsRunnerTest(unittest.TestCase):
    """Diagnostics runner behavior."""

    def test_run_reports_ready_with_mocked_infrastructure(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            credentials = root / "credentials.json"
            cached_template = root / "cache" / "templates" / "contract.docx"
            self._write_env(root, credentials, libreoffice_path="")
            self._write_credentials(credentials)

            config = SimpleNamespace(
                google=SimpleNamespace(
                    credentials_path=credentials,
                    drive_root_folder_id="root",
                ),
                paths=SimpleNamespace(
                    cache_dir=root / "cache",
                    template_cache_dir=root / "cache" / "templates",
                    metadata_cache_dir=root / "cache" / "metadata",
                    temp_dir=root / "tmp",
                ),
            )
            catalog = TemplateCatalog.from_mapping(
                {
                    "projects": [
                        {
                            "id": "project",
                            "name": "Project",
                            "vacancies": [
                                {
                                    "id": "vacancy",
                                    "name": "Vacancy",
                                    "template_id": "template",
                                    "template_ids": ["template"],
                                }
                            ],
                        }
                    ],
                    "templates": [
                        {
                            "id": "template",
                            "name": "Contract.docx",
                            "google_drive_file_id": "template",
                        }
                    ],
                }
            )
            fake_drive = _FakeDriveService()

            with patch.dict("os.environ", {}, clear=True):
                with patch("src.diagnostics.SettingsLoader") as loader_class:
                    with patch("src.diagnostics.GoogleAuth") as auth_class:
                        with patch("src.diagnostics.GoogleDriveService") as drive_class:
                            with patch("src.diagnostics.GoogleDriveCatalogService") as catalog_class:
                                with patch("src.diagnostics.TemplateCache") as cache_class:
                                    with patch("src.diagnostics.DocxRenderer") as renderer_class:
                                        loader_class.return_value.load.return_value = config
                                        auth_class.return_value.create_drive_client.return_value = object()
                                        drive_class.return_value = fake_drive
                                        catalog_class.return_value.load_catalog.return_value = catalog
                                        cache_class.return_value.get_template.return_value = cached_template
                                        renderer_class.return_value.render.return_value = (
                                            SimpleNamespace(unresolved_placeholders=[])
                                        )

                                        report = DiagnosticsRunner(root_dir=root).run()

            self.assertFalse(report.has_errors())
            status_names = {status.name for status in report.statuses}
            self.assertIn("ENV", status_names)
            self.assertIn("Google Auth", status_names)
            self.assertIn("Root Folder", status_names)
            self.assertIn("Project Tree", status_names)
            self.assertIn("Template Cache", status_names)
            self.assertIn("Renderer", status_names)
            templates_status = next(
                status for status in report.statuses if status.name == "Templates"
            )
            self.assertIn("DOCX/DOCM templates found", templates_status.message)

    def test_credentials_check_reports_missing_required_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "credentials.json"
            path.write_text('{"project_id": "demo"}', encoding="utf-8")
            report = DiagnosticsReport()

            result = DiagnosticsRunner(root_dir=Path(temp_dir))._check_credentials(
                report,
                path,
            )

        self.assertIsNone(result)
        self.assertTrue(report.has_errors())
        self.assertIn("client_email", report.statuses[0].message)
        self.assertIn("private_key", report.statuses[0].message)
        self.assertIn("token_uri", report.statuses[0].message)

    def test_libreoffice_missing_is_warning(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = DiagnosticsReport()

            with patch.dict(
                "os.environ",
                {
                    "BOT_TOKEN": "token",
                    "GOOGLE_CREDENTIALS": str(root / "credentials.json"),
                    "GOOGLE_DRIVE_ROOT_FOLDER_ID": "root",
                },
                clear=True,
            ):
                DiagnosticsRunner(root_dir=root)._load_env(report)

        libreoffice_status = next(
            status for status in report.statuses if status.name == "LibreOffice"
        )
        self.assertFalse(report.has_errors())
        self.assertIn("not configured", libreoffice_status.message)

    def test_renderer_failure_reports_original_exception_and_file_diagnostics(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template = root / "broken.docm"
            template.write_bytes(b"not-a-zip")
            config = SimpleNamespace(paths=SimpleNamespace(temp_dir=root))
            report = DiagnosticsReport()
            original = KeyError("word/document.xml")
            wrapped = RenderingError("Failed to open DOCX template")
            wrapped.__cause__ = original

            with patch("src.diagnostics.DocxRenderer") as renderer_class:
                renderer_class.return_value.render.side_effect = wrapped

                DiagnosticsRunner(root_dir=root)._check_renderer(report, config, template)

        renderer_status = next(status for status in report.statuses if status.name == "Renderer")
        details = "\n".join(report.details)
        self.assertTrue(report.has_errors())
        self.assertIn("RenderingError: Failed to open DOCX template", renderer_status.message)
        self.assertIn("KeyError", renderer_status.message)
        self.assertIn("Template file diagnostics:", details)
        self.assertIn("exists: True", details)
        self.assertIn("extension: .docm", details)
        self.assertIn("first bytes: 6e 6f 74 2d 61 2d 7a 69", details)
        self.assertIn("valid zip: False", details)

    def _write_env(
        self,
        root: Path,
        credentials: Path,
        *,
        libreoffice_path: str,
    ) -> None:
        (root / ".env").write_text(
            "\n".join(
                [
                    "BOT_TOKEN=token",
                    f"GOOGLE_CREDENTIALS={credentials}",
                    "GOOGLE_DRIVE_ROOT_FOLDER_ID=root",
                    f"LIBREOFFICE_PATH={libreoffice_path}",
                ]
            ),
            encoding="utf-8",
        )

    def _write_credentials(self, path: Path) -> None:
        path.write_text(
            """
{
  "project_id": "demo",
  "client_email": "service@example.com",
  "private_key": "-----BEGIN PRIVATE KEY-----\\nkey\\n-----END PRIVATE KEY-----\\n",
  "token_uri": "https://oauth2.googleapis.com/token"
}
""",
            encoding="utf-8",
        )


class _FakeDriveService:
    def get_file_metadata(self, file_id: str) -> GoogleFileMetadata:
        return GoogleFileMetadata(
            file_id=file_id,
            name="Root",
            mime_type="application/vnd.google-apps.folder",
            modified_time=None,
            md5=None,
            size=None,
            is_folder=True,
        )

    def list_folders(self, folder_id: str) -> tuple[GoogleFileMetadata, ...]:
        if folder_id == "root":
            return (
                GoogleFileMetadata(
                    file_id="project",
                    name="Project",
                    mime_type="application/vnd.google-apps.folder",
                    modified_time=None,
                    md5=None,
                    size=None,
                    is_folder=True,
                ),
            )
        if folder_id == "project":
            return (
                GoogleFileMetadata(
                    file_id="vacancy",
                    name="Vacancy",
                    mime_type="application/vnd.google-apps.folder",
                    modified_time=None,
                    md5=None,
                    size=None,
                    is_folder=True,
                ),
            )
        return ()

    def list_template_files(self, folder_id: str) -> tuple[GoogleFileMetadata, ...]:
        if folder_id == "vacancy":
            return (
                GoogleFileMetadata(
                    file_id="template",
                    name="Contract.docx",
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    modified_time="2026-07-14T00:00:00Z",
                    md5="md5",
                    size=10,
                ),
            )
        return ()

    def list_children(self, folder_id: str) -> tuple[GoogleFileMetadata, ...]:
        if folder_id == "project":
            return (
                GoogleFileMetadata(
                    file_id="vacancy",
                    name="Vacancy",
                    mime_type="application/vnd.google-apps.folder",
                    modified_time=None,
                    md5=None,
                    size=None,
                    is_folder=True,
                ),
            )
        if folder_id == "vacancy":
            return (
                GoogleFileMetadata(
                    file_id="template",
                    name="Contract.docx",
                    mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    modified_time="2026-07-14T00:00:00Z",
                    md5="md5",
                    size=10,
                    is_folder=False,
                ),
            )
        return ()


if __name__ == "__main__":
    unittest.main()
