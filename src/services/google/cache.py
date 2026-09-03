"""Template cache backed by local files and metadata."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.services.config.settings_loader import AppConfig
from src.services.google.drive import (
    DOCM_MIME_TYPE,
    DOCX_MIME_TYPE,
    GoogleDriveService,
    GoogleFileMetadata,
)


@dataclass(frozen=True)
class TemplateCacheMetadata:
    """Local metadata for a cached Google Drive template."""

    file_id: str
    modified_time: str | None
    md5: str | None
    downloaded_at: str


@dataclass
class TemplateCache:
    """Stores downloaded templates and Google Drive metadata."""

    config: AppConfig
    drive_service: GoogleDriveService
    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
        init=False,
        repr=False,
    )

    def get_template(self, file_id: str, filename: str | None = None) -> Path:
        """Return a local template path, downloading or updating cache if needed."""
        remote_metadata = None
        if filename is None:
            remote_metadata = self.drive_service.get_file_metadata(file_id)
            local_path = self._template_path_from_metadata(file_id, remote_metadata)
        else:
            local_path = self.template_path(file_id, filename)

        if not local_path.exists():
            self._logger.info("Template cache miss: %s", file_id)
            return self._download_and_store(file_id, local_path, remote_metadata)

        remote_metadata = remote_metadata or self.drive_service.get_file_metadata(file_id)
        local_metadata = self.load_metadata(file_id)

        if self._is_update_required(local_metadata, remote_metadata):
            self._logger.info("Template cache update required: %s", file_id)
            return self._download_and_store(file_id, local_path, remote_metadata)

        self._logger.info("Template cache hit: %s", file_id)
        return local_path

    def template_path(self, file_id: str, filename: str | None = None) -> Path:
        """Return the local cache path for a template file."""
        safe_name = filename or f"{self._safe_file_id(file_id)}.docx"
        return self.config.paths.template_cache_dir / safe_name

    def metadata_path(self, file_id: str) -> Path:
        """Return the local metadata JSON path for a Google Drive file."""
        return self.config.paths.metadata_cache_dir / f"{self._safe_file_id(file_id)}.json"

    def load_metadata(self, file_id: str) -> TemplateCacheMetadata | None:
        """Load cached metadata for a Google Drive file if it exists."""
        path = self.metadata_path(file_id)
        if not path.exists():
            return None

        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return TemplateCacheMetadata(
            file_id=str(data["file_id"]),
            modified_time=data.get("modified_time"),
            md5=data.get("md5"),
            downloaded_at=str(data["downloaded_at"]),
        )

    def save_metadata(
        self,
        file_id: str,
        metadata: GoogleFileMetadata | TemplateCacheMetadata,
    ) -> TemplateCacheMetadata:
        """Save metadata for a cached Google Drive file."""
        cache_metadata = self._cache_metadata(file_id, metadata)
        path = self.metadata_path(file_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8") as file:
            json.dump(asdict(cache_metadata), file, ensure_ascii=False, indent=2)

        self._logger.debug("Saved template cache metadata: %s", path)
        return cache_metadata

    def _download_and_store(
        self,
        file_id: str,
        local_path: Path,
        metadata: GoogleFileMetadata | None = None,
    ) -> Path:
        remote_metadata = metadata or self.drive_service.get_file_metadata(file_id)
        self._logger.info("Downloading template from Google Drive: %s", file_id)
        downloaded_path = self.drive_service.download_file(file_id, local_path)
        self.save_metadata(file_id, remote_metadata)
        return downloaded_path

    def _is_update_required(
        self,
        local_metadata: TemplateCacheMetadata | None,
        remote_metadata: GoogleFileMetadata,
    ) -> bool:
        if local_metadata is None:
            return True
        if local_metadata.modified_time != remote_metadata.modified_time:
            return True
        if remote_metadata.md5 and local_metadata.md5 != remote_metadata.md5:
            return True
        return False

    def _cache_metadata(
        self,
        file_id: str,
        metadata: GoogleFileMetadata | TemplateCacheMetadata,
    ) -> TemplateCacheMetadata:
        if isinstance(metadata, TemplateCacheMetadata):
            return metadata

        return TemplateCacheMetadata(
            file_id=file_id,
            modified_time=metadata.modified_time,
            md5=metadata.md5,
            downloaded_at=datetime.now(timezone.utc).isoformat(),
        )

    def _safe_file_id(self, file_id: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]", "_", file_id)

    def _template_path_from_metadata(
        self,
        file_id: str,
        metadata: GoogleFileMetadata,
    ) -> Path:
        extension = self._template_extension(metadata)
        return self.config.paths.template_cache_dir / f"{self._safe_file_id(file_id)}{extension}"

    def _template_extension(self, metadata: GoogleFileMetadata) -> str:
        if metadata.name:
            suffix = Path(metadata.name).suffix.lower()
            if suffix in (".docx", ".docm"):
                return suffix
        if metadata.mime_type == DOCM_MIME_TYPE:
            return ".docm"
        if metadata.mime_type == DOCX_MIME_TYPE:
            return ".docx"
        return ".docx"
