"""Telegram template selection handler."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from src.interfaces.telegram.keyboards import (
    TEMPLATE_CALLBACK_PREFIX,
    TEMPLATE_BACK_CALLBACK,
    build_generation_actions_keyboard,
    build_vacancies_keyboard,
)
from src.interfaces.telegram.hr_template import build_hr_template_text
from src.interfaces.telegram.states import ContractFlow, UserSessionStore
from src.services.config import TemplateCatalog


router = Router(name="template")
_logger = logging.getLogger(__name__)


def _has_navigation(template_catalog: TemplateCatalog) -> bool:
    return all(
        hasattr(template_catalog, name)
        for name in (
            "get_navigation_folder",
            "list_navigation_children",
            "list_templates_for_folder",
        )
    )


@router.callback_query(F.data == TEMPLATE_BACK_CALLBACK)
async def handle_template_back(
    callback: CallbackQuery,
    state: FSMContext,
    template_catalog: TemplateCatalog,
    user_sessions: UserSessionStore,
) -> None:
    """Return to the previous Google Drive folder level or vacancy list."""
    project_id: str | None = None
    vacancy_id: str | None = None
    
    if callback.from_user is not None:
        session = user_sessions.get(callback.from_user.id)
        project_id = session.project
        vacancy_id = session.vacancy
        session.template = None

    await callback.answer()
    if project_id is None:
        await state.set_state(ContractFlow.waiting_project)
        if callback.message is not None:
            await callback.message.answer("Сначала выберите проект через /start.")
        return

    parent_id = None
    if _has_navigation(template_catalog) and vacancy_id:
        try:
            folder = template_catalog.get_navigation_folder(project_id, vacancy_id)
            parent_id = folder.parent_id
        except Exception:
            pass

    await state.set_state(ContractFlow.waiting_vacancy)
    if callback.message is not None:
        await callback.message.answer(
            "Выберите раздел.",
            reply_markup=build_vacancies_keyboard(template_catalog, project_id, parent_id),
        )


@router.callback_query(F.data.startswith(TEMPLATE_CALLBACK_PREFIX))
async def handle_template_selected(
    callback: CallbackQuery,
    state: FSMContext,
    template_catalog: TemplateCatalog,
    user_sessions: UserSessionStore,
) -> None:
    """Save selected template and ask for employee data."""
    template_id = str(callback.data or "")[len(TEMPLATE_CALLBACK_PREFIX):]
    template = template_catalog.get_template(template_id)

    if callback.from_user is not None:
        session = user_sessions.get(callback.from_user.id)
        session.template = template_id
        _logger.info(
            "Template selected: user=%s template=%s",
            callback.from_user.id,
            template_id,
        )

    await state.set_state(ContractFlow.waiting_employee_data)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            build_hr_template_text(template.name),
            parse_mode="HTML",
            reply_markup=build_generation_actions_keyboard(),
        )
