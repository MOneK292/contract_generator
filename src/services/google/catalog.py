"""Google Drive template catalog discovery."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.services.config.settings_loader import AppConfig
from src.services.config.template_catalog import TemplateCatalog
from src.services.google.drive import GoogleDriveService, GoogleFileMetadata, is_word_template


@dataclass
class GoogleDriveCatalogService:
    """Builds TemplateCatalog from the Google Drive folder hierarchy."""

    config: AppConfig
    drive_service: GoogleDriveService
    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
        init=False,
        repr=False,
    )

    def load_catalog(self, *, force_refresh: bool = False) -> TemplateCatalog:
        """Load the cached catalog or refresh it from Google Drive."""
        if not force_refresh and self.catalog_path.exists():
            self._logger.info("Loading template catalog from cache: %s", self.catalog_path)
            return self._catalog_from_mapping(self._load_catalog_mapping())
        return self.refresh_catalog()

    def refresh_catalog(self) -> TemplateCatalog:
        """Refresh the catalog from Google Drive and cache it locally."""
        mapping = self._build_catalog_mapping()
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        with self.catalog_path.open("w", encoding="utf-8") as file:
            json.dump(mapping, file, ensure_ascii=False, indent=2)
        self._logger.info("Template catalog refreshed: %s", self.catalog_path)
        return self._catalog_from_mapping(mapping)

    @property
    def catalog_path(self) -> Path:
        """Return the local catalog cache path."""
        return self.config.paths.cache_dir / "catalog.json"

    def _build_catalog_mapping(self) -> dict[str, Any]:
        projects: list[dict[str, Any]] = []
        templates: list[dict[str, str]] = []
        navigation: dict[str, dict[str, Any]] = {}

        for project_folder in self.drive_service.list_folders(
            self.config.google.drive_root_folder_id
        ):
            project_id = project_folder.file_id
            project_data: dict[str, Any] = {
                "id": project_id,
                "name": project_folder.name or project_folder.file_id,
                "vacancies": [],
            }
            root_node: dict[str, Any] = {
                "id": f"{project_id}:root",
                "name": project_folder.name or project_folder.file_id,
                "children": [],
                "template_ids": [],
            }
            self._collect_project_templates(
                project_folder,
                project_data,
                root_node,
                templates,
                path_parts=[],
                parent_name=None,
            )

            projects.append(project_data)
            navigation[project_id] = root_node

        return {"projects": projects, "templates": templates, "navigation": navigation}

    def _collect_project_templates(
        self,
        folder: GoogleFileMetadata,
        project_data: dict[str, Any],
        node: dict[str, Any],
        templates: list[dict[str, str]],
        path_parts: list[str],
        parent_name: str | None,
    ) -> None:
        children = self.drive_service.list_children(folder.file_id)
        folder_templates = [child for child in children if is_word_template(child)]
        child_folders = [child for child in children if child.is_folder]

        if folder_templates:
            template_ids = [template.file_id for template in folder_templates]
            node["template_ids"] = template_ids
            project_data["vacancies"].append(
                {
                    "id": self._vacancy_id(folder, path_parts),
                    "name": normalize_template_folder_name(
                        path_parts[-1] if path_parts else "Шаблоны проекта",
                        parent_name,
                    ),
                    "template_id": template_ids[0],
                    "template_ids": template_ids,
                }
            )
            for template in folder_templates:
                templates.append(
                    {
                        "id": template.file_id,
                        "name": template.name or template.file_id,
                        "google_drive_file_id": template.file_id,
                    }
                )

        for child_folder in child_folders:
            child_name = child_folder.name or child_folder.file_id
            child_node = {
                "id": child_folder.file_id,
                "name": normalize_template_folder_name(child_name, path_parts[-1] if path_parts else None),
                "children": [],
                "template_ids": [],
            }
            node["children"].append(child_node)
            self._collect_project_templates(
                child_folder,
                project_data,
                child_node,
                templates,
                [*path_parts, child_name],
                parent_name=path_parts[-1] if path_parts else None,
            )

    def _vacancy_id(self, folder: GoogleFileMetadata, path_parts: list[str]) -> str:
        if path_parts:
            return folder.file_id
        return f"{folder.file_id}:root"

    def _load_catalog_mapping(self) -> dict[str, Any]:
        with self.catalog_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid catalog cache format: {self.catalog_path}")
        return data

    def _catalog_from_mapping(self, mapping: dict[str, Any]) -> TemplateCatalog:
        catalog = TemplateCatalog.from_mapping(mapping)
        catalog.set_refresh_callback(self.refresh_catalog)
        return catalog


def normalize_template_folder_path(path_parts: list[str]) -> str:
    """Return a user-facing menu name for a nested Google Drive template path."""
    if not path_parts:
        return "Шаблоны проекта"

    normalized: list[str] = []
    for index, part in enumerate(path_parts):
        display_name = part.strip()
        if index > 0:
            display_name = _remove_parent_name(display_name, path_parts[index - 1])
        display_name = _expand_common_abbreviation(display_name)
        normalized.append(display_name)

    return " / ".join(item for item in normalized if item)


def normalize_template_folder_name(value: str, parent: str | None = None) -> str:
    """Return a user-facing name for one Google Drive folder level."""
    display_name = value.strip()
    if parent:
        display_name = _remove_parent_name(display_name, parent)
    return _expand_common_abbreviation(display_name)


def _remove_parent_name(value: str, parent: str) -> str:
    parent_words = _normalized_words(parent)
    kept_words = [
        word
        for word in value.split()
        if _normalize_word(word) not in parent_words
    ]
    return " ".join(kept_words).strip() or value.strip()


def _normalized_words(value: str) -> set[str]:
    return {_normalize_word(word) for word in value.split() if _normalize_word(word)}


def _normalize_word(value: str) -> str:
    return "".join(char for char in value.casefold().replace("ё", "е") if char.isalnum())


def _expand_common_abbreviation(value: str) -> str:
    if _normalize_word(value) in {"эв", "электровело"}:
        return "Электровело"
    return value
