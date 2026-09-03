"""Telegram vacancy selection handler."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from src.interfaces.telegram.keyboards import (
    VACANCY_BACK_CALLBACK_PREFIX,
    VACANCY_CALLBACK_PREFIX,
    build_projects_keyboard,
    build_templates_keyboard,
    build_vacancies_keyboard,
)
from src.interfaces.telegram.states import ContractFlow, UserSessionStore
from src.services.config import TemplateCatalog


router = Router(name="vacancy")
_logger = logging.getLogger(__name__)


@router.callback_query(F.data.startswith(VACANCY_CALLBACK_PREFIX))
async def handle_vacancy_selected(
    callback: CallbackQuery,
    state: FSMContext,
    template_catalog: TemplateCatalog,
    user_sessions: UserSessionStore,
) -> None:
    """Save selected vacancy and show available templates."""
    folder_id = str(callback.data or "")[len(VACANCY_CALLBACK_PREFIX):]

    project_id: str | None = None
    if callback.from_user is not None:
        session = user_sessions.get(callback.from_user.id)
        project_id = session.project
        session.template = None
        _logger.info("Drive folder selected: user=%s folder=%s", callback.from_user.id, folder_id)

    await callback.answer()
    if project_id is None:
        if callback.message is not None:
            await callback.message.answer("Сначала выберите проект через /start.")
        await state.set_state(ContractFlow.waiting_project)
        return

    if _has_navigation(template_catalog):
        folder = template_catalog.get_navigation_folder(project_id, folder_id)
        child_folders = template_catalog.list_navigation_children(project_id, folder_id)
        templates = template_catalog.list_templates_for_folder(project_id, folder_id)
        if child_folders:
            await state.set_state(ContractFlow.waiting_vacancy)
            if callback.message is not None:
                await callback.message.answer(
                    f"{folder.name}\n\nВыберите следующий раздел.",
                    reply_markup=build_vacancies_keyboard(
                        template_catalog,
                        project_id,
                        folder_id,
                    ),
                )
            return
        if templates:
            if callback.from_user is not None:
                session = user_sessions.get(callback.from_user.id)
                session.vacancy = folder_id
            await state.set_state(ContractFlow.waiting_template)
            if callback.message is not None:
                await callback.message.answer(
                    f"{folder.name}\n\nВыберите шаблон.",
                    reply_markup=build_templates_keyboard(template_catalog, project_id, folder_id),
                )
            return

    vacancy_id = folder_id
    vacancy = template_catalog.get_vacancy(vacancy_id)
    if callback.from_user is not None:
        session = user_sessions.get(callback.from_user.id)
        session.vacancy = vacancy_id
        _logger.info("Vacancy selected: user=%s vacancy=%s", callback.from_user.id, vacancy_id)

    await state.set_state(ContractFlow.waiting_template)
    if callback.message is not None:
        await callback.message.answer(
            f"Вакансия: {vacancy.name}\n\nВыберите шаблон.",
            reply_markup=build_templates_keyboard(template_catalog, project_id, vacancy_id),
        )


@router.callback_query(F.data.startswith(VACANCY_BACK_CALLBACK_PREFIX))
async def handle_vacancy_back(
    callback: CallbackQuery,
    state: FSMContext,
    template_catalog: TemplateCatalog,
    user_sessions: UserSessionStore,
) -> None:
    """Return to the previous Google Drive folder level or projects list."""
    target = str(callback.data or "")[len(VACANCY_BACK_CALLBACK_PREFIX):]
    
    if target == "__projects__":
        if callback.from_user is not None:
            user_sessions.reset(callback.from_user.id)
        await state.set_state(ContractFlow.waiting_project)
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(
                "Выберите проект.",
                reply_markup=build_projects_keyboard(template_catalog),
            )
        return

    parent_id = target or None
    project_id: str | None = None
    if callback.from_user is not None:
        session = user_sessions.get(callback.from_user.id)
        project_id = session.project
        session.vacancy = None
        session.template = None

    await callback.answer()
    if project_id is None:
        await state.set_state(ContractFlow.waiting_project)
        if callback.message is not None:
            await callback.message.answer("Сначала выберите проект через /start.")
        return

    await state.set_state(ContractFlow.waiting_vacancy)
    if callback.message is not None:
        await callback.message.answer(
            "Выберите раздел.",
            reply_markup=build_vacancies_keyboard(template_catalog, project_id, parent_id),
        )


def _has_navigation(template_catalog: TemplateCatalog) -> bool:
    return all(
        hasattr(template_catalog, name)
        for name in (
            "get_navigation_folder",
            "list_navigation_children",
            "list_templates_for_folder",
        )
    )
