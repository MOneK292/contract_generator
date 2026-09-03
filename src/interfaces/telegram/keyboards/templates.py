"""Template selection keyboards."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.services.config import TemplateCatalog


TEMPLATE_CALLBACK_PREFIX = "template:"
TEMPLATE_BACK_CALLBACK = "template_back:"


def build_templates_keyboard(
    catalog: TemplateCatalog,
    project_id: str,
    vacancy_id: str,
) -> InlineKeyboardMarkup:
    """Build an inline keyboard with templates for a vacancy."""
    buttons = [
        [
            InlineKeyboardButton(
                text=template.name,
                callback_data=f"{TEMPLATE_CALLBACK_PREFIX}{template.id}",
            )
        ]
        for template in catalog.list_templates_for_vacancy(project_id, vacancy_id)
    ]
    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=TEMPLATE_BACK_CALLBACK,
                style="primary",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def template_callback_data(template_id: str) -> str:
    """Return callback data for a template id."""
    return f"{TEMPLATE_CALLBACK_PREFIX}{template_id}"
