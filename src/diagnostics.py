"""Backend readiness diagnostics.

Run with:

    python -m src.diagnostics

The diagnostics command checks the production infrastructure without starting
Telegram or PDF conversion. Every check is isolated: failures are reported in
the final table, but the command continues with the remaining checks whenever
the required dependencies are available.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, load_dotenv

from src.core.exceptions import ConfigurationError
from src.models.template import Template
from src.services.config import AppConfig, SettingsLoader, TemplateCatalog
from src.services.docx import DocxRenderer
from src.services.google import (
    GoogleAuth,
    GoogleDriveCatalogService,
    GoogleDriveError,
    GoogleDriveService,
    GoogleFileMetadata,
    TemplateCache,
)
from src.services.google.catalog import normalize_template_folder_path
from src.services.google.drive import is_word_template


OK = "✓"
WARNING = "⚠"
ERROR = "✗"


@dataclass(frozen=True)
class DiagnosticStatus:
    """Single diagnostic status shown in the final table."""

    name: str
    marker: str
    message: str

    @property
    def failed(self) -> bool:
        """Return whether this status represents a failed critical check."""
        return self.marker == ERROR


@dataclass(frozen=True)
class DriveTemplateNode:
    """Template file discovered in a Google Drive vacancy folder."""

    file_id: str
    name: str


@dataclass(frozen=True)
class DriveVacancyNode:
    """Template-containing folder discovered below a Google Drive project folder."""

    file_id: str
    name: str
    templates: tuple[DriveTemplateNode, ...]


@dataclass(frozen=True)
class DriveProjectNode:
    """Project folder discovered below the Google Drive root folder."""

    file_id: str
    name: str
    vacancies: tuple[DriveVacancyNode, ...]


@dataclass(frozen=True)
class DriveTree:
    """Google Drive project/vacancy/template tree."""

    root_name: str
    projects: tuple[DriveProjectNode, ...]

    def first_template(self) -> DriveTemplateNode | None:
        """Return the first discovered template, if any."""
        for project in self.projects:
            for vacancy in project.vacancies:
                if vacancy.templates:
                    return vacancy.templates[0]
        return None

    def template_ids(self) -> set[str]:
        """Return all template file ids from the Drive tree."""
        return {
            template.file_id
            for project in self.projects
            for vacancy in project.vacancies
            for template in vacancy.templates
        }

    def vacancy_count(self) -> int:
        """Return the number of discovered vacancy folders."""
        return sum(len(project.vacancies) for project in self.projects)

    def template_count(self) -> int:
        """Return the number of discovered DOCX/DOCM templates."""
        return sum(
            len(vacancy.templates)
            for project in self.projects
            for vacancy in project.vacancies
        )


@dataclass
class DiagnosticsReport:
    """Accumulated diagnostics output."""

    statuses: list[DiagnosticStatus] = field(default_factory=list)
    details: list[str] = field(default_factory=list)

    def ok(self, name: str, message: str) -> None:
        """Append a successful diagnostic status."""
        self.statuses.append(DiagnosticStatus(name, OK, message))

    def warning(self, name: str, message: str) -> None:
        """Append a non-critical diagnostic warning."""
        self.statuses.append(DiagnosticStatus(name, WARNING, message))

    def error(self, name: str, message: str) -> None:
        """Append a failed critical diagnostic status."""
        self.statuses.append(DiagnosticStatus(name, ERROR, message))

    def detail(self, message: str) -> None:
        """Append a detailed message shown before the final table."""
        self.details.append(message)

    def has_errors(self) -> bool:
        """Return whether any critical check failed."""
        return any(status.failed for status in self.statuses)


@dataclass
class DiagnosticsRunner:
    """Runs backend readiness checks for configuration, Drive, cache and DOCX."""

    root_dir: Path = field(default_factory=lambda: Path.cwd().resolve())
    show_tracebacks: bool = False

    def run(self) -> DiagnosticsReport:
        """Run all diagnostics and return a structured report."""
        report = DiagnosticsReport()
        env = self._load_env(report)
        config = self._load_config(report, env)

        credentials_data: dict[str, Any] | None = None
        if config is not None:
            credentials_data = self._check_credentials(report, config.google.credentials_path)
        elif env.get("GOOGLE_CREDENTIALS"):
            credentials_data = self._check_credentials(
                report,
                self._resolve_path(env["GOOGLE_CREDENTIALS"]),
            )
        else:
            report.error("Credentials", "GOOGLE_CREDENTIALS is not configured")

        drive_service: GoogleDriveService | None = None
        if config is not None and credentials_data is not None:
            drive_service = self._check_google_auth(report, config)
        elif config is not None:
            report.error("Google Auth", "Skipped because credentials are invalid")
        else:
            report.error("Google Auth", "Skipped because configuration did not load")

        drive_tree: DriveTree | None = None
        if config is not None and drive_service is not None:
            drive_tree = self._check_root_and_tree(report, config, drive_service)
        else:
            report.error("Root Folder", "Skipped because Google Drive is unavailable")
            report.error("Project Tree", "Skipped because Google Drive is unavailable")

        catalog: TemplateCatalog | None = None
        if config is not None and drive_service is not None and drive_tree is not None:
            catalog = self._check_template_catalog(report, config, drive_service, drive_tree)
        else:
            report.error("TemplateCatalog", "Skipped because project tree is unavailable")

        downloaded_template: Path | None = None
        if config is not None and drive_service is not None and drive_tree is not None:
            downloaded_template = self._check_template_cache(
                report,
                config,
                drive_service,
                drive_tree,
            )
        else:
            report.error("Template Cache", "Skipped because project tree is unavailable")

        if config is not None and downloaded_template is not None:
            self._check_renderer(report, config, downloaded_template)
        else:
            report.error("Renderer", "Skipped because template download is unavailable")

        if catalog is not None and drive_tree is not None:
            self._report_catalog_summary(report, catalog, drive_tree)

        return report

    def _load_env(self, report: DiagnosticsReport) -> dict[str, str]:
        env_file = self.root_dir / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)
            file_values = dotenv_values(env_file)
            report.detail(f".env loaded: {env_file}")
        else:
            file_values = {}
            report.detail(f".env file not found: {env_file}; using process environment")

        env = {
            key: value
            for key, value in file_values.items()
            if value is not None
        }
        env.update(os.environ)

        missing: list[str] = []
        for key in ("BOT_TOKEN", "GOOGLE_CREDENTIALS", "GOOGLE_DRIVE_ROOT_FOLDER_ID"):
            if env.get(key, "").strip():
                report.detail(f"{OK} {key} found")
            else:
                missing.append(key)
                report.detail(f"{ERROR} {key} is missing")

        libreoffice_path = env.get("LIBREOFFICE_PATH", "").strip()
        if libreoffice_path:
            report.detail(f"{OK} LIBREOFFICE_PATH found: {libreoffice_path}")
        else:
            report.detail(f"{WARNING} LIBREOFFICE_PATH is empty")

        if missing:
            report.error("ENV", "Missing required variables: " + ", ".join(missing))
        else:
            report.ok("ENV", "Required environment variables are present")

        if not libreoffice_path:
            report.warning("LibreOffice", "LibreOffice not configured; PDF conversion disabled")
        else:
            executable = self._resolve_path(libreoffice_path)
            if executable.exists() and executable.is_file():
                report.ok("LibreOffice", f"Configured: {executable}")
            else:
                report.warning(
                    "LibreOffice",
                    f"LibreOffice executable not found: {executable}; PDF conversion disabled",
                )

        return env

    def _load_config(
        self,
        report: DiagnosticsReport,
        env: dict[str, str],
    ) -> AppConfig | None:
        try:
            config = SettingsLoader(root_dir=self.root_dir).load(
                validate_external_paths=False
            )
        except ConfigurationError as error:
            report.error("Configuration", str(error))
            self._maybe_detail_traceback(report)
            return None
        except Exception as error:
            report.error("Configuration", f"Failed to load settings: {error}")
            self._maybe_detail_traceback(report)
            return None

        if not config.google.drive_root_folder_id.strip():
            report.error("Configuration", "GOOGLE_DRIVE_ROOT_FOLDER_ID is empty")
            return None
        report.ok("Configuration", "settings.yaml and templates.yaml loaded")
        return config

    def _check_credentials(
        self,
        report: DiagnosticsReport,
        credentials_path: Path,
    ) -> dict[str, Any] | None:
        if not credentials_path.exists():
            report.error("Credentials", f"File does not exist: {credentials_path}")
            return None
        if not credentials_path.is_file():
            report.error("Credentials", f"Path is not a file: {credentials_path}")
            return None

        try:
            with credentials_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as error:
            report.error("Credentials", f"Invalid JSON: {error}")
            return None
        except OSError as error:
            report.error("Credentials", f"Cannot read credentials: {error}")
            return None

        required_fields = ("project_id", "client_email", "private_key", "token_uri")
        missing = [
            field_name
            for field_name in required_fields
            if not str(data.get(field_name, "")).strip()
        ]
        if missing:
            report.error(
                "Credentials",
                "Missing required fields: " + ", ".join(missing),
            )
            return None

        report.ok("Credentials", f"client_email: {data['client_email']}")
        return data

    def _check_google_auth(
        self,
        report: DiagnosticsReport,
        config: AppConfig,
    ) -> GoogleDriveService | None:
        try:
            client = GoogleAuth(config).create_drive_client()
        except Exception as error:
            report.error("Google Auth", f"Failed to create Google Drive client: {error}")
            self._maybe_detail_traceback(report)
            return None

        report.ok("Google Auth", "Google authentication OK")
        return GoogleDriveService(client)

    def _check_root_and_tree(
        self,
        report: DiagnosticsReport,
        config: AppConfig,
        drive_service: GoogleDriveService,
    ) -> DriveTree | None:
        root_id = config.google.drive_root_folder_id
        try:
            root_metadata = drive_service.get_file_metadata(root_id)
            projects = drive_service.list_folders(root_id)
        except GoogleDriveError as error:
            report.error("Root Folder", f"Cannot access root folder {root_id}: {error}")
            self._maybe_detail_traceback(report)
            report.error("Project Tree", "Skipped because root folder is unavailable")
            return None

        root_name = root_metadata.name or root_id
        project_names = ", ".join(project.name or project.file_id for project in projects)
        report.ok(
            "Root Folder",
            f"{root_name}; projects: {len(projects)}"
            + (f" ({project_names})" if project_names else ""),
        )

        try:
            tree = self._read_drive_tree(root_metadata, projects, drive_service)
        except GoogleDriveError as error:
            report.error("Project Tree", f"Failed to read Drive tree: {error}")
            self._maybe_detail_traceback(report)
            return None

        report.ok(
            "Project Tree",
            (
                f"projects: {len(tree.projects)}, vacancies: {tree.vacancy_count()}, "
                f"templates: {tree.template_count()}"
            ),
        )
        if tree.projects:
            report.ok("Projects", f"{len(tree.projects)} project folders found")
        else:
            report.error("Projects", "No project folders found")

        if tree.vacancy_count():
            report.ok("Vacancies", f"{tree.vacancy_count()} vacancy folders found")
        else:
            report.error("Vacancies", "No vacancy folders found")

        if tree.template_count():
            report.ok("Templates", f"{tree.template_count()} DOCX/DOCM templates found")
        else:
            report.error("Templates", "No DOCX/DOCM templates found")

        report.detail(self._format_drive_tree(tree))
        return tree

    def _read_drive_tree(
        self,
        root_metadata: GoogleFileMetadata,
        projects: tuple[GoogleFileMetadata, ...],
        drive_service: GoogleDriveService,
    ) -> DriveTree:
        project_nodes: list[DriveProjectNode] = []
        for project in projects:
            vacancy_nodes = self._read_template_folders(
                drive_service,
                project,
                path_parts=[],
            )
            project_nodes.append(
                DriveProjectNode(
                    file_id=project.file_id,
                    name=project.name or project.file_id,
                    vacancies=tuple(vacancy_nodes),
                )
            )

        return DriveTree(
            root_name=root_metadata.name or root_metadata.file_id,
            projects=tuple(project_nodes),
        )

    def _read_template_folders(
        self,
        drive_service: GoogleDriveService,
        folder: GoogleFileMetadata,
        path_parts: list[str],
    ) -> tuple[DriveVacancyNode, ...]:
        children = drive_service.list_children(folder.file_id)
        templates = tuple(
            DriveTemplateNode(
                file_id=template.file_id,
                name=template.name or template.file_id,
            )
            for template in children
            if is_word_template(template)
        )
        child_folders = [child for child in children if child.is_folder]

        nodes: list[DriveVacancyNode] = []
        if templates:
            nodes.append(
                DriveVacancyNode(
                    file_id=self._template_folder_id(folder, path_parts),
                    name=self._template_folder_name(path_parts),
                    templates=templates,
                )
            )

        for child_folder in child_folders:
            nodes.extend(
                self._read_template_folders(
                    drive_service,
                    child_folder,
                    [*path_parts, child_folder.name or child_folder.file_id],
                )
            )

        return tuple(nodes)

    def _template_folder_id(
        self,
        folder: GoogleFileMetadata,
        path_parts: list[str],
    ) -> str:
        if path_parts:
            return folder.file_id
        return f"{folder.file_id}:root"

    def _template_folder_name(self, path_parts: list[str]) -> str:
        return normalize_template_folder_path(path_parts)

    def _check_template_catalog(
        self,
        report: DiagnosticsReport,
        config: AppConfig,
        drive_service: GoogleDriveService,
        drive_tree: DriveTree,
    ) -> TemplateCatalog | None:
        try:
            catalog = GoogleDriveCatalogService(config, drive_service).load_catalog(
                force_refresh=True
            )
        except Exception as error:
            report.error("TemplateCatalog", f"Failed to build catalog: {error}")
            self._maybe_detail_traceback(report)
            return None

        catalog_project_ids = {project.id for project in catalog.list_projects()}
        drive_project_ids = {project.file_id for project in drive_tree.projects}
        catalog_vacancy_ids = {
            vacancy.id
            for project_vacancies in catalog.list_project_vacancies()
            for vacancy in project_vacancies.vacancies
        }
        drive_vacancy_ids_with_templates = {
            vacancy.file_id
            for project in drive_tree.projects
            for vacancy in project.vacancies
            if vacancy.templates
        }
        empty_vacancies = sorted(
            vacancy.name
            for project in drive_tree.projects
            for vacancy in project.vacancies
            if not vacancy.templates
        )
        catalog_template_ids = {
            template.google_drive_file_id for template in catalog.list_templates()
        }
        drive_template_ids = drive_tree.template_ids()

        mismatches = []
        self._append_set_mismatch(
            mismatches,
            "projects",
            drive_project_ids,
            catalog_project_ids,
        )
        self._append_set_mismatch(
            mismatches,
            "vacancies",
            drive_vacancy_ids_with_templates,
            catalog_vacancy_ids,
        )
        self._append_set_mismatch(
            mismatches,
            "templates",
            drive_template_ids,
            catalog_template_ids,
        )

        if empty_vacancies:
            report.warning(
                "TemplateCatalog",
                "Vacancies without DOCX/DOCM templates are not included: "
                + ", ".join(empty_vacancies),
            )

        if mismatches:
            report.error("TemplateCatalog", "; ".join(mismatches))
            return catalog
        if empty_vacancies:
            return catalog

        report.ok("TemplateCatalog", "Catalog matches Google Drive tree")
        return catalog

    def _append_set_mismatch(
        self,
        messages: list[str],
        label: str,
        expected: set[str],
        actual: set[str],
    ) -> None:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            messages.append(f"{label} missing in catalog: " + ", ".join(missing))
        if extra:
            messages.append(f"{label} extra in catalog: " + ", ".join(extra))

    def _check_template_cache(
        self,
        report: DiagnosticsReport,
        config: AppConfig,
        drive_service: GoogleDriveService,
        drive_tree: DriveTree,
    ) -> Path | None:
        template = drive_tree.first_template()
        if template is None:
            report.error("Template Cache", "No DOCX/DOCM templates found in Google Drive tree")
            return None

        try:
            path = TemplateCache(config, drive_service).get_template(
                template.file_id,
                template.name,
            )
        except Exception as error:
            report.error("Template Cache", f"Failed to download template: {error}")
            self._maybe_detail_traceback(report)
            return None

        report.ok("Template Cache", f"Downloaded template: {path}")
        return path

    def _check_renderer(
        self,
        report: DiagnosticsReport,
        config: AppConfig,
        template_path: Path,
    ) -> None:
        output_path = config.paths.temp_dir / "diagnostics_rendered.docx"
        data = {
            "ФИО": "Иванов Иван Иванович",
            "Ф": "Иванов",
            "И": "Иван",
            "О": "Иванович",
            "ИНН": "123456789012",
            "Ставка": "316,00",
            "Плата": "316,00",
            "Дата выдачи": "15.04.2021",
            "Месяц": "апреля",
            "День": "15",
            "Год": "2021",
            "Город": "Санкт-Петербург",
        }

        try:
            result = DocxRenderer().render(template_path, data, output_path)
        except Exception as error:
            report.error(
                "Renderer",
                "Failed to render DOCX/DOCM template: "
                + self._format_exception_chain(error),
            )
            report.detail(self._format_template_file_diagnostics(template_path))
            self._maybe_detail_traceback(report)
            return

        unresolved = ", ".join(result.unresolved_placeholders)
        if unresolved:
            report.ok(
                "Renderer",
                f"DOCX saved: {output_path}; unresolved placeholders: {unresolved}",
            )
        else:
            report.ok("Renderer", f"DOCX saved: {output_path}; no unresolved placeholders")

    def _format_exception_chain(self, error: BaseException) -> str:
        exceptions: list[str] = []
        current: BaseException | None = error
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            exceptions.append(f"{type(current).__name__}: {current}")
            current = current.__cause__ or current.__context__
        return " <- ".join(exceptions)

    def _format_template_file_diagnostics(self, template_path: Path) -> str:
        path = Path(template_path)
        exists = path.exists()
        suffix = path.suffix or "(none)"
        size = path.stat().st_size if exists and path.is_file() else None
        first_bytes = self._read_first_bytes(path)
        is_zip, zip_error = self._check_zip(path)
        lines = [
            "Template file diagnostics:",
            f"  path: {path}",
            f"  exists: {exists}",
            f"  size: {size if size is not None else 'n/a'}",
            f"  extension: {suffix}",
            f"  first bytes: {first_bytes}",
            f"  valid zip: {is_zip}",
        ]
        if zip_error is not None:
            lines.append(f"  zip error: {zip_error}")
        return "\n".join(lines)

    def _read_first_bytes(self, path: Path, limit: int = 8) -> str:
        if not path.exists() or not path.is_file():
            return "n/a"
        try:
            return path.read_bytes()[:limit].hex(" ")
        except OSError as error:
            return f"read failed: {type(error).__name__}: {error}"

    def _check_zip(self, path: Path) -> tuple[bool, str | None]:
        if not path.exists() or not path.is_file():
            return False, "file does not exist"
        if not zipfile.is_zipfile(path):
            return False, "zipfile.is_zipfile returned False"
        try:
            with zipfile.ZipFile(path) as archive:
                archive.testzip()
        except Exception as error:
            return False, f"{type(error).__name__}: {error}"
        return True, None

    def _report_catalog_summary(
        self,
        report: DiagnosticsReport,
        catalog: TemplateCatalog,
        drive_tree: DriveTree,
    ) -> None:
        report.detail(
            "Catalog summary: "
            f"{len(catalog.list_projects())} projects, "
            f"{len(catalog.list_templates())} templates; "
            f"Drive tree root: {drive_tree.root_name}"
        )
        report.detail(self._format_catalog_navigation(catalog))

    def _format_catalog_navigation(self, catalog: TemplateCatalog) -> str:
        lines = ["Telegram navigation tree:"]
        for project in catalog.list_projects():
            lines.append(project.name)
            if not hasattr(catalog, "list_navigation_children"):
                for vacancy in catalog.list_vacancies(project.id):
                    lines.append(f"    {vacancy.name}")
                continue
            children = catalog.list_navigation_children(project.id)
            if not children:
                lines.append("    (no folders found)")
                continue
            for child in children:
                self._append_catalog_folder(lines, catalog, project.id, child.id, 1)
        return "\n".join(lines)

    def _append_catalog_folder(
        self,
        lines: list[str],
        catalog: TemplateCatalog,
        project_id: str,
        folder_id: str,
        depth: int,
    ) -> None:
        folder = catalog.get_navigation_folder(project_id, folder_id)
        indent = "    " * depth
        lines.append(f"{indent}{folder.name}")
        for template in catalog.list_templates_for_folder(project_id, folder_id):
            lines.append(f"{indent}    {template.name}")
        for child in catalog.list_navigation_children(project_id, folder_id):
            self._append_catalog_folder(lines, catalog, project_id, child.id, depth + 1)

    def _format_drive_tree(self, tree: DriveTree) -> str:
        lines = [f"Google Drive tree: {tree.root_name}"]
        if not tree.projects:
            lines.append("  (no projects found)")
            return "\n".join(lines)

        for project in tree.projects:
            lines.append(project.name)
            if not project.vacancies:
                lines.append("    (no vacancies found)")
                continue
            for vacancy in project.vacancies:
                lines.append(f"    {vacancy.name}")
                if not vacancy.templates:
                    lines.append("        (no DOCX/DOCM templates found)")
                    continue
                for template in vacancy.templates:
                    lines.append(f"        {template.name}")
        return "\n".join(lines)

    def _resolve_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        return (self.root_dir / path).resolve()

    def _maybe_detail_traceback(self, report: DiagnosticsReport) -> None:
        if self.show_tracebacks:
            report.detail(traceback.format_exc().strip())


def print_report(report: DiagnosticsReport) -> None:
    """Print the diagnostics details and final status table."""
    for detail in report.details:
        sys.stdout.write(f"{detail}\n")

    if report.details:
        sys.stdout.write("\n")

    sys.stdout.write("Backend diagnostics\n")
    sys.stdout.write("-------------------\n")
    width = max((len(status.name) for status in report.statuses), default=0)
    for status in report.statuses:
        sys.stdout.write(
            f"{status.marker} {status.name.ljust(width)}  {status.message}\n"
        )

    if report.has_errors():
        sys.stdout.write("\nBackend is not ready. Fix failed checks and run diagnostics again.\n")
    else:
        sys.stdout.write("\nReady for Telegram ✅\n")


def main() -> int:
    """Run diagnostics as a command-line entry point."""
    show_tracebacks = "--traceback" in sys.argv[1:]
    report = DiagnosticsRunner(show_tracebacks=show_tracebacks).run()
    print_report(report)
    return 1 if report.has_errors() else 0


if __name__ == "__main__":
    raise SystemExit(main())
