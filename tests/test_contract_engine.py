"""Tests for ContractEngine orchestration."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

from src.core.contract_engine import ContractEngine, ContractRequest
from src.core.exceptions import RenderingError, TemplateNotFoundError
from src.services.google.drive import GoogleDriveError


class ContractEngineTest(unittest.TestCase):
    """Contract engine behavior."""

    def test_successful_pipeline(self) -> None:
        engine, dependencies = self._engine()
        request = ContractRequest(
            project_id="project",
            vacancy_id="vacancy",
            raw_employee_text="ФИО: Иванов Иван Иванович",
            output_docx=Path("tmp/output.docx"),
        )

        result = engine.generate(request)

        self.assertTrue(result.success)
        self.assertEqual(result.output_docx, Path("tmp/output.docx"))
        self.assertEqual(result.unresolved_placeholders, [])
        self.assertEqual(result.used_template.id, "template")
        self.assertEqual(result.employee_fields_count, 2)
        self.assertIsNone(result.error_message)
        dependencies.template_cache.get_template.assert_called_once_with("drive-file")
        dependencies.employee_parser.parse.assert_called_once_with(
            "ФИО: Иванов Иван Иванович"
        )
        dependencies.processor_registry.process.assert_called_once_with(
            {"ФИО": "Иванов Иван Иванович"}
        )
        dependencies.docx_renderer.render.assert_called_once_with(
            Path("cache/template.docx"),
            {"ФИО": "Иванов Иван Иванович", "Ф": "Иванов"},
            Path("tmp/output.docx"),
        )

    def test_parser_error_returns_failed_result(self) -> None:
        engine, dependencies = self._engine()
        dependencies.employee_parser.parse.side_effect = ValueError("bad text")

        result = engine.generate(self._request())

        self.assertFalse(result.success)
        self.assertIsNone(result.output_docx)
        self.assertIn("bad text", result.error_message)

    def test_renderer_error_returns_failed_result(self) -> None:
        engine, dependencies = self._engine()
        dependencies.docx_renderer.render.side_effect = RenderingError("render failed")

        result = engine.generate(self._request(output_docx=Path("tmp/output.docx")))

        self.assertFalse(result.success)
        self.assertEqual(result.output_docx, Path("tmp/output.docx"))
        self.assertIn("render failed", result.error_message)

    def test_google_error_returns_failed_result(self) -> None:
        engine, dependencies = self._engine()
        dependencies.template_cache.get_template.side_effect = GoogleDriveError(
            "google failed"
        )

        result = engine.generate(self._request())

        self.assertFalse(result.success)
        self.assertIsNone(result.output_docx)
        self.assertEqual(result.used_template.id, "template")
        self.assertIn("google failed", result.error_message)

    def test_refreshes_catalog_and_retries_after_stale_google_metadata_404(self) -> None:
        with TemporaryDirectory() as temp_dir:
            engine, dependencies = self._engine()
            metadata_path = Path(temp_dir) / "drive-file.json"
            metadata_path.write_text("{}", encoding="utf-8")
            error = GoogleDriveError("stale metadata")
            cause = Exception("404")
            cause.resp = SimpleNamespace(status=404)
            error.__cause__ = cause
            dependencies.template_cache.get_template.side_effect = [
                error,
                Path("cache/template.docx"),
            ]
            dependencies.template_cache.metadata_path.return_value = metadata_path
            dependencies.template_catalog.refresh.return_value = None

            result = engine.generate(self._request())

            self.assertTrue(result.success)
            self.assertFalse(metadata_path.exists())
            dependencies.template_catalog.refresh.assert_called_once()
            self.assertEqual(dependencies.template_cache.get_template.call_count, 2)

    def test_empty_text_is_processed(self) -> None:
        engine, dependencies = self._engine()
        dependencies.employee_parser.parse.return_value = {}
        dependencies.processor_registry.process.return_value = {}

        result = engine.generate(self._request(raw_employee_text=""))

        self.assertTrue(result.success)
        self.assertEqual(result.employee_fields_count, 0)
        dependencies.employee_parser.parse.assert_called_once_with("")
        dependencies.docx_renderer.render.assert_called_once()

    def test_unknown_project_returns_failed_result(self) -> None:
        engine, dependencies = self._engine()
        dependencies.template_catalog.get_project.side_effect = TemplateNotFoundError(
            "unknown project"
        )

        result = engine.generate(self._request(project_id="unknown"))

        self.assertFalse(result.success)
        self.assertIn("unknown project", result.error_message)
        dependencies.template_cache.get_template.assert_not_called()

    def test_unknown_vacancy_returns_failed_result(self) -> None:
        engine, dependencies = self._engine()
        dependencies.template_catalog.list_vacancies.return_value = []

        result = engine.generate(self._request(vacancy_id="unknown"))

        self.assertFalse(result.success)
        self.assertIn("Vacancy is not configured", result.error_message)
        dependencies.template_cache.get_template.assert_not_called()

    def test_unresolved_placeholders_are_returned(self) -> None:
        engine, dependencies = self._engine()
        dependencies.docx_renderer.render.return_value = SimpleNamespace(
            success=True,
            unresolved_placeholders=["ИНН", "Паспорт"],
        )

        result = engine.generate(self._request())

        self.assertTrue(result.success)
        self.assertEqual(result.unresolved_placeholders, ["ИНН", "Паспорт"])

    def test_cleanup_service_runs_after_successful_render(self) -> None:
        cleanup_service = Mock()
        engine, dependencies = self._engine(cleanup_service=cleanup_service)

        result = engine.generate(self._request(output_docx=Path("tmp/output.docx")))

        self.assertTrue(result.success)
        cleanup_service.cleanup_temp_files.assert_called_once_with(Path("tmp"))

    def test_accepts_dict_request_with_employee_text_alias(self) -> None:
        engine, dependencies = self._engine()

        result = engine.generate(
            {
                "project_id": "project",
                "vacancy_id": "vacancy",
                "employee_text": "ФИО: Иванов Иван Иванович",
                "output_path": "tmp/output.docx",
            }
        )

        self.assertTrue(result.success)
        self.assertEqual(result.output_docx, Path("tmp/output.docx"))
        dependencies.employee_parser.parse.assert_called_once_with(
            "ФИО: Иванов Иван Иванович"
        )

    def _engine(self, cleanup_service=None) -> tuple[ContractEngine, SimpleNamespace]:
        template = SimpleNamespace(
            id="template",
            name="Template",
            google_drive_file_id="drive-file",
        )
        vacancy = SimpleNamespace(id="vacancy", name="Vacancy", template_id="template")

        template_catalog = Mock()
        template_catalog.get_project.return_value = SimpleNamespace(id="project")
        template_catalog.list_vacancies.return_value = [vacancy]
        template_catalog.get_template.return_value = template
        template_catalog.list_templates_for_vacancy.return_value = []

        template_cache = Mock()
        template_cache.get_template.return_value = Path("cache/template.docx")

        employee_parser = Mock()
        employee_parser.parse.return_value = {"ФИО": "Иванов Иван Иванович"}

        processor_registry = Mock()
        processor_registry.process.return_value = {
            "ФИО": "Иванов Иван Иванович",
            "Ф": "Иванов",
        }

        docx_renderer = Mock()
        docx_renderer.render.return_value = SimpleNamespace(
            success=True,
            unresolved_placeholders=[],
        )

        dependencies = SimpleNamespace(
            template_catalog=template_catalog,
            template_cache=template_cache,
            employee_parser=employee_parser,
            processor_registry=processor_registry,
            docx_renderer=docx_renderer,
        )
        return (
            ContractEngine(
                template_catalog=template_catalog,
                template_cache=template_cache,
                employee_parser=employee_parser,
                processor_registry=processor_registry,
                docx_renderer=docx_renderer,
                cleanup_service=cleanup_service,
                output_dir=Path("tmp"),
            ),
            dependencies,
        )

    def _request(
        self,
        *,
        project_id: str = "project",
        vacancy_id: str = "vacancy",
        raw_employee_text: str = "ФИО: Иванов Иван Иванович",
        output_docx: Path | None = None,
    ) -> ContractRequest:
        return ContractRequest(
            project_id=project_id,
            vacancy_id=vacancy_id,
            raw_employee_text=raw_employee_text,
            output_docx=output_docx,
        )


if __name__ == "__main__":
    unittest.main()
