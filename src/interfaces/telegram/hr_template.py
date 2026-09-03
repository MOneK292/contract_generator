"""Telegram HR input templates."""

from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo


MOSCOW_TZ = ZoneInfo("Europe/Moscow")
MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
HR_TEMPLATE_FIELDS = (
    "Ф",
    "И",
    "О",
    "Дата рождения",
    "Телефон",
    "Город",
    "Ставка",
    "СНИЛС",
    "ИНН",
    "Серия",
    "Номер П",
    "Кем выдан",
    "Дата выдачи",
    "Регистрация",
)


def build_hr_template_text(template_name: str, *, now: datetime | None = None) -> str:
    """Return the HR instruction message for the selected template."""
    form = build_hr_form(now=now)
    return (
        "Выбран шаблон:\n\n"
        f"<b>{escape(template_name)}</b>\n\n"
        "Отправьте данные сотрудника одним сообщением:\n\n"
        f"<pre>{escape(form)}</pre>"
    )


def build_hr_form(*, now: datetime | None = None) -> str:
    """Return the raw HR form with Moscow-date contract fields prefilled."""
    current = _moscow_now(now)
    lines = [f"{field}:" for field in HR_TEMPLATE_FIELDS]
    lines.extend(
        [
            f"День: {current.day:02d}",
            f"Месяц: {MONTHS[current.month - 1]}",
            f"Год: {current.year}",
            f"МесяцЧ: {current.month:02d}",
        ]
    )
    return "\n".join(lines)


def build_missing_fields_text(placeholders: list[str]) -> str:
    """Return a copyable form containing only unresolved placeholders."""
    fields = [placeholder.strip() for placeholder in placeholders if placeholder.strip()]
    bullet_list = "\n".join(f"• {field}" for field in fields)
    form = "\n".join(f"{field}:" for field in fields)
    return (
        "Не хватает данных:\n\n"
        f"{escape(bullet_list)}\n\n"
        "Отправьте одним сообщением:\n\n"
        f"<pre>{escape(form)}</pre>"
    )


def _moscow_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(MOSCOW_TZ)
    if value.tzinfo is None:
        return value.replace(tzinfo=MOSCOW_TZ)
    return value.astimezone(MOSCOW_TZ)
