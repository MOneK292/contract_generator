"""Google Drive access."""

from __future__ import annotations

import io
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from src.core.exceptions import ContractGeneratorError


GOOGLE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOCM_MIME_TYPE = "application/vnd.ms-word.document.macroEnabled.12"
WORD_TEMPLATE_EXTENSIONS = (".docx", ".docm")
WORD_TEMPLATE_MIME_TYPES = (DOCX_MIME_TYPE, DOCM_MIME_TYPE)


class GoogleDriveError(ContractGeneratorError):
    """Raised when a Google Drive operation fails."""


@dataclass(frozen=True)
class GoogleFileMetadata:
    """Google Drive file metadata used by the cache."""

    file_id: str
    name: str | None
    mime_type: str | None
    modified_time: str | None
    md5: str | None
    size: int | None
    is_folder: bool = False


@dataclass
class GoogleDriveService:
    """Reads metadata and downloads Word templates from Google Drive."""

    drive_client: Any
    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
        init=False,
        repr=False,
    )

    def get_file_metadata(self, file_id: str) -> GoogleFileMetadata:
        """Return metadata for a Google Drive file."""
        try:
            response = (
                self.drive_client.files()
                .get(
                    fileId=file_id,
                    fields="id,name,mimeType,modifiedTime,md5Checksum,size",
                )
                .execute()
            )
        except HttpError as error:
            self._log_google_error("metadata", file_id, error)
            raise GoogleDriveError(f"Failed to get Google Drive metadata: {file_id}") from error
        except Exception as error:
            self._logger.exception("Unexpected Google Drive metadata error: %s", file_id)
            raise GoogleDriveError(f"Failed to get Google Drive metadata: {file_id}") from error

        return self._metadata_from_response(response)

    def file_exists(self, file_id: str) -> bool:
        """Return whether a Google Drive file exists and is accessible."""
        try:
            self.get_file_metadata(file_id)
        except GoogleDriveError as error:
            if self._is_not_found(error.__cause__):
                return False
            raise
        return True

    def get_modified_time(self, file_id: str) -> str | None:
        """Return a file's Google Drive `modifiedTime` value."""
        return self.get_file_metadata(file_id).modified_time

    def get_md5_checksum(self, file_id: str) -> str | None:
        """Return a file's Google Drive `md5Checksum` value if available."""
        return self.get_file_metadata(file_id).md5

    def list_children(self, folder_id: str) -> tuple[GoogleFileMetadata, ...]:
        """Return direct children of a Google Drive folder."""
        query = f"'{folder_id}' in parents and trashed = false"
        files: list[GoogleFileMetadata] = []
        page_token = None
        try:
            while True:
                response = (
                    self.drive_client.files()
                    .list(
                        q=query,
                        fields=(
                            "files(id,name,mimeType,modifiedTime,md5Checksum,size),"
                            "nextPageToken"
                        ),
                        pageSize=1000,
                        pageToken=page_token,
                    )
                    .execute()
                )
                files.extend(
                    self._metadata_from_response(item)
                    for item in response.get("files", [])
                )
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
        except HttpError as error:
            self._log_google_error("list", folder_id, error)
            raise GoogleDriveError(f"Failed to list Google Drive folder: {folder_id}") from error
        except Exception as error:
            self._logger.exception("Unexpected Google Drive list error: %s", folder_id)
            raise GoogleDriveError(f"Failed to list Google Drive folder: {folder_id}") from error

        return tuple(files)

    def list_folders(self, folder_id: str) -> tuple[GoogleFileMetadata, ...]:
        """Return direct child folders of a Google Drive folder."""
        return tuple(child for child in self.list_children(folder_id) if child.is_folder)

    def list_docx_files(self, folder_id: str) -> tuple[GoogleFileMetadata, ...]:
        """Return direct child Word template files of a Google Drive folder."""
        return self.list_template_files(folder_id)

    def list_template_files(self, folder_id: str) -> tuple[GoogleFileMetadata, ...]:
        """Return direct child DOCX/DOCM template files of a Google Drive folder."""
        return tuple(child for child in self.list_children(folder_id) if is_word_template(child))

    def download_file(self, file_id: str, output_path: str | Path) -> Path:
        """Download a Google Drive file to `output_path` and return the path."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_output = output.with_suffix(output.suffix + ".download")
        start = time.perf_counter()

        try:
            request = self.drive_client.files().get_media(fileId=file_id)
            with io.FileIO(temp_output, "wb") as file_handle:
                downloader = MediaIoBaseDownload(file_handle, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
            temp_output.replace(output)
        except HttpError as error:
            self._cleanup_partial_download(temp_output)
            self._log_google_error("download", file_id, error)
            raise GoogleDriveError(f"Failed to download Google Drive file: {file_id}") from error
        except Exception as error:
            self._cleanup_partial_download(temp_output)
            self._logger.exception("Unexpected Google Drive download error: %s", file_id)
            raise GoogleDriveError(f"Failed to download Google Drive file: {file_id}") from error

        elapsed = time.perf_counter() - start
        file_size = output.stat().st_size
        self._logger.info(
            "Downloaded Google Drive file %s to %s in %.3fs (%s bytes)",
            file_id,
            output,
            elapsed,
            file_size,
        )
        return output

    def _metadata_from_response(self, response: dict[str, Any]) -> GoogleFileMetadata:
        size = response.get("size")
        return GoogleFileMetadata(
            file_id=str(response["id"]),
            name=response.get("name"),
            mime_type=response.get("mimeType"),
            modified_time=response.get("modifiedTime"),
            md5=response.get("md5Checksum"),
            size=int(size) if size is not None else None,
            is_folder=response.get("mimeType") == GOOGLE_FOLDER_MIME_TYPE,
        )

    def _log_google_error(self, operation: str, file_id: str, error: HttpError) -> None:
        self._logger.error(
            "Google API error during %s for file %s: %s",
            operation,
            file_id,
            error,
        )

    def _is_not_found(self, error: BaseException | None) -> bool:
        return isinstance(error, HttpError) and getattr(error.resp, "status", None) == 404

    def _cleanup_partial_download(self, temp_output: Path) -> None:
        if temp_output.exists():
            temp_output.unlink()


def is_word_template(metadata: GoogleFileMetadata) -> bool:
    """Return whether Google metadata describes a supported Word template."""
    if metadata.mime_type in WORD_TEMPLATE_MIME_TYPES:
        return True
    if metadata.name:
        return metadata.name.lower().endswith(WORD_TEMPLATE_EXTENSIONS)
    return False
