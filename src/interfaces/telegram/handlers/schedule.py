"""Telegram handler for on-demand schedule retrieval."""

from __future__ import annotations

import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.services.schedule_tracker.message_formatter import format_current_schedule_message
from src.services.schedule_tracker.time_utils import get_moscow_today_str
from src.services.schedule_tracker.tracker_service import ScheduleTrackerService

_logger = logging.getLogger(__name__)
router = Router(name="schedule")


@router.message(Command("schedule", "today", "raspisanie"))
async def handle_schedule_command(
    message: Message,
    schedule_tracker: ScheduleTrackerService | None = None,
) -> None:
    """Fetch and display today's current manager schedule on-demand."""
    if not schedule_tracker:
        await message.answer(
            "⚠️ <b>Мониторинг расписания не настроен</b>\n\n"
            "Интеграция с Google Таблицей не активна в настройках бота.",
            parse_mode="HTML",
        )
        return

    try:
        if message.bot:
            await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    except Exception:
        pass

    try:
        result = await schedule_tracker.get_current_schedule()
        if result is None:
            today_str = get_moscow_today_str(schedule_tracker.timezone)
            await message.answer(
                f"ℹ️ <b>Расписание не найдено</b>\n\n"
                f"На сегодня (<code>{today_str}</code>) расписание для <b>{schedule_tracker.manager_name}</b> "
                "в таблице отсутствует или лист текущей недели не найден.",
                parse_mode="HTML",
            )
            return

        manager, date_str, slots, phones = result
        text = format_current_schedule_message(
            manager=manager,
            date=date_str,
            slots=slots,
            phones=phones,
        )
        await message.answer(text, parse_mode="HTML")
    except Exception as error:
        _logger.exception("Error while fetching on-demand schedule: %s", error)
        await message.answer(
            "❌ <b>Ошибка при получении расписания</b>\n\n"
            "Не удалось связаться с Google Таблицей. Пожалуйста, попробуйте позже.",
            parse_mode="HTML",
        )
