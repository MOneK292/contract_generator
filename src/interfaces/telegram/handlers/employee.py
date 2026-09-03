"""Telegram employee data handler."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, Message, ReplyKeyboardRemove

from src.core.contract_engine import ContractEngine, ContractRequest, ContractResult
from src.interfaces.telegram.hr_template import (
    build_hr_template_text,
    build_missing_fields_text,
)
from src.interfaces.telegram.keyboards import (
    build_generation_actions_keyboard,
    build_projects_keyboard,
    build_templates_keyboard,
)
from src.interfaces.telegram.states import ContractFlow, UserSession, UserSessionStore
from src.services.config import TemplateCatalog


router = Router(name="employee")
_logger = logging.getLogger(__name__)


@router.message(ContractFlow.waiting_employee_data)
async def handle_employee_data(
    message: Message,
    state: FSMContext,
    template_catalog: TemplateCatalog,
    user_sessions: UserSessionStore,
    contract_engine: ContractEngine | None = None,
) -> None:
    """Generate a contract from one HR text message."""
    text = (message.text or "").strip()
    user_id = message.from_user.id if message.from_user is not None else 0
    session = user_sessions.get(user_id)


    if not _session_is_ready(session):
        await state.set_state(ContractFlow.waiting_project)
        await message.answer(
            "Сначала выберите проект, вакансию и шаблон через /start.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if contract_engine is None:
        _logger.error("Generation failed: ContractEngine is not configured")
        await message.answer(
            "❌ Не удалось сформировать договор.\n\n"
            "Причина:\nContractEngine не настроен.",
            reply_markup=build_generation_actions_keyboard(),
        )
        return

    _logger.info("User started generation: user=%s", user_id)
    progress_message = await message.answer("⏳ Генерирую договор...")
    result = await _generate_contract(contract_engine, session, text)
    await _delete_message(progress_message)

    await _handle_generation_result(
        message,
        state,
        template_catalog,
        session,
        user_id,
        text,
        result,
    )


@router.message(ContractFlow.waiting_missing_fields)
async def handle_missing_fields(
    message: Message,
    state: FSMContext,
    template_catalog: TemplateCatalog,
    user_sessions: UserSessionStore,
    contract_engine: ContractEngine | None = None,
) -> None:
    """Merge missing employee fields and retry contract generation."""
    text = (message.text or "").strip()
    user_id = message.from_user.id if message.from_user is not None else 0

    session = user_sessions.get(user_id)
    if not _session_is_ready(session):
        await state.set_state(ContractFlow.waiting_project)
        await message.answer(
            "Сначала выберите проект, вакансию и шаблон через /start.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if contract_engine is None:
        _logger.error("Generation failed: ContractEngine is not configured")
        await message.answer(
            "❌ Не удалось сформировать договор.\n\n"
            "Причина:\nContractEngine не настроен.",
            reply_markup=build_generation_actions_keyboard(),
        )
        return

    combined_text = _combine_employee_text(session.employee_text, text)
    _logger.info("User continued generation: user=%s", user_id)
    progress_message = await message.answer("⏳ Генерирую договор...")
    result = await _generate_contract(contract_engine, session, combined_text)
    await _delete_message(progress_message)

    await _handle_generation_result(
        message,
        state,
        template_catalog,
        session,
        user_id,
        combined_text,
        result,
    )


async def _handle_generation_result(
    message: Message,
    state: FSMContext,
    template_catalog: TemplateCatalog,
    session: UserSession,
    user_id: int,
    employee_text: str,
    result: ContractResult,
) -> None:
    """Send a generated document or ask for unresolved placeholders."""
    if not result.success:
        _logger.error(
            "Generation failed: user=%s execution_time=%.3f",
            user_id,
            result.execution_time,
        )
        await message.answer(
            "❌ Не удалось сформировать договор.\n\n"
            f"Причина:\n{result.error_message or 'Неизвестная ошибка.'}",
            reply_markup=build_generation_actions_keyboard(),
        )
        return

    if result.unresolved_placeholders:
        _logger.info(
            "Generation has unresolved placeholders: user=%s count=%s",
            user_id,
            len(result.unresolved_placeholders),
        )
        session.employee_text = employee_text
        session.missing_fields = list(result.unresolved_placeholders)
        session.pending_request = ContractRequest(
            project_id=str(session.project),
            vacancy_id=str(session.vacancy),
            template_id=session.template,
            raw_employee_text=employee_text,
        )
        _delete_generated_output(result)
        await state.set_state(ContractFlow.waiting_missing_fields)
        await message.answer(
            build_missing_fields_text(result.unresolved_placeholders),
            parse_mode="HTML",
        )
        return

    document_paths = _generated_document_paths(result)
    if not document_paths:
        _logger.error("Generation failed: generated document path is missing")
        await message.answer(
            "❌ Не удалось сформировать договор.\n\n"
            "Причина:\nEngine не вернул путь к готовому файлу.",
            reply_markup=build_generation_actions_keyboard(),
        )
        return

    vacancy_name = template_catalog.get_vacancy(str(session.vacancy)).name
    for document_path in document_paths:
        filename = _document_filename(employee_text, vacancy_name, document_path.suffix)
        await message.answer_document(FSInputFile(document_path, filename=filename))
    _logger.info("Document sent: user=%s", user_id)
    _delete_sent_files(document_paths)
    session.clear_pending_generation()

    await state.set_state(ContractFlow.waiting_employee_data)
    _logger.info(
        "Generation finished: user=%s execution_time=%.3f",
        user_id,
        result.execution_time,
    )
    await message.answer(
        "✅ Договор успешно сформирован.\n\n"
        "Вы можете отправить данные следующего сотрудника.",
        reply_markup=build_generation_actions_keyboard(),
    )


@router.callback_query(lambda c: c.data == "action_next_employee")
async def process_action_next_employee(
    callback: aiogram.types.CallbackQuery,
    state: FSMContext,
) -> None:
    await state.set_state(ContractFlow.waiting_employee_data)
    await callback.message.answer(
        "Отправьте данные сотрудника одним сообщением.",
        reply_markup=build_generation_actions_keyboard(),
    )
    await callback.answer()

@router.callback_query(lambda c: c.data == "action_change_template")
async def process_action_change_template(
    callback: aiogram.types.CallbackQuery,
    state: FSMContext,
    template_catalog: TemplateCatalog,
    user_sessions: UserSessionStore,
) -> None:
    user_id = callback.from_user.id
    session = user_sessions.get(user_id)
    if not session.project or not session.vacancy:
        await process_action_start_over(callback, state, template_catalog, user_sessions)
        return

    session.template = None
    await state.set_state(ContractFlow.waiting_template)
    await callback.message.answer(
        "Доступные шаблоны:",
        reply_markup=build_templates_keyboard(
            template_catalog,
            session.project,
            session.vacancy,
        ),
    )
    await callback.answer()

@router.callback_query(lambda c: c.data == "action_start_over")
async def process_action_start_over(
    callback: aiogram.types.CallbackQuery,
    state: FSMContext,
    template_catalog: TemplateCatalog,
    user_sessions: UserSessionStore,
) -> None:
    user_id = callback.from_user.id
    user_sessions.reset(user_id)
    await state.set_state(ContractFlow.waiting_project)
    await callback.message.answer(
        "Доступные проекты:",
        reply_markup=build_projects_keyboard(template_catalog),
    )
    await callback.answer()


async def _generate_contract(
    contract_engine: ContractEngine,
    session: UserSession,
    employee_text: str,
) -> ContractResult:
    request = ContractRequest(
        project_id=str(session.project),
        vacancy_id=str(session.vacancy),
        template_id=session.template,
        raw_employee_text=employee_text,
    )
    return await asyncio.to_thread(contract_engine.generate, request)


async def _delete_message(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        _logger.debug("Failed to delete progress message", exc_info=True)


def _session_is_ready(session: UserSession) -> bool:
    return bool(session.project and session.vacancy and session.template)


def _generated_document_paths(result: ContractResult) -> list[Path]:
    paths: list[Path] = []
    if result.output_docx is not None:
        paths.append(Path(result.output_docx))
    if result.output_pdf is not None:
        paths.append(Path(result.output_pdf))
    return paths


def _combine_employee_text(existing_text: str, new_text: str) -> str:
    existing = existing_text.strip()
    new = new_text.strip()
    if not existing:
        return new
    if not new:
        return existing
    return f"{existing}\n{new}"


def _delete_generated_output(result: ContractResult) -> None:
    for value in (result.output_docx, result.output_pdf):
        if value is None:
            continue
        path = Path(value)
        if not path.exists():
            continue
        try:
            path.unlink()
        except OSError:
            _logger.warning("Failed to delete incomplete generated file: %s", path)


def _document_filename(employee_text: str, vacancy_name: str, suffix: str) -> str:
    last_name = _extract_last_name(employee_text)
    extension = suffix if suffix else ".docx"
    if not last_name:
        return f"contract{extension}"
    return f"{_safe_filename(last_name)}_{_safe_filename(vacancy_name)}{extension}"


def _extract_last_name(employee_text: str) -> str | None:
    for line in employee_text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().casefold() == "фио":
            parts = value.strip().split()
            return parts[0] if parts else None
    return None


def _safe_filename(value: str) -> str:
    safe_value = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("_.")
    return safe_value or "contract"


def _delete_sent_files(paths: list[Path]) -> None:
    for path in paths:
        if path.suffix.lower() not in {".docx", ".pdf"} or not path.exists():
            continue
        try:
            path.unlink()
        except OSError:
            _logger.warning("Failed to delete sent file: %s", path, exc_info=True)
