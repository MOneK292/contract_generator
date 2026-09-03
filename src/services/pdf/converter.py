"""PDF conversion service."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.core.exceptions import PdfConversionError
from src.services.config.settings_loader import AppConfig


def _find_libreoffice_executable() -> Path | None:
    """Search for soffice/soffice.exe in standard installation paths."""
    candidates = [
        # Linux / Docker standard paths
        Path("/usr/bin/soffice"),
        Path("/usr/lib/libreoffice/program/soffice"),
        Path("/opt/libreoffice/program/soffice"),
        # Windows standard paths
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    ]
    for path in candidates:
        if path.exists() and path.is_file():
            return path

    # Try system PATH
    found = shutil.which("soffice")
    if found:
        return Path(found)

    return None


@dataclass
class PdfConverter:
    """Converts DOCX files to PDF.

    Tries LibreOffice first (via configured path or auto-detection).
    Falls back to ``docx2pdf`` if LibreOffice is unavailable.
    """

    config: AppConfig
    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
        init=False,
        repr=False,
    )

    def convert(self, input_docx: str | Path, output_directory: str | Path) -> Path:
        """Convert a DOCX file to PDF and return the generated PDF path."""
        docx_path = Path(input_docx)
        output_dir = Path(output_directory)

        if not docx_path.exists() or not docx_path.is_file():
            raise PdfConversionError(f"DOCX file does not exist: {docx_path}")

        output_dir.mkdir(parents=True, exist_ok=True)

        # Determine LibreOffice executable: configured path or auto-detected
        executable = self.config.libreoffice.executable_path
        if executable is None or not executable.exists():
            executable = _find_libreoffice_executable()

        if executable is not None:
            return self._convert_with_libreoffice(docx_path, output_dir, executable)

        return self._convert_with_docx2pdf(docx_path, output_dir)

    # ------------------------------------------------------------------
    # LibreOffice backend
    # ------------------------------------------------------------------

    def _convert_with_libreoffice(
        self,
        docx_path: Path,
        output_dir: Path,
        executable: Path,
    ) -> Path:
        command = [
            str(executable),
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(docx_path),
        ]

        self._logger.info("PDF conversion via LibreOffice: %s", docx_path)
        start = time.perf_counter()

        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.config.libreoffice.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            elapsed = time.perf_counter() - start
            self._logger.error(
                "LibreOffice conversion timed out after %.3fs: %s",
                elapsed,
                docx_path,
            )
            raise PdfConversionError(
                f"LibreOffice conversion timed out: {docx_path}"
            ) from error
        except OSError as error:
            self._logger.exception("Failed to start LibreOffice: %s", executable)
            raise PdfConversionError(
                f"Failed to start LibreOffice: {executable}"
            ) from error

        elapsed = time.perf_counter() - start
        self._logger.info("LibreOffice stdout: %s", process.stdout.strip())
        self._logger.info("LibreOffice stderr: %s", process.stderr.strip())

        if process.returncode != 0:
            self._logger.error(
                "LibreOffice conversion failed with code %s in %.3fs",
                process.returncode,
                elapsed,
            )
            raise PdfConversionError(
                f"LibreOffice conversion failed with code {process.returncode}: {docx_path}"
            )

        pdf_path = output_dir / f"{docx_path.stem}.pdf"
        if not pdf_path.exists():
            raise PdfConversionError(
                f"LibreOffice did not generate PDF: {pdf_path}"
            )

        self._logger.info(
            "PDF conversion completed in %.3fs: %s", elapsed, pdf_path
        )
        return pdf_path

    # ------------------------------------------------------------------
    # docx2pdf backend (fallback when LibreOffice is not installed)
    # ------------------------------------------------------------------

    def _convert_with_docx2pdf(
        self,
        docx_path: Path,
        output_dir: Path,
    ) -> Path:
        try:
            from docx2pdf import convert  # type: ignore[import]
        except ImportError as error:
            raise PdfConversionError(
                "PDF-конвертация недоступна: LibreOffice не найден и пакет "
                "docx2pdf не установлен. Выполните: pip install docx2pdf"
            ) from error

        pdf_path = output_dir / f"{docx_path.stem}.pdf"
        self._logger.info("PDF conversion via docx2pdf: %s", docx_path)
        start = time.perf_counter()
        try:
            convert(str(docx_path), str(pdf_path))
        except Exception as error:
            raise PdfConversionError(
                f"docx2pdf conversion failed: {docx_path}"
            ) from error

        elapsed = time.perf_counter() - start
        if not pdf_path.exists():
            raise PdfConversionError(
                f"docx2pdf did not generate PDF: {pdf_path}"
            )

        self._logger.info(
            "PDF conversion completed in %.3fs: %s", elapsed, pdf_path
        )
        return pdf_path
