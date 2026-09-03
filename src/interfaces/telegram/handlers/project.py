"""Telegram project selection handler."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from src.interfaces.telegram.keyboards import (
    PROJECT_CALLBACK_PREFIX,
    PROJECT_BACK_CALLBACK,
    build_vacancies_keyboard,
)
from src.interfaces.telegram.states import ContractFlow, UserSessionStore
from src.services.config import TemplateCatalog


router = Router(name="project")
_logger = logging.getLogger(__name__)


@router.callback_query(F.data == PROJECT_BACK_CALLBACK)
async def handle_project_back(
    callback: CallbackQuery,
    state: FSMContext,
    user_sessions: UserSessionStore,
) -> None:
    """Handle back button from projects selection."""
    if callback.from_user is not None:
        user_sessions.reset(callback.from_user.id)
    await state.clear()
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_text(
            "Выбор проекта отменен. Введите /start, чтобы начать заново."
        )


@router.callback_query(F.data.startswith(PROJECT_CALLBACK_PREFIX))
async def handle_project_selected(
    callback: CallbackQuery,
    state: FSMContext,
    template_catalog: TemplateCatalog,
    user_sessions: UserSessionStore,
) -> None:
    """Save selected project and show its vacancies."""
    project_id = str(callback.data or "")[len(PROJECT_CALLBACK_PREFIX):]
    project = template_catalog.get_project(project_id)

    if callback.from_user is not None:
        session = user_sessions.get(callback.from_user.id)
        session.project = project_id
        session.vacancy = None
        session.template = None
        _logger.info("Project selected: user=%s project=%s", callback.from_user.id, project_id)

    await state.set_state(ContractFlow.waiting_vacancy)
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            f"Проект: {project.name}\n\nВыберите вакансию.",
            reply_markup=build_vacancies_keyboard(template_catalog, project_id),
        )

