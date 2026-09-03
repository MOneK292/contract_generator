"""Tests for LibreOffice PDF conversion."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from src.core.exceptions import PdfConversionError
from src.services.pdf.converter import PdfConverter


class PdfConverterTest(unittest.TestCase):
    """PDF converter behavior."""

    def test_success(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._file(root / "soffice.exe")
            docx = self._file(root / "contract.docx")
            output_dir = root / "pdf"
            pdf = output_dir / "contract.pdf"

            def run(command, **kwargs):
                pdf.write_bytes(b"pdf")
                return subprocess.CompletedProcess(command, 0, "ok", "")

            with patch("src.services.pdf.converter.subprocess.run", side_effect=run) as run_mock:
                result = PdfConverter(self._config(executable)).convert(docx, output_dir)

            self.assertEqual(result, pdf)
            run_mock.assert_called_once()
            command = run_mock.call_args.args[0]
            self.assertEqual(
                command,
                [
                    str(executable),
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(output_dir),
                    str(docx),
                ],
            )
            self.assertEqual(run_mock.call_args.kwargs["timeout"], 60)

    def test_process_failed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._file(root / "soffice.exe")
            docx = self._file(root / "contract.docx")
            process = subprocess.CompletedProcess(["soffice"], 1, "stdout", "stderr")

            with patch("src.services.pdf.converter.subprocess.run", return_value=process):
                with self.assertRaises(PdfConversionError):
                    PdfConverter(self._config(executable)).convert(docx, root / "pdf")

    def test_timeout(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._file(root / "soffice.exe")
            docx = self._file(root / "contract.docx")

            with patch(
                "src.services.pdf.converter.subprocess.run",
                side_effect=subprocess.TimeoutExpired("soffice", 60),
            ):
                with self.assertRaises(PdfConversionError):
                    PdfConverter(self._config(executable)).convert(docx, root / "pdf")

    def test_pdf_not_generated(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._file(root / "soffice.exe")
            docx = self._file(root / "contract.docx")
            process = subprocess.CompletedProcess(["soffice"], 0, "stdout", "")

            with patch("src.services.pdf.converter.subprocess.run", return_value=process):
                with self.assertRaises(PdfConversionError):
                    PdfConverter(self._config(executable)).convert(docx, root / "pdf")

    def test_wrong_executable(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docx = self._file(root / "contract.docx")

            with self.assertRaises(PdfConversionError):
                PdfConverter(self._config(root / "missing-soffice.exe")).convert(
                    docx,
                    root / "pdf",
                )

    def test_unconfigured_libreoffice_has_clear_error(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docx = self._file(root / "contract.docx")

            with patch.dict("sys.modules", {"docx2pdf": None}):
                with self.assertRaises(PdfConversionError) as context:
                    PdfConverter(self._config(None)).convert(docx, root / "pdf")

        self.assertIn("PDF-конвертация недоступна", str(context.exception))

    def test_start_error(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            executable = self._file(root / "soffice.exe")
            docx = self._file(root / "contract.docx")

            with patch(
                "src.services.pdf.converter.subprocess.run",
                side_effect=OSError("cannot start"),
            ):
                with self.assertRaises(PdfConversionError):
                    PdfConverter(self._config(executable)).convert(docx, root / "pdf")

    def _config(self, executable: Path | None):
        return SimpleNamespace(
            libreoffice=SimpleNamespace(
                executable_path=executable,
                timeout_seconds=60,
            )
        )

    def _file(self, path: Path) -> Path:
        path.write_bytes(b"content")
        return path


if __name__ == "__main__":
    unittest.main()
