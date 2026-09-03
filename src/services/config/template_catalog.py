"""Template catalog loaded from config/templates.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.core.exceptions import ConfigurationError, TemplateNotFoundError
from src.models.project import Project
from src.models.template import Template
from src.models.vacancy import Vacancy


@dataclass(frozen=True)
class ProjectVacancies:
    """Vacancies grouped by project."""

    project: Project
    vacancies: tuple[Vacancy, ...]


@dataclass(frozen=True)
class CatalogFolder:
    """Folder node used for Google Drive navigation."""

    id: str
    name: str
    parent_id: str | None
    children: tuple["CatalogFolder", ...]
    template_ids: tuple[str, ...]


class TemplateCatalog:
    """Provides projects, vacancies, and template metadata."""

    def __init__(
        self,
        projects: list[Project],
        vacancies_by_project: dict[str, list[Vacancy]],
        templates: list[Template],
        templates_by_vacancy: dict[tuple[str, str], list[Template]] | None = None,
        navigation_by_project: dict[str, CatalogFolder] | None = None,
    ) -> None:
        self._projects = tuple(projects)
        self._project_by_id = {project.id: project for project in projects}
        self._vacancies_by_project = {
            project_id: tuple(vacancies)
            for project_id, vacancies in vacancies_by_project.items()
        }
        self._vacancy_by_id = {
            vacancy.id: vacancy
            for vacancies in self._vacancies_by_project.values()
            for vacancy in vacancies
        }
        self._templates = tuple(templates)
        self._template_by_id = {template.id: template for template in templates}
        self._templates_by_vacancy = {
            key: tuple(value)
            for key, value in (templates_by_vacancy or {}).items()
        }
        self._navigation_by_project = navigation_by_project or {}
        self._navigation_by_id: dict[tuple[str, str], CatalogFolder] = {}
        for project_id, root in self._navigation_by_project.items():
            self._index_navigation(project_id, root)
        self._refresh_callback = None

    @classmethod
    def from_file(cls, path: str | Path) -> "TemplateCatalog":
        """Load template catalog from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise ConfigurationError(f"Templates file does not exist: {path}")

        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}

        if not isinstance(data, dict):
            raise ConfigurationError(f"Templates file must contain a mapping: {path}")

        return cls.from_mapping(data)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "TemplateCatalog":
        """Build a catalog from parsed `templates.yaml` data."""
        projects_raw = data.get("projects", [])
        templates_raw = data.get("templates", [])

        if not isinstance(projects_raw, list):
            raise ConfigurationError("templates.yaml field `projects` must be a list")
        if not isinstance(templates_raw, list):
            raise ConfigurationError("templates.yaml field `templates` must be a list")

        projects: list[Project] = []
        vacancies_by_project: dict[str, list[Vacancy]] = {}
        templates_by_vacancy: dict[tuple[str, str], list[Template]] = {}
        templates: list[Template] = []

        for template_raw in templates_raw:
            templates.append(cls._parse_template(template_raw))

        for project_raw in projects_raw:
            project, vacancies, nested_templates = cls._parse_project(project_raw)
            projects.append(project)
            vacancies_by_project[project.id] = vacancies
            templates.extend(nested_templates)
            for vacancy_raw, vacancy in zip(project_raw.get("vacancies", []), vacancies):
                template_ids = vacancy_raw.get("template_ids", [vacancy.template_id])
                if not isinstance(template_ids, list):
                    raise ConfigurationError(
                        f"Vacancy `{vacancy.id}` field `template_ids` must be a list"
                    )
                templates_by_vacancy[(project.id, vacancy.id)] = [
                    template
                    for template in templates
                    if template.id in set(template_ids)
                ]

        cls._validate_unique("project", [project.id for project in projects])
        cls._validate_unique("vacancy", [
            vacancy.id
            for vacancies in vacancies_by_project.values()
            for vacancy in vacancies
        ])
        cls._validate_unique("template", [template.id for template in templates])
        cls._validate_template_references(vacancies_by_project, templates)
        cls._validate_templates_by_vacancy(templates_by_vacancy, templates)

        navigation_by_project = cls._parse_navigation(data.get("navigation", {}))

        return cls(
            projects,
            vacancies_by_project,
            templates,
            templates_by_vacancy,
            navigation_by_project,
        )

    def list_projects(self) -> tuple[Project, ...]:
        """Return all configured projects."""
        return self._projects

    def list_project_vacancies(self) -> tuple[ProjectVacancies, ...]:
        """Return projects with their configured vacancies."""
        return tuple(
            ProjectVacancies(project, self._vacancies_by_project.get(project.id, ()))
            for project in self._projects
        )

    def list_vacancies(self, project_id: str) -> tuple[Vacancy, ...]:
        """Return vacancies for a project."""
        self.get_project(project_id)
        return self._vacancies_by_project.get(project_id, ())

    def list_templates(self) -> tuple[Template, ...]:
        """Return all configured templates."""
        return self._templates

    def list_templates_for_vacancy(
        self,
        project_id: str,
        vacancy_id: str,
    ) -> tuple[Template, ...]:
        """Return templates configured for a project vacancy."""
        self.get_project(project_id)
        self.get_vacancy(vacancy_id)
        return self._templates_by_vacancy.get((project_id, vacancy_id), ())

    def list_navigation_children(
        self,
        project_id: str,
        folder_id: str | None = None,
    ) -> tuple[CatalogFolder, ...]:
        """Return child folders for a project navigation node."""
        folder = self.get_navigation_folder(project_id, folder_id)
        return folder.children

    def list_templates_for_folder(
        self,
        project_id: str,
        folder_id: str | None,
    ) -> tuple[Template, ...]:
        """Return templates attached to a project navigation node."""
        folder = self.get_navigation_folder(project_id, folder_id)
        return tuple(
            self.get_template(template_id)
            for template_id in folder.template_ids
            if template_id in self._template_by_id
        )

    def get_navigation_folder(
        self,
        project_id: str,
        folder_id: str | None = None,
    ) -> CatalogFolder:
        """Return a navigation folder by project id and folder id."""
        self.get_project(project_id)
        if folder_id is None:
            root = self._navigation_by_project.get(project_id)
            if root is not None:
                return root
            return CatalogFolder(
                id=f"{project_id}:root",
                name="",
                parent_id=None,
                children=tuple(
                    CatalogFolder(
                        id=vacancy.id,
                        name=vacancy.name,
                        parent_id=None,
                        children=(),
                        template_ids=(vacancy.template_id,),
                    )
                    for vacancy in self.list_vacancies(project_id)
                ),
                template_ids=(),
            )
        try:
            return self._navigation_by_id[(project_id, folder_id)]
        except KeyError as error:
            if project_id not in self._navigation_by_project:
                for vacancy in self.list_vacancies(project_id):
                    if vacancy.id == folder_id:
                        return CatalogFolder(
                            id=vacancy.id,
                            name=vacancy.name,
                            parent_id=None,
                            children=(),
                            template_ids=(vacancy.template_id,),
                        )
            raise TemplateNotFoundError(
                f"Folder is not configured for project `{project_id}`: {folder_id}"
            ) from error

    def get_project(self, project_id: str) -> Project:
        """Return a project by id."""
        try:
            return self._project_by_id[project_id]
        except KeyError as error:
            raise TemplateNotFoundError(f"Project is not configured: {project_id}") from error

    def get_vacancy(self, vacancy_id: str) -> Vacancy:
        """Return a vacancy by id."""
        try:
            return self._vacancy_by_id[vacancy_id]
        except KeyError as error:
            raise TemplateNotFoundError(f"Vacancy is not configured: {vacancy_id}") from error

    def get_template(self, template_id: str) -> Template:
        """Return a template by id."""
        try:
            return self._template_by_id[template_id]
        except KeyError as error:
            raise TemplateNotFoundError(f"Template is not configured: {template_id}") from error

    def get_template_for_vacancy(self, vacancy_id: str) -> Template:
        """Return a template linked to a vacancy."""
        vacancy = self.get_vacancy(vacancy_id)
        return self.get_template(vacancy.template_id)

    def _index_navigation(self, project_id: str, folder: CatalogFolder) -> None:
        self._navigation_by_id[(project_id, folder.id)] = folder
        for child in folder.children:
            self._index_navigation(project_id, child)

    def set_refresh_callback(self, callback: Any) -> None:
        """Set a callback used to refresh a Google Drive-backed catalog."""
        self._refresh_callback = callback

    def refresh(self) -> "TemplateCatalog" | None:
        """Refresh this catalog when a refresh callback is available."""
        if self._refresh_callback is None:
            return None
        refreshed = self._refresh_callback()
        if isinstance(refreshed, TemplateCatalog):
            return refreshed
        return None

    @staticmethod
    def _parse_project(data: Any) -> tuple[Project, list[Vacancy], list[Template]]:
        if not isinstance(data, dict):
            raise ConfigurationError("Each project in templates.yaml must be a mapping")

        project = Project(
            id=TemplateCatalog._required_str(data, "id"),
            name=TemplateCatalog._required_str(data, "name"),
        )
        vacancies_raw = data.get("vacancies", [])
        if not isinstance(vacancies_raw, list):
            raise ConfigurationError(
                f"Project `{project.id}` field `vacancies` must be a list"
            )

        vacancies: list[Vacancy] = []
        templates: list[Template] = []
        for vacancy_raw in vacancies_raw:
            vacancy, nested_template = TemplateCatalog._parse_vacancy(vacancy_raw)
            vacancies.append(vacancy)
            if nested_template is not None:
                templates.append(nested_template)

        return project, vacancies, templates

    @staticmethod
    def _parse_vacancy(data: Any) -> tuple[Vacancy, Template | None]:
        if not isinstance(data, dict):
            raise ConfigurationError("Each vacancy in templates.yaml must be a mapping")

        template_raw = data.get("template")
        nested_template = None
        if template_raw is not None:
            nested_template = TemplateCatalog._parse_template(template_raw)
            template_id = nested_template.id
        else:
            template_id = TemplateCatalog._required_str(data, "template_id")

        return (
            Vacancy(
                id=TemplateCatalog._required_str(data, "id"),
                name=TemplateCatalog._required_str(data, "name"),
                template_id=template_id,
            ),
            nested_template,
        )

    @staticmethod
    def _parse_template(data: Any) -> Template:
        if not isinstance(data, dict):
            raise ConfigurationError("Each template in templates.yaml must be a mapping")

        return Template(
            id=TemplateCatalog._required_str(data, "id"),
            name=TemplateCatalog._required_str(data, "name"),
            google_drive_file_id=TemplateCatalog._required_str(
                data, "google_drive_file_id"
            ),
        )

    @staticmethod
    def _parse_navigation(data: Any) -> dict[str, CatalogFolder]:
        if not isinstance(data, dict):
            return {}
        result: dict[str, CatalogFolder] = {}
        for project_id, folder_raw in data.items():
            if isinstance(folder_raw, dict):
                result[str(project_id)] = TemplateCatalog._parse_navigation_folder(
                    folder_raw,
                    parent_id=None,
                )
        return result

    @staticmethod
    def _parse_navigation_folder(data: dict[str, Any], parent_id: str | None) -> CatalogFolder:
        folder_id = TemplateCatalog._required_str(data, "id")
        children_raw = data.get("children", [])
        template_ids_raw = data.get("template_ids", [])
        children = tuple(
            TemplateCatalog._parse_navigation_folder(child, folder_id)
            for child in children_raw
            if isinstance(child, dict)
        )
        template_ids = tuple(str(template_id) for template_id in template_ids_raw)
        return CatalogFolder(
            id=folder_id,
            name=str(data.get("name", "")),
            parent_id=parent_id,
            children=children,
            template_ids=template_ids,
        )

    @staticmethod
    def _validate_unique(label: str, ids: list[str]) -> None:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for item_id in ids:
            if item_id in seen:
                duplicates.add(item_id)
            seen.add(item_id)
        if duplicates:
            duplicate_list = ", ".join(sorted(duplicates))
            raise ConfigurationError(f"Duplicate {label} ids in templates.yaml: {duplicate_list}")

    @staticmethod
    def _validate_template_references(
        vacancies_by_project: dict[str, list[Vacancy]],
        templates: list[Template],
    ) -> None:
        template_ids = {template.id for template in templates}
        missing = sorted(
            {
                vacancy.template_id
                for vacancies in vacancies_by_project.values()
                for vacancy in vacancies
                if vacancy.template_id not in template_ids
            }
        )
        if missing:
            raise ConfigurationError(
                "Vacancies reference unknown template ids: " + ", ".join(missing)
            )

    @staticmethod
    def _validate_templates_by_vacancy(
        templates_by_vacancy: dict[tuple[str, str], list[Template]],
        templates: list[Template],
    ) -> None:
        template_ids = {template.id for template in templates}
        missing = sorted(
            template.id
            for vacancy_templates in templates_by_vacancy.values()
            for template in vacancy_templates
            if template.id not in template_ids
        )
        if missing:
            raise ConfigurationError(
                "Vacancies reference unknown template ids: " + ", ".join(missing)
            )

    @staticmethod
    def _required_str(data: dict[str, Any], key: str) -> str:
        value = data.get(key)
        if value is None or str(value).strip() == "":
            raise ConfigurationError(f"Missing required templates.yaml value: {key}")
        return str(value)
