"""Telegram inline keyboards."""

from src.interfaces.telegram.keyboards.actions import (
    CHANGE_TEMPLATE_TEXT,
    NEXT_EMPLOYEE_TEXT,
    START_OVER_TEXT,
    build_generation_actions_keyboard,
)
from src.interfaces.telegram.keyboards.projects import (
    PROJECT_CALLBACK_PREFIX,
    PROJECT_BACK_CALLBACK,
    build_projects_keyboard,
    project_callback_data,
)
from src.interfaces.telegram.keyboards.templates import (
    TEMPLATE_CALLBACK_PREFIX,
    TEMPLATE_BACK_CALLBACK,
    build_templates_keyboard,
    template_callback_data,
)
from src.interfaces.telegram.keyboards.vacancies import (
    VACANCY_BACK_CALLBACK_PREFIX,
    VACANCY_CALLBACK_PREFIX,
    build_vacancies_keyboard,
    vacancy_callback_data,
)

__all__ = [
    "PROJECT_CALLBACK_PREFIX",
    "PROJECT_BACK_CALLBACK",
    "CHANGE_TEMPLATE_TEXT",
    "NEXT_EMPLOYEE_TEXT",
    "START_OVER_TEXT",
    "TEMPLATE_CALLBACK_PREFIX",
    "TEMPLATE_BACK_CALLBACK",
    "VACANCY_BACK_CALLBACK_PREFIX",
    "VACANCY_CALLBACK_PREFIX",
    "build_generation_actions_keyboard",
    "build_projects_keyboard",
    "build_templates_keyboard",
    "build_vacancies_keyboard",
    "project_callback_data",
    "template_callback_data",
    "vacancy_callback_data",
]
