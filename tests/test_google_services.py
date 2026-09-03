"""Tests for Google Drive services and template cache."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from googleapiclient.errors import HttpError

from src.services.google.auth import GoogleAuth, GoogleAuthError
from src.services.google.cache import TemplateCache, TemplateCacheMetadata
from src.services.google.drive import (
    DOCM_MIME_TYPE,
    DOCX_MIME_TYPE,
    GoogleDriveError,
    GoogleDriveService,
    GoogleFileMetadata,
)


class GoogleAuthTest(unittest.TestCase):
    """Google auth behavior."""

    def test_create_drive_client_uses_app_config_credentials(self) -> None:
        config = SimpleNamespace(
            google=SimpleNamespace(credentials_path=Path("credentials.json"))
        )

        with patch("src.services.google.auth.Credentials") as credentials_class:
            with patch("src.services.google.auth.build") as build:
                credentials = Mock()
                client = Mock()
                credentials_class.from_service_account_file.return_value = credentials
                build.return_value = client

                result = GoogleAuth(config=config).create_drive_client()

        self.assertEqual(result, client)
        credentials_class.from_service_account_file.assert_called_once_with(
            "credentials.json",
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
        build.assert_called_once_with(
            "drive",
            "v3",
            credentials=credentials,
            cache_discovery=False,
        )

    def test_create_drive_client_wraps_errors(self) -> None:
        config = SimpleNamespace(
            google=SimpleNamespace(credentials_path=Path("credentials.json"))
        )

        with patch("src.services.google.auth.Credentials") as credentials_class:
            credentials_class.from_service_account_file.side_effect = OSError("bad")

            with self.assertRaises(GoogleAuthError):
                GoogleAuth(config=config).create_drive_client()

    def test_create_drive_client_prefers_oauth2_when_configured(self) -> None:
        """OAuth2 credentials should be used when refresh_token is set."""
        config = SimpleNamespace(
            google=SimpleNamespace(
                credentials_path=Path("credentials.json"),
                oauth_client_id="test-client-id",
                oauth_client_secret="test-secret",
                oauth_refresh_token="test-refresh-token",
            )
        )

        with patch("google.oauth2.credentials.Credentials") as user_creds_class:
            with patch("src.services.google.auth.build") as build:
                creds_instance = Mock()
                user_creds_class.return_value = creds_instance
                client = Mock()
                build.return_value = client

                result = GoogleAuth(config=config).create_drive_client()

        self.assertEqual(result, client)
        user_creds_class.assert_called_once()
        build.assert_called_once_with(
            "drive", "v3", credentials=creds_instance, cache_discovery=False,
        )

    def test_create_sheets_client_uses_oauth2(self) -> None:
        """create_sheets_client should use OAuth2 when configured."""
        config = SimpleNamespace(
            google=SimpleNamespace(
                credentials_path=Path("credentials.json"),
                oauth_client_id="test-client-id",
                oauth_client_secret="test-secret",
                oauth_refresh_token="test-refresh-token",
            )
        )

        with patch("google.oauth2.credentials.Credentials") as user_creds_class:
            with patch("src.services.google.auth.build") as build:
                creds_instance = Mock()
                user_creds_class.return_value = creds_instance
                client = Mock()
                build.return_value = client

                result = GoogleAuth(config=config).create_sheets_client()

        self.assertEqual(result, client)
        build.assert_called_once_with(
            "sheets", "v4", credentials=creds_instance, cache_discovery=False,
        )

    def test_create_sheets_client_falls_back_to_service_account(self) -> None:
        """create_sheets_client should fall back to Service Account when no OAuth2."""
        config = SimpleNamespace(
            google=SimpleNamespace(credentials_path=Path("credentials.json"))
        )

        with patch("src.services.google.auth.Credentials") as credentials_class:
            with patch("src.services.google.auth.build") as build:
                credentials = Mock()
                client = Mock()
                credentials_class.from_service_account_file.return_value = credentials
                build.return_value = client

                result = GoogleAuth(config=config).create_sheets_client()

        self.assertEqual(result, client)
        build.assert_called_once_with(
            "sheets", "v4", credentials=credentials, cache_discovery=False,
        )


class TemplateCacheTest(unittest.TestCase):
    """Template cache behavior."""

    def test_cache_hit_uses_local_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache, drive = self._cache(temp_dir)
            file_id = "file-id"
            local_path = cache.template_path(file_id)
            local_path.write_bytes(b"cached")
            remote_metadata = self._metadata(file_id, "2026-01-01T00:00:00Z", "md5")
            cache.save_metadata(file_id, remote_metadata)
            drive.get_file_metadata.return_value = remote_metadata

            result = cache.get_template(file_id)

            self.assertEqual(result, local_path)
            drive.download_file.assert_not_called()

    def test_cache_miss_downloads_and_saves_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache, drive = self._cache(temp_dir)
            file_id = "file-id"
            remote_metadata = self._metadata(file_id, "2026-01-01T00:00:00Z", "md5")
            drive.get_file_metadata.return_value = remote_metadata
            drive.download_file.side_effect = lambda _, path: Path(path)

            result = cache.get_template(file_id)
            stored_metadata = cache.load_metadata(file_id)

            self.assertEqual(result, cache.template_path(file_id))
            drive.download_file.assert_called_once_with(file_id, cache.template_path(file_id))
            self.assertIsNotNone(stored_metadata)
            self.assertEqual(stored_metadata.file_id, file_id)
            self.assertEqual(stored_metadata.modified_time, remote_metadata.modified_time)
            self.assertEqual(stored_metadata.md5, remote_metadata.md5)

    def test_cache_miss_preserves_docm_extension_from_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache, drive = self._cache(temp_dir)
            file_id = "file-id"
            remote_metadata = GoogleFileMetadata(
                file_id=file_id,
                name="template.docm",
                mime_type=DOCM_MIME_TYPE,
                modified_time="2026-01-01T00:00:00Z",
                md5="md5",
                size=10,
            )
            drive.get_file_metadata.return_value = remote_metadata
            drive.download_file.side_effect = lambda _, path: Path(path)

            result = cache.get_template(file_id)

            self.assertEqual(result, cache.config.paths.template_cache_dir / "file-id.docm")
            drive.download_file.assert_called_once_with(file_id, result)

    def test_cache_update_downloads_when_modified_time_changes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache, drive = self._cache(temp_dir)
            file_id = "file-id"
            local_path = cache.template_path(file_id)
            local_path.write_bytes(b"old")
            cache.save_metadata(file_id, self._metadata(file_id, "old", "old-md5"))
            remote_metadata = self._metadata(file_id, "new", "new-md5")
            drive.get_file_metadata.return_value = remote_metadata
            drive.download_file.side_effect = lambda _, path: Path(path)

            result = cache.get_template(file_id)
            stored_metadata = cache.load_metadata(file_id)

            self.assertEqual(result, local_path)
            drive.download_file.assert_called_once_with(file_id, local_path)
            self.assertEqual(stored_metadata.modified_time, "new")
            self.assertEqual(stored_metadata.md5, "new-md5")

    def test_metadata_save_and_load(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache, _ = self._cache(temp_dir)
            metadata = TemplateCacheMetadata(
                file_id="file-id",
                modified_time="modified",
                md5="md5",
                downloaded_at="2026-01-01T00:00:00+00:00",
            )

            cache.save_metadata("file-id", metadata)
            loaded = cache.load_metadata("file-id")

            self.assertEqual(loaded, metadata)

    def test_download_error_is_propagated_without_metadata_save(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache, drive = self._cache(temp_dir)
            file_id = "file-id"
            drive.get_file_metadata.return_value = self._metadata(file_id, "new", "md5")
            drive.download_file.side_effect = GoogleDriveError("download failed")

            with self.assertRaises(GoogleDriveError):
                cache.get_template(file_id)

            self.assertIsNone(cache.load_metadata(file_id))

    def _cache(self, temp_dir: str) -> tuple[TemplateCache, Mock]:
        root = Path(temp_dir)
        template_dir = root / "templates"
        metadata_dir = root / "metadata"
        template_dir.mkdir()
        metadata_dir.mkdir()
        config = SimpleNamespace(
            paths=SimpleNamespace(
                template_cache_dir=template_dir,
                metadata_cache_dir=metadata_dir,
            )
        )
        drive = Mock()
        return TemplateCache(config=config, drive_service=drive), drive

    def _metadata(
        self,
        file_id: str,
        modified_time: str,
        md5: str | None,
    ) -> GoogleFileMetadata:
        return GoogleFileMetadata(
            file_id=file_id,
            name="template.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            modified_time=modified_time,
            md5=md5,
            size=10,
        )


class GoogleDriveServiceTest(unittest.TestCase):
    """Google Drive service behavior."""

    def test_get_file_metadata(self) -> None:
        execute = Mock(
            return_value={
                "id": "file-id",
                "name": "template.docx",
                "mimeType": "docx",
                "modifiedTime": "modified",
                "md5Checksum": "md5",
                "size": "42",
            }
        )
        client = self._client(get_execute=execute)
        service = GoogleDriveService(client)

        metadata = service.get_file_metadata("file-id")

        self.assertEqual(metadata.file_id, "file-id")
        self.assertEqual(metadata.modified_time, "modified")
        self.assertEqual(metadata.md5, "md5")
        self.assertEqual(metadata.size, 42)

    def test_file_exists_returns_false_for_404(self) -> None:
        error = self._http_error(404)
        client = self._client(get_execute=Mock(side_effect=error))
        service = GoogleDriveService(client)

        self.assertFalse(service.file_exists("missing-file"))

    def test_get_modified_time_and_md5_checksum(self) -> None:
        execute = Mock(
            return_value={
                "id": "file-id",
                "modifiedTime": "modified",
                "md5Checksum": "md5",
            }
        )
        service = GoogleDriveService(self._client(get_execute=execute))

        self.assertEqual(service.get_modified_time("file-id"), "modified")
        self.assertEqual(service.get_md5_checksum("file-id"), "md5")

    def test_google_api_error_is_wrapped(self) -> None:
        client = self._client(get_execute=Mock(side_effect=self._http_error(500)))
        service = GoogleDriveService(client)

        with self.assertRaises(GoogleDriveError):
            service.get_file_metadata("file-id")

    def test_list_template_files_returns_docx_and_docm(self) -> None:
        service = GoogleDriveService(self._client())
        service.list_children = Mock(
            return_value=(
                GoogleFileMetadata("docx-id", "contract.docx", DOCX_MIME_TYPE, None, None, None),
                GoogleFileMetadata("docm-id", "macro.docm", DOCM_MIME_TYPE, None, None, None),
                GoogleFileMetadata("txt-id", "notes.txt", "text/plain", None, None, None),
            )
        )

        templates = service.list_template_files("folder")

        self.assertEqual([template.file_id for template in templates], ["docx-id", "docm-id"])

    def test_download_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "template.docx"
            service = GoogleDriveService(self._client())

            with patch(
                "src.services.google.drive.MediaIoBaseDownload",
                self._fake_downloader(b"docx"),
            ):
                result = service.download_file("file-id", output_path)

            self.assertEqual(result, output_path)
            self.assertEqual(output_path.read_bytes(), b"docx")

    def test_download_error_is_wrapped(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "template.docx"
            client = self._client(get_media=Mock(side_effect=self._http_error(500)))
            service = GoogleDriveService(client)

            with self.assertRaises(GoogleDriveError):
                service.download_file("file-id", output_path)

    def _client(
        self,
        get_execute: Mock | None = None,
        get_media: Mock | None = None,
    ) -> Mock:
        files = Mock()
        files.get.return_value.execute = get_execute or Mock(
            return_value={"id": "file-id"}
        )
        if get_media is None:
            files.get_media.return_value = object()
        else:
            files.get_media.side_effect = get_media.side_effect
        client = Mock()
        client.files.return_value = files
        return client

    def _http_error(self, status: int) -> HttpError:
        response = SimpleNamespace(status=status, reason="error")
        return HttpError(response, b"{}")

    def _fake_downloader(self, content: bytes):
        class FakeDownloader:
            def __init__(self, file_handle, request) -> None:
                self.file_handle = file_handle
                self.done = False

            def next_chunk(self):
                if not self.done:
                    self.file_handle.write(content)
                    self.done = True
                return None, True

        return FakeDownloader


if __name__ == "__main__":
    unittest.main()
