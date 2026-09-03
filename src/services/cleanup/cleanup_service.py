"""Generated file cleanup service."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class CleanupResult:
    """Result of a cleanup operation."""

    removed_docx: bool
    kept_pdf: bool
    removed_temp_files: tuple[Path, ...]
    remaining_temp_files: tuple[Path, ...]
    cleanup_errors: tuple[str, ...] = ()


@dataclass
class CleanupService:
    """Removes temporary generation artifacts while preserving deliverables."""

    temp_suffixes: tuple[str, ...] = (".tmp", ".download")
    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
        init=False,
        repr=False,
    )

    def cleanup(
        self,
        docx_path: str | Path,
        pdf_path: str | Path,
        temp_dir: str | Path,
        *,
        delete_docx: bool = True,
    ) -> CleanupResult:
        """Cleanup generated files after PDF creation.

        The PDF is treated as a deliverable and is never removed. The DOCX can
        be removed with `delete_docx=True` when it is only an intermediate
        artifact, or preserved when both DOCX and PDF must be delivered.
        Temporary files with configured suffixes are removed from `temp_dir`.
        """
        docx = Path(docx_path)
        pdf = Path(pdf_path)
        removed_docx = False
        cleanup_errors: list[str] = []

        if delete_docx and docx.exists():
            try:
                docx.unlink()
                removed_docx = True
                self._logger.info("Removed temporary DOCX: %s", docx)
            except OSError as error:
                cleanup_errors.append(str(error))
                self._logger.exception("Failed to remove temporary DOCX: %s", docx)

        removed_temp_files, remaining_temp_files, temp_errors = self.cleanup_temp_files(temp_dir)
        cleanup_errors.extend(temp_errors)
        kept_pdf = pdf.exists()
        self._logger.info(
            "Cleanup completed: removed_docx=%s kept_pdf=%s removed_temp_files=%s",
            removed_docx,
            kept_pdf,
            len(removed_temp_files),
        )
        return CleanupResult(
            removed_docx=removed_docx,
            kept_pdf=kept_pdf,
            removed_temp_files=removed_temp_files,
            remaining_temp_files=remaining_temp_files,
            cleanup_errors=tuple(cleanup_errors),
        )

    def cleanup_temp_files(
        self,
        temp_dir: str | Path,
    ) -> tuple[tuple[Path, ...], tuple[Path, ...], tuple[str, ...]]:
        """Remove known temporary files from `temp_dir`.

        Returns `(removed_temp_files, remaining_temp_files, cleanup_errors)`.
        """
        temp_path = Path(temp_dir)
        if not temp_path.exists():
            return (), (), ()

        removed: list[Path] = []
        remaining: list[Path] = []
        errors: list[str] = []

        for path in self._iter_temp_files(temp_path):
            try:
                path.unlink()
                removed.append(path)
                self._logger.debug("Removed temporary file: %s", path)
            except OSError:
                remaining.append(path)
                errors.append(str(path))
                self._logger.exception("Failed to remove temporary file: %s", path)

        return tuple(removed), tuple(remaining), tuple(errors)

    def _iter_temp_files(self, temp_dir: Path) -> Iterable[Path]:
        for path in temp_dir.rglob("*"):
            if path.is_file() and path.suffix in self.temp_suffixes:
                yield path
