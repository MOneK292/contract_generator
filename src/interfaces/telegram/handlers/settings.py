"""Handlers for dynamic monitoring settings via Telegram."""

import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.services.schedule_tracker.tracker_service import ScheduleTrackerService

_logger = logging.getLogger(__name__)

settings_router = Router(name="settings")


class SettingsFlow(StatesGroup):
    waiting_start_time = State()
    waiting_end_time = State()
    waiting_interval = State()


def build_settings_keyboard(settings: dict) -> InlineKeyboardMarkup:
    """Build the settings inline keyboard based on current user state."""
    enabled = bool(settings.get("enabled", True))
    start_time = settings.get("notification_start_time", "09:00")
    end_time = settings.get("notification_end_time", "20:00")
    interval = settings.get("poll_interval_seconds", 60)

    status_text = "🟢 Включено" if enabled else "🔴 Отключено"
    toggle_text = "Отключить" if enabled else "Включить"
    toggle_callback = "settings_disable" if enabled else "settings_enable"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Статус: {status_text} (Нажмите, чтобы {toggle_text.lower()})", callback_data=toggle_callback)],
            [InlineKeyboardButton(text=f"Начало окна: {start_time}", callback_data="settings_edit_start")],
            [InlineKeyboardButton(text=f"Конец окна: {end_time}", callback_data="settings_edit_end")],
            [InlineKeyboardButton(text=f"Интервал опроса: {interval} сек", callback_data="settings_edit_interval")],
            [InlineKeyboardButton(text="🔄 Обновить меню", callback_data="settings_refresh")],
        ]
    )


def format_settings_text(settings: dict) -> str:
    """Format the user settings status text."""
    enabled = bool(settings.get("enabled", True))
    start_time = settings.get("notification_start_time", "09:00")
    end_time = settings.get("notification_end_time", "20:00")
    interval = settings.get("poll_interval_seconds", 60)
    
    return (
        "⚙️ <b>Настройки мониторинга расписания</b>\n\n"
        f"<b>Статус уведомлений:</b> {'🟢 Работает' if enabled else '🔴 Остановлен'}\n"
        f"<b>Ваше окно уведомлений:</b> с {start_time} по {end_time} (МСК)\n"
        f"<b>Интервал опроса таблицы:</b> {interval} секунд\n\n"
        "<i>Статус и окно настраиваются персонально. Интервал опроса единый для системы.</i>"
    )


async def _get_merged_settings(schedule_tracker: ScheduleTrackerService, user_id: int) -> dict:
    user_settings = await schedule_tracker.repository.get_user_settings(user_id)
    global_settings = await schedule_tracker.repository.get_settings()
    user_settings["poll_interval_seconds"] = global_settings.get("poll_interval_seconds", 60)
    return user_settings


@settings_router.message(Command("settings"))
async def cmd_settings(
    message: Message,
    schedule_tracker: ScheduleTrackerService | None = None,
) -> None:
    """Show the dynamic monitoring settings menu for the current user."""
    if not schedule_tracker or not message.from_user:
        await message.answer("⚠️ Мониторинг расписания не активен в этом боте.")
        return

    user_id = message.from_user.id
    settings = await _get_merged_settings(schedule_tracker, user_id)
    
    await message.answer(
        text=format_settings_text(settings),
        reply_markup=build_settings_keyboard(settings),
        parse_mode="HTML"
    )


@settings_router.callback_query(F.data == "settings_refresh")
async def process_settings_refresh(
    callback: CallbackQuery,
    schedule_tracker: ScheduleTrackerService | None = None,
) -> None:
    if not schedule_tracker or not callback.from_user:
        await callback.answer("Мониторинг отключен", show_alert=True)
        return
        
    user_id = callback.from_user.id
    settings = await _get_merged_settings(schedule_tracker, user_id)
    await callback.message.edit_text(
        text=format_settings_text(settings),
        reply_markup=build_settings_keyboard(settings),
        parse_mode="HTML"
    )
    await callback.answer("Обновлено")


@settings_router.callback_query(F.data == "settings_disable")
async def process_settings_disable(
    callback: CallbackQuery,
    schedule_tracker: ScheduleTrackerService | None = None,
) -> None:
    if schedule_tracker and callback.from_user:
        await schedule_tracker.repository.update_user_settings(callback.from_user.id, enabled=False)
        await process_settings_refresh(callback, schedule_tracker)
    else:
        await callback.answer("Ошибка", show_alert=True)


@settings_router.callback_query(F.data == "settings_enable")
async def process_settings_enable(
    callback: CallbackQuery,
    schedule_tracker: ScheduleTrackerService | None = None,
) -> None:
    if schedule_tracker and callback.from_user:
        await schedule_tracker.repository.update_user_settings(callback.from_user.id, enabled=True)
        await process_settings_refresh(callback, schedule_tracker)
    else:
        await callback.answer("Ошибка", show_alert=True)


@settings_router.callback_query(F.data == "settings_edit_start")
async def process_edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer("Введите ваше время начала окна уведомлений в формате ЧЧ:ММ (МСК), например 09:00:")
    await state.set_state(SettingsFlow.waiting_start_time)
    await callback.answer()


@settings_router.message(SettingsFlow.waiting_start_time)
async def process_start_time(message: Message, state: FSMContext, schedule_tracker: ScheduleTrackerService | None = None) -> None:
    time_str = message.text.strip()
    if len(time_str) == 5 and ":" in time_str:
        if schedule_tracker and message.from_user:
            await schedule_tracker.repository.update_user_settings(message.from_user.id, notification_start_time=time_str)
            await message.answer(f"✅ Персональное время начала изменено на {time_str}. Введите /settings для проверки.")
        await state.clear()
    else:
        await message.answer("❌ Неверный формат. Пожалуйста, используйте формат ЧЧ:ММ (например, 09:00).")


@settings_router.callback_query(F.data == "settings_edit_end")
async def process_edit_end(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer("Введите ваше время окончания окна уведомлений в формате ЧЧ:ММ (МСК), например 20:00:")
    await state.set_state(SettingsFlow.waiting_end_time)
    await callback.answer()


@settings_router.message(SettingsFlow.waiting_end_time)
async def process_end_time(message: Message, state: FSMContext, schedule_tracker: ScheduleTrackerService | None = None) -> None:
    time_str = message.text.strip()
    if len(time_str) == 5 and ":" in time_str:
        if schedule_tracker and message.from_user:
            await schedule_tracker.repository.update_user_settings(message.from_user.id, notification_end_time=time_str)
            await message.answer(f"✅ Персональное время окончания изменено на {time_str}. Введите /settings для проверки.")
        await state.clear()
    else:
        await message.answer("❌ Неверный формат. Пожалуйста, используйте формат ЧЧ:ММ (например, 20:00).")


@settings_router.callback_query(F.data == "settings_edit_interval")
async def process_edit_interval(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer("Введите новый интервал опроса в секундах (минимум 15, максимум 3600):")
    await state.set_state(SettingsFlow.waiting_interval)
    await callback.answer()


@settings_router.message(SettingsFlow.waiting_interval)
async def process_interval(message: Message, state: FSMContext, schedule_tracker: ScheduleTrackerService | None = None) -> None:
    try:
        val = int(message.text.strip())
        if 15 <= val <= 3600:
            if schedule_tracker:
                await schedule_tracker.repository.update_settings(poll_interval_seconds=val)
                await message.answer(f"✅ Интервал опроса изменен на {val} сек. Введите /settings для проверки.")
            await state.clear()
        else:
            await message.answer("❌ Интервал должен быть числом от 15 до 3600. Попробуйте еще раз.")
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число (например, 60).")
