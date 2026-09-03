"""Vacancy selection keyboards."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.services.config import TemplateCatalog


VACANCY_CALLBACK_PREFIX = "vacancy:"
VACANCY_BACK_CALLBACK_PREFIX = "vacancy_back:"


def build_vacancies_keyboard(
    catalog: TemplateCatalog,
    project_id: str,
    parent_id: str | None = None,
) -> InlineKeyboardMarkup:
    """Build an inline keyboard with the next Google Drive folder level."""
    if hasattr(catalog, "list_navigation_children"):
        folders = catalog.list_navigation_children(project_id, parent_id)
        buttons = [
            [
                InlineKeyboardButton(
                    text=folder.name,
                    callback_data=f"{VACANCY_CALLBACK_PREFIX}{folder.id}",
                )
            ]
            for folder in folders
        ]
        if parent_id is not None:
            folder = catalog.get_navigation_folder(project_id, parent_id)
            back_target = folder.parent_id or ""
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data=f"{VACANCY_BACK_CALLBACK_PREFIX}{back_target}",
                        style="primary",
                    )
                ]
            )
        else:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад",
                        callback_data=f"{VACANCY_BACK_CALLBACK_PREFIX}__projects__",
                        style="primary",
                    )
                ]
            )
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    buttons = [
        [
            InlineKeyboardButton(
                text=vacancy.name,
                callback_data=f"{VACANCY_CALLBACK_PREFIX}{vacancy.id}",
            )
        ]
        for vacancy in catalog.list_vacancies(project_id)
    ]
    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"{VACANCY_BACK_CALLBACK_PREFIX}__projects__",
                style="primary",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def vacancy_callback_data(vacancy_id: str) -> str:
    """Return callback data for a vacancy id."""
    return f"{VACANCY_CALLBACK_PREFIX}{vacancy_id}"
