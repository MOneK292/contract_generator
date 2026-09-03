"""Tests for cleanup service."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.services.cleanup.cleanup_service import CleanupService


class CleanupServiceTest(unittest.TestCase):
    """Cleanup service behavior."""

    def test_cleanup_removes_docx_and_temp_files_but_keeps_pdf(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docx = self._file(root / "contract.docx")
            pdf = self._file(root / "contract.pdf")
            temp_file = self._file(root / "work.tmp")
            download_file = self._file(root / "nested" / "file.download")

            result = CleanupService().cleanup(docx, pdf, root)

            self.assertTrue(result.removed_docx)
            self.assertFalse(docx.exists())
            self.assertTrue(result.kept_pdf)
            self.assertTrue(pdf.exists())
            self.assertFalse(temp_file.exists())
            self.assertFalse(download_file.exists())
            self.assertEqual(result.remaining_temp_files, ())
            self.assertEqual(result.cleanup_errors, ())
            self.assertEqual(set(result.removed_temp_files), {temp_file, download_file})

    def test_cleanup_can_keep_docx(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docx = self._file(root / "contract.docx")
            pdf = self._file(root / "contract.pdf")

            result = CleanupService().cleanup(docx, pdf, root, delete_docx=False)

            self.assertFalse(result.removed_docx)
            self.assertTrue(docx.exists())
            self.assertTrue(result.kept_pdf)

    def test_cleanup_temp_files_ignores_deliverables(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docx = self._file(root / "contract.docx")
            pdf = self._file(root / "contract.pdf")
            temp_file = self._file(root / "work.tmp")

            removed, remaining, errors = CleanupService().cleanup_temp_files(root)

            self.assertEqual(removed, (temp_file,))
            self.assertEqual(remaining, ())
            self.assertEqual(errors, ())
            self.assertTrue(docx.exists())
            self.assertTrue(pdf.exists())
            self.assertFalse(temp_file.exists())

    def test_cleanup_temp_files_missing_directory(self) -> None:
        removed, remaining, errors = CleanupService().cleanup_temp_files(Path("missing"))

        self.assertEqual(removed, ())
        self.assertEqual(remaining, ())
        self.assertEqual(errors, ())

    def _file(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"content")
        return path


if __name__ == "__main__":
    unittest.main()
