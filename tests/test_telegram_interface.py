"""Tests for Telegram UI infrastructure."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from aiohttp import ThreadedResolver
from aiogram import Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from src.interfaces.telegram import create_bot, create_dispatcher
from src.interfaces.telegram.bot import TelegramStartupError, create_telegram_application
from src.interfaces.telegram.hr_template import build_hr_form, build_hr_template_text
from src.interfaces.telegram.bot import setup_telegram_menu
from src.interfaces.telegram.keyboards import (
    PROJECT_CALLBACK_PREFIX,
    TEMPLATE_CALLBACK_PREFIX,
    VACANCY_CALLBACK_PREFIX,
    VACANCY_BACK_CALLBACK_PREFIX,
    build_projects_keyboard,
    build_templates_keyboard,
    build_vacancies_keyboard,
)
from src.interfaces.telegram.states import UserSessionStore
from src.services.config import TemplateCatalog


class TelegramInterfaceTest(unittest.IsolatedAsyncioTestCase):
    """Telegram infrastructure behavior."""

    def test_registers_handlers(self) -> None:
        catalog = self._catalog()

        dispatcher = create_dispatcher(catalog)

        self.assertIsInstance(dispatcher, Dispatcher)
        router_names = {router.name for router in dispatcher.sub_routers}
        self.assertTrue(
            "start" in router_names and "project" in router_names and "vacancy" in router_names and "template" in router_names and "employee" in router_names and "offers" in router_names
        )

    def test_builds_projects_keyboard(self) -> None:
        keyboard = build_projects_keyboard(self._catalog())

        self.assertEqual(len(keyboard.inline_keyboard), 3)
        self.assertEqual(keyboard.inline_keyboard[0][0].text, "Project A")
        self.assertEqual(
            keyboard.inline_keyboard[0][0].callback_data,
            f"{PROJECT_CALLBACK_PREFIX}project-a",
        )

    def test_builds_vacancies_keyboard(self) -> None:
        keyboard = build_vacancies_keyboard(self._catalog(), "project-a")

        self.assertEqual(len(keyboard.inline_keyboard), 3)
        self.assertEqual(keyboard.inline_keyboard[1][0].text, "Vacancy 2")
        self.assertEqual(
            keyboard.inline_keyboard[1][0].callback_data,
            f"{VACANCY_CALLBACK_PREFIX}vacancy-2",
        )

    def test_builds_each_drive_tree_level_as_separate_keyboard(self) -> None:
        keyboard = build_vacancies_keyboard(self._navigation_catalog(), "project-a")

        self.assertEqual(len(keyboard.inline_keyboard), 2)
        self.assertEqual(keyboard.inline_keyboard[0][0].text, "Экспресс плюс")
        self.assertEqual(
            keyboard.inline_keyboard[0][0].callback_data,
            f"{VACANCY_CALLBACK_PREFIX}folder-express",
        )

        child_keyboard = build_vacancies_keyboard(
            self._navigation_catalog(),
            "project-a",
            "folder-express",
        )

        self.assertEqual(child_keyboard.inline_keyboard[0][0].text, "Авто")
        self.assertEqual(child_keyboard.inline_keyboard[1][0].text, "Вело")
        self.assertEqual(child_keyboard.inline_keyboard[-1][0].text, "⬅️ Назад")
        self.assertEqual(
            child_keyboard.inline_keyboard[-1][0].callback_data,
            f"{VACANCY_BACK_CALLBACK_PREFIX}project-a:root",
        )

    def test_builds_templates_keyboard(self) -> None:
        keyboard = build_templates_keyboard(
            self._catalog(),
            "project-a",
            "vacancy-1",
        )

        self.assertEqual(len(keyboard.inline_keyboard), 3)
        self.assertEqual(keyboard.inline_keyboard[0][0].text, "Contract.docx")
        self.assertEqual(
            keyboard.inline_keyboard[1][0].callback_data,
            f"{TEMPLATE_CALLBACK_PREFIX}template-2",
        )

    def test_create_bot_requires_token(self) -> None:
        config = SimpleNamespace(env={})

        with self.assertRaises(TelegramStartupError):
            create_bot(config)

    async def test_create_bot_uses_aiohttp_session_with_threaded_resolver(self) -> None:
        config = SimpleNamespace(env={"BOT_TOKEN": "123456:ABCDEF"})

        bot = create_bot(config)

        self.assertIsInstance(bot.session, AiohttpSession)
        self.assertIsInstance(bot.session._connector_init["resolver"], ThreadedResolver)

    async def test_setup_telegram_menu_registers_start_command(self) -> None:
        bot = _FakeBot()

        await setup_telegram_menu(bot)

        self.assertEqual(bot.commands[0].command, "start")

    def test_hr_template_uses_moscow_date_fields(self) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        form = build_hr_form(
            now=datetime(2026, 7, 14, 10, 30, tzinfo=ZoneInfo("Europe/Moscow"))
        )

        self.assertIn("День: 14", form)
        self.assertIn("Месяц: июля", form)
        self.assertIn("Год: 2026", form)
        self.assertIn("МесяцЧ: 07", form)

    def test_hr_template_is_copyable_pre_block(self) -> None:
        message = build_hr_template_text("Contract.docm")

        self.assertIn("<pre>", message)
        self.assertIn("Ф:", message)
        self.assertIn("Номер П:", message)

    def test_create_telegram_application_requires_projects(self) -> None:
        config = SimpleNamespace(env={"BOT_TOKEN": "123456:ABCDEF"})
        empty_catalog = TemplateCatalog.from_mapping({"projects": [], "templates": []})

        with self.assertRaises(TelegramStartupError):
            create_telegram_application(config, empty_catalog)

    def test_user_session_store_resets_selection(self) -> None:
        store = UserSessionStore()
        session = store.get(10)
        session.project = "project-a"
        session.vacancy = "vacancy-1"
        session.template = "template-1"

        reset_session = store.reset(10)

        self.assertIsNone(reset_session.project)
        self.assertIsNone(reset_session.vacancy)
        self.assertIsNone(reset_session.template)

    def _catalog(self) -> TemplateCatalog:
        return TemplateCatalog.from_mapping(
            {
                "projects": [
                    {
                        "id": "project-a",
                        "name": "Project A",
                        "vacancies": [
                            {
                                "id": "vacancy-1",
                                "name": "Vacancy 1",
                                "template_id": "template-1",
                                "template_ids": ["template-1", "template-2"],
                            },
                            {
                                "id": "vacancy-2",
                                "name": "Vacancy 2",
                                "template_id": "template-3",
                                "template_ids": ["template-3"],
                            },
                        ],
                    },
                    {
                        "id": "project-b",
                        "name": "Project B",
                        "vacancies": [
                            {
                                "id": "vacancy-3",
                                "name": "Vacancy 3",
                                "template_id": "template-4",
                                "template_ids": ["template-4"],
                            }
                        ],
                    },
                ],
                "templates": [
                    {
                        "id": "template-1",
                        "name": "Contract.docx",
                        "google_drive_file_id": "drive-1",
                    },
                    {
                        "id": "template-2",
                        "name": "Addendum.docx",
                        "google_drive_file_id": "drive-2",
                    },
                    {
                        "id": "template-3",
                        "name": "Courier.docx",
                        "google_drive_file_id": "drive-3",
                    },
                    {
                        "id": "template-4",
                        "name": "Picker.docx",
                        "google_drive_file_id": "drive-4",
                    },
                ],
            }
        )

    def _navigation_catalog(self) -> TemplateCatalog:
        return TemplateCatalog.from_mapping(
            {
                "projects": [
                    {
                        "id": "project-a",
                        "name": "Самокат",
                        "vacancies": [
                            {
                                "id": "folder-auto",
                                "name": "Авто",
                                "template_id": "template-auto",
                                "template_ids": ["template-auto"],
                            },
                            {
                                "id": "folder-bike",
                                "name": "Вело",
                                "template_id": "template-bike",
                                "template_ids": ["template-bike"],
                            },
                        ],
                    }
                ],
                "templates": [
                    {
                        "id": "template-auto",
                        "name": "Auto.docm",
                        "google_drive_file_id": "template-auto",
                    },
                    {
                        "id": "template-bike",
                        "name": "Bike.docm",
                        "google_drive_file_id": "template-bike",
                    },
                ],
                "navigation": {
                    "project-a": {
                        "id": "project-a:root",
                        "name": "Самокат",
                        "template_ids": [],
                        "children": [
                            {
                                "id": "folder-express",
                                "name": "Экспресс плюс",
                                "template_ids": [],
                                "children": [
                                    {
                                        "id": "folder-auto",
                                        "name": "Авто",
                                        "template_ids": ["template-auto"],
                                        "children": [],
                                    },
                                    {
                                        "id": "folder-bike",
                                        "name": "Вело",
                                        "template_ids": ["template-bike"],
                                        "children": [],
                                    },
                                ],
                            }
                        ],
                    }
                },
            }
        )


class _FakeBot:
    def __init__(self) -> None:
        self.commands = []

    async def set_my_commands(self, commands) -> None:
        self.commands = commands


if __name__ == "__main__":
    unittest.main()
