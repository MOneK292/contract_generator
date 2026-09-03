"""Telegram /start handler."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from src.interfaces.telegram.keyboards import build_projects_keyboard
from src.interfaces.telegram.states import ContractFlow, UserSessionStore
from src.services.config import TemplateCatalog


router = Router(name="start")
_logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def handle_start(
    message: Message,
    state: FSMContext,
    template_catalog: TemplateCatalog,
    user_sessions: UserSessionStore,
) -> None:
    """Start the project selection flow."""
    if message.from_user is not None:
        user_sessions.reset(message.from_user.id)
        _logger.info("User started bot: %s", message.from_user.id)
    else:
        _logger.info("User started bot without Telegram user metadata")

    await state.set_state(ContractFlow.waiting_project)
    
    # Remove any old reply keyboards sticking around
    await message.answer(
        "Добро пожаловать.",
        reply_markup=ReplyKeyboardRemove(),
    )
    
    await message.answer(
        "Выберите проект.",
        reply_markup=build_projects_keyboard(template_catalog),
    )
