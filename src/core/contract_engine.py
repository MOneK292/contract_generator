"""Central business entry point for contract generation."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.exceptions import TemplateNotFoundError


@dataclass(frozen=True)
class ContractRequest:
    """Input required by the contract engine."""

    project_id: str
    vacancy_id: str
    raw_employee_text: str
    output_docx: Path | None = None
    template_id: str | None = None
    output_pdf_dir: Path | None = None


@dataclass(frozen=True)
class ContractResult:
    """Result returned by the contract engine."""

    success: bool
    output_docx: Path | None
    output_pdf: Path | None
    unresolved_placeholders: list[str]
    execution_time: float
    used_template: Any | None
    employee_fields_count: int
    cleanup_error: str | None = None
    error_message: str | None = None


@dataclass
class ContractEngine:
    """Coordinates template lookup, caching, parsing, processing, and DOCX rendering."""

    template_catalog: Any
    template_cache: Any
    employee_parser: Any
    processor_registry: Any
    docx_renderer: Any
    pdf_converter: Any | None = None
    cleanup_service: Any | None = None
    output_dir: Path = Path("tmp")
    pdf_output_dir: Path | None = None
    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
        init=False,
        repr=False,
    )

    def generate(self, request: ContractRequest | Any) -> ContractResult:
        """Generate a rendered DOCX contract from a contract request."""
        started_at = time.perf_counter()
        output_docx: Path | None = None
        output_pdf: Path | None = None
        used_template: Any | None = None
        employee_fields_count = 0
        cleanup_error: str | None = None

        try:
            contract_request = self._normalize_request(request)
            self._logger.info("Engine started")

            vacancy = self._get_vacancy(
                contract_request.project_id,
                contract_request.vacancy_id,
            )
            used_template = self._get_template(
                contract_request.project_id,
                vacancy,
                contract_request.template_id,
            )
            self._logger.info("Template loaded: %s", getattr(used_template, "id", None))

            template_path = self._get_template_path_with_recovery(
                contract_request,
                vacancy,
                used_template,
            )
            self._logger.info("Template cached locally: %s", template_path)

            raw_fields = self.employee_parser.parse(contract_request.raw_employee_text)
            self._logger.info("Parser completed: %s fields", len(raw_fields))

            employee_fields = self.processor_registry.process(raw_fields)
            employee_fields_count = len(employee_fields)
            self._logger.info("Registry completed: %s fields", employee_fields_count)

            output_docx = contract_request.output_docx or self._default_output_path(
                contract_request.project_id,
                contract_request.vacancy_id,
            )
            render_result = self.docx_renderer.render(
                template_path,
                employee_fields,
                output_docx,
            )
            self._logger.info("Renderer completed: %s", output_docx)
            if self.pdf_converter is not None:
                pdf_output_dir = (
                    contract_request.output_pdf_dir
                    or self.pdf_output_dir
                    or output_docx.parent
                )
                output_pdf = self.pdf_converter.convert(output_docx, pdf_output_dir)
                self._logger.info("PDF conversion completed: %s", output_pdf)
                cleanup_error = self._cleanup_after_pdf(output_docx, output_pdf)
            else:
                cleanup_error = self._cleanup_temp_files(output_docx.parent)

            execution_time = time.perf_counter() - started_at
            self._logger.info("Generation completed in %.3fs", execution_time)
            return ContractResult(
                success=bool(render_result.success),
                output_docx=output_docx,
                output_pdf=output_pdf,
                unresolved_placeholders=list(render_result.unresolved_placeholders),
                execution_time=execution_time,
                used_template=used_template,
                employee_fields_count=employee_fields_count,
                cleanup_error=cleanup_error,
            )
        except Exception as error:
            execution_time = time.perf_counter() - started_at
            self._logger.exception("Generation failed")
            return ContractResult(
                success=False,
                output_docx=output_docx,
                output_pdf=output_pdf,
                unresolved_placeholders=[],
                execution_time=execution_time,
                used_template=used_template,
                employee_fields_count=employee_fields_count,
                cleanup_error=cleanup_error,
                error_message=str(error),
            )

    def _normalize_request(self, request: ContractRequest | Any) -> ContractRequest:
        if isinstance(request, ContractRequest):
            return request

        raw_employee_text = self._get_request_value(
            request,
            "raw_employee_text",
            fallback_name="employee_text",
        )
        output_docx = self._optional_request_path(request, "output_docx")
        if output_docx is None:
            output_docx = self._optional_request_path(request, "output_path")
        output_pdf_dir = self._optional_request_path(request, "output_pdf_dir")

        return ContractRequest(
            project_id=str(self._get_request_value(request, "project_id")),
            vacancy_id=str(self._get_request_value(request, "vacancy_id")),
            raw_employee_text=str(raw_employee_text),
            output_docx=output_docx,
            template_id=self._optional_request_str(request, "template_id"),
            output_pdf_dir=output_pdf_dir,
        )

    def _get_request_value(
        self,
        request: Any,
        name: str,
        *,
        fallback_name: str | None = None,
    ) -> Any:
        if hasattr(request, name):
            return getattr(request, name)
        if isinstance(request, dict) and name in request:
            return request[name]
        if fallback_name is not None:
            if hasattr(request, fallback_name):
                return getattr(request, fallback_name)
            if isinstance(request, dict) and fallback_name in request:
                return request[fallback_name]
        raise AttributeError(f"Request is missing required field: {name}")

    def _optional_request_path(self, request: Any, name: str) -> Path | None:
        value = None
        if hasattr(request, name):
            value = getattr(request, name)
        elif isinstance(request, dict) and name in request:
            value = request[name]

        if value is None:
            return None
        return Path(value)

    def _optional_request_str(self, request: Any, name: str) -> str | None:
        value = None
        if hasattr(request, name):
            value = getattr(request, name)
        elif isinstance(request, dict) and name in request:
            value = request[name]

        if value is None:
            return None
        return str(value)

    def _get_vacancy(self, project_id: str, vacancy_id: str) -> Any:
        self.template_catalog.get_project(project_id)
        for vacancy in self.template_catalog.list_vacancies(project_id):
            if vacancy.id == vacancy_id:
                return vacancy
        raise TemplateNotFoundError(
            f"Vacancy is not configured for project `{project_id}`: {vacancy_id}"
        )

    def _get_template(self, project_id: str, vacancy: Any, template_id: str | None) -> Any:
        if template_id is not None:
            if hasattr(self.template_catalog, "list_templates_for_vacancy"):
                allowed_templates = self.template_catalog.list_templates_for_vacancy(
                    project_id,
                    vacancy.id,
                )
                allowed_template_ids = {template.id for template in allowed_templates}
                if allowed_template_ids and template_id not in allowed_template_ids:
                    raise TemplateNotFoundError(
                        f"Template is not configured for vacancy `{vacancy.id}`: {template_id}"
                    )
            return self.template_catalog.get_template(template_id)
        return self.template_catalog.get_template(vacancy.template_id)

    def _get_template_path_with_recovery(
        self,
        request: ContractRequest,
        vacancy: Any,
        used_template: Any,
    ) -> Path:
        try:
            return self.template_cache.get_template(used_template.google_drive_file_id)
        except Exception as error:
            if not self._is_recoverable_google_error(error):
                raise

            self._logger.warning(
                "Template metadata is stale; refreshing catalog and retrying: %s",
                used_template.google_drive_file_id,
            )
            self._delete_template_cache_metadata(used_template.google_drive_file_id)
            refreshed_catalog = self._refresh_template_catalog()
            if refreshed_catalog is not None:
                self.template_catalog = refreshed_catalog
                vacancy = self._get_vacancy(request.project_id, request.vacancy_id)
                used_template = self._find_refreshed_template(
                    request.project_id,
                    vacancy,
                    request.template_id,
                    getattr(used_template, "name", None),
                )

            return self.template_cache.get_template(used_template.google_drive_file_id)

    def _find_refreshed_template(
        self,
        project_id: str,
        vacancy: Any,
        template_id: str | None,
        template_name: str | None,
    ) -> Any:
        templates = ()
        if hasattr(self.template_catalog, "list_templates_for_vacancy"):
            templates = self.template_catalog.list_templates_for_vacancy(project_id, vacancy.id)
        for template in templates:
            if template_id is not None and template.id == template_id:
                return template
        for template in templates:
            if template_name is not None and template.name == template_name:
                return template
        return self._get_template(project_id, vacancy, template_id)

    def _refresh_template_catalog(self) -> Any | None:
        refresh = getattr(self.template_catalog, "refresh", None)
        if refresh is None:
            return None
        try:
            return refresh()
        except Exception:
            self._logger.exception("Failed to refresh template catalog")
            return None

    def _delete_template_cache_metadata(self, file_id: str) -> None:
        metadata_path = getattr(self.template_cache, "metadata_path", None)
        if metadata_path is None:
            return
        try:
            path = metadata_path(file_id)
            if path.exists():
                path.unlink()
        except Exception:
            self._logger.warning("Failed to delete stale template metadata: %s", file_id)

    def _is_recoverable_google_error(self, error: BaseException) -> bool:
        cause = getattr(error, "__cause__", None)
        response = getattr(cause, "resp", None)
        status = getattr(response, "status", None)
        return status in (403, 404)

    def _cleanup_after_pdf(self, docx_path: Path, pdf_path: Path) -> str | None:
        if self.cleanup_service is None:
            return None
        try:
            result = self.cleanup_service.cleanup(
                docx_path,
                pdf_path,
                docx_path.parent,
                delete_docx=False,
            )
        except Exception as error:
            self._logger.exception("Cleanup failed")
            return str(error)

        if getattr(result, "cleanup_errors", None):
            return "; ".join(result.cleanup_errors)
        self._logger.info("Cleanup completed: %s", docx_path.parent)
        return None

    def _cleanup_temp_files(self, temp_dir: Path) -> str | None:
        if self.cleanup_service is None:
            return None
        try:
            result = self.cleanup_service.cleanup_temp_files(temp_dir)
        except Exception as error:
            self._logger.exception("Cleanup failed")
            return str(error)

        cleanup_errors = ()
        if isinstance(result, tuple) and len(result) >= 3:
            cleanup_errors = result[2]
        if cleanup_errors:
            return "; ".join(cleanup_errors)
        self._logger.info("Cleanup completed: %s", temp_dir)
        return None

    def _default_output_path(self, project_id: str, vacancy_id: str) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        filename = (
            f"{self._safe_filename(project_id)}_"
            f"{self._safe_filename(vacancy_id)}_"
            f"{timestamp}.docx"
        )
        return self.output_dir / filename

    def _safe_filename(self, value: str) -> str:
        safe_value = re.sub(r"[^A-Za-z0-9_.-]", "_", value)
        return safe_value or "contract"
