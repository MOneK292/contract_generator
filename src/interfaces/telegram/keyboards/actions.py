"""Reply keyboards for post-template actions."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

NEXT_EMPLOYEE_TEXT = "➕ Следующий сотрудник"
CHANGE_TEMPLATE_TEXT = "🔄 Сменить шаблон"
START_OVER_TEXT = "🏠 Выбрать другой проект"


def build_generation_actions_keyboard() -> InlineKeyboardMarkup:
    """Build a keyboard for repeated HR work after template selection."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=NEXT_EMPLOYEE_TEXT, callback_data="action_next_employee")],
            [InlineKeyboardButton(text=CHANGE_TEMPLATE_TEXT, callback_data="action_change_template")],
            [InlineKeyboardButton(text=START_OVER_TEXT, callback_data="action_start_over")],
        ]
    )
