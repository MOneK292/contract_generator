"""Project selection keyboards."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.services.config import TemplateCatalog


PROJECT_CALLBACK_PREFIX = "project:"
PROJECT_BACK_CALLBACK = "project_back:"


def build_projects_keyboard(catalog: TemplateCatalog) -> InlineKeyboardMarkup:
    """Build an inline keyboard with all available projects."""
    buttons = [
        [
            InlineKeyboardButton(
                text=project.name,
                callback_data=f"{PROJECT_CALLBACK_PREFIX}{project.id}",
            )
        ]
        for project in catalog.list_projects()
    ]
    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=PROJECT_BACK_CALLBACK,
                style="primary",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def project_callback_data(project_id: str) -> str:
    """Return callback data for a project id."""
    return f"{PROJECT_CALLBACK_PREFIX}{project_id}"

