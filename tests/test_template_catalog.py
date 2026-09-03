"""Tests for template catalog loading."""

from __future__ import annotations

import unittest

from src.core.exceptions import ConfigurationError
from src.services.config.template_catalog import TemplateCatalog


class TemplateCatalogTest(unittest.TestCase):
    """Template catalog behavior."""

    def test_loads_projects_vacancies_and_nested_templates(self) -> None:
        catalog = TemplateCatalog.from_mapping(
            {
                "projects": [
                    {
                        "id": "project",
                        "name": "Project",
                        "vacancies": [
                            {
                                "id": "designer",
                                "name": "Designer",
                                "template": {
                                    "id": "designer-contract",
                                    "name": "Designer Contract",
                                    "google_drive_file_id": "file-id",
                                },
                            }
                        ],
                    }
                ]
            }
        )

        self.assertEqual(catalog.get_project("project").name, "Project")
        self.assertEqual(catalog.get_vacancy("designer").template_id, "designer-contract")
        self.assertEqual(
            catalog.get_template_for_vacancy("designer").google_drive_file_id,
            "file-id",
        )

    def test_rejects_unknown_template_references(self) -> None:
        with self.assertRaises(ConfigurationError):
            TemplateCatalog.from_mapping(
                {
                    "projects": [
                        {
                            "id": "project",
                            "name": "Project",
                            "vacancies": [
                                {
                                    "id": "designer",
                                    "name": "Designer",
                                    "template_id": "missing",
                                }
                            ],
                        }
                    ]
                }
            )


if __name__ == "__main__":
    unittest.main()
