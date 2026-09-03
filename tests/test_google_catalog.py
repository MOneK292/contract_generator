"""Tests for Google Drive catalog discovery."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

from src.services.google.catalog import (
    GoogleDriveCatalogService,
    normalize_template_folder_name,
    normalize_template_folder_path,
)
from src.services.google.drive import GoogleFileMetadata


class GoogleDriveCatalogServiceTest(unittest.TestCase):
    """Google Drive catalog service behavior."""

    def test_refresh_catalog_builds_tree_and_saves_cache(self) -> None:
        with TemporaryDirectory() as temp_dir:
            service, drive = self._service(Path(temp_dir))
            drive.list_folders.side_effect = [
                [self._folder("project-folder", "Яндекс Лавка")],
            ]
            drive.list_children.side_effect = [
                [self._folder("vacancy-folder", "Сборщик")],
                [
                    self._docx("template-1", "Договор.docx"),
                    self._docx("template-2", "Доп соглашение.docx"),
                ],
            ]

            catalog = service.refresh_catalog()

            self.assertTrue(service.catalog_path.exists())
            self.assertEqual(catalog.get_project("project-folder").name, "Яндекс Лавка")
            self.assertEqual(catalog.get_vacancy("vacancy-folder").name, "Сборщик")
            self.assertEqual(catalog.get_template("template-1").name, "Договор.docx")
            self.assertEqual(
                [template.id for template in catalog.list_templates_for_vacancy(
                    "project-folder",
                    "vacancy-folder",
                )],
                ["template-1", "template-2"],
            )

    def test_refresh_catalog_recursively_finds_templates_at_any_depth(self) -> None:
        with TemporaryDirectory() as temp_dir:
            service, drive = self._service(Path(temp_dir))
            drive.list_folders.return_value = [
                self._folder("project-folder", "Проект"),
            ]
            drive.list_children.side_effect = [
                [self._folder("category", "Категория")],
                [self._folder("subcategory", "Подкатегория")],
                [self._docm("template-docm", "Договор.docm")],
            ]

            catalog = service.refresh_catalog()

            vacancies = catalog.list_vacancies("project-folder")
            self.assertEqual(len(vacancies), 1)
            self.assertEqual(vacancies[0].id, "subcategory")
            self.assertEqual(vacancies[0].name, "Подкатегория")
            root_children = catalog.list_navigation_children("project-folder")
            self.assertEqual(root_children[0].name, "Категория")
            sub_children = catalog.list_navigation_children("project-folder", "category")
            self.assertEqual(sub_children[0].name, "Подкатегория")
            self.assertEqual(
                catalog.list_templates_for_folder("project-folder", "subcategory")[0].id,
                "template-docm",
            )
            self.assertEqual(
                catalog.list_templates_for_vacancy("project-folder", "subcategory")[0].id,
                "template-docm",
            )

    def test_load_catalog_uses_cache_without_drive_calls(self) -> None:
        with TemporaryDirectory() as temp_dir:
            service, drive = self._service(Path(temp_dir))
            service.catalog_path.parent.mkdir(parents=True, exist_ok=True)
            service.catalog_path.write_text(
                """
{
  "projects": [
    {
      "id": "project-folder",
      "name": "Project",
      "vacancies": [
        {
          "id": "vacancy-folder",
          "name": "Vacancy",
          "template_id": "template-1",
          "template_ids": ["template-1"]
        }
      ]
    }
  ],
  "templates": [
    {
      "id": "template-1",
      "name": "Contract.docx",
      "google_drive_file_id": "template-1"
    }
  ]
}
""",
                encoding="utf-8",
            )

            catalog = service.load_catalog()

            self.assertEqual(catalog.get_template("template-1").google_drive_file_id, "template-1")
            drive.list_folders.assert_not_called()

    def test_normalizes_nested_drive_menu_names(self) -> None:
        self.assertEqual(
            normalize_template_folder_path(["Система Логистики", "Сборщик система логистики"]),
            "Система Логистики / Сборщик",
        )
        self.assertEqual(
            normalize_template_folder_path(["Экспресс плюс", "Авто экспресс плюс"]),
            "Экспресс плюс / Авто",
        )
        self.assertEqual(
            normalize_template_folder_path(["Система Логистики", "ЭВ система логистики"]),
            "Система Логистики / Электровело",
        )

    def test_normalizes_single_drive_menu_level(self) -> None:
        self.assertEqual(
            normalize_template_folder_name("Авто экспресс плюс", "Экспресс плюс"),
            "Авто",
        )
        self.assertEqual(
            normalize_template_folder_name("ЭВ система логистики", "Система логистики"),
            "Электровело",
        )

    def _service(self, root: Path) -> tuple[GoogleDriveCatalogService, Mock]:
        drive = Mock()
        config = SimpleNamespace(
            paths=SimpleNamespace(cache_dir=root / "cache"),
            google=SimpleNamespace(drive_root_folder_id="root-folder"),
        )
        return GoogleDriveCatalogService(config, drive), drive

    def _folder(self, file_id: str, name: str) -> GoogleFileMetadata:
        return GoogleFileMetadata(
            file_id=file_id,
            name=name,
            mime_type="application/vnd.google-apps.folder",
            modified_time=None,
            md5=None,
            size=None,
            is_folder=True,
        )

    def _docx(self, file_id: str, name: str) -> GoogleFileMetadata:
        return GoogleFileMetadata(
            file_id=file_id,
            name=name,
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            modified_time=None,
            md5=None,
            size=10,
            is_folder=False,
        )

    def _docm(self, file_id: str, name: str) -> GoogleFileMetadata:
        return GoogleFileMetadata(
            file_id=file_id,
            name=name,
            mime_type="application/vnd.ms-word.document.macroEnabled.12",
            modified_time=None,
            md5=None,
            size=10,
            is_folder=False,
        )


if __name__ == "__main__":
    unittest.main()
