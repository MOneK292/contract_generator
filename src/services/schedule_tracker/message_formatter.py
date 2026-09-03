"""HTML message formatting for Telegram notifications according to TZ."""

from __future__ import annotations

import html
from src.services.schedule_tracker.models import ChangeType, ScheduleReport


def format_schedule_message(report: ScheduleReport) -> str:
    """Format ScheduleReport into Telegram HTML message."""
    manager_escaped = html.escape(report.manager)
    date_escaped = html.escape(report.date)

    lines: list[str] = [
        "📊 <b>Обновление расписания</b>",
        f"👤 <b>Менеджер:</b> {manager_escaped}",
        f"📅 <b>Дата:</b> {date_escaped}\n",
        "🔔 <b>Обновлено:</b>",
    ]

    for diff in report.diffs:
        time_tag = f"<b>{html.escape(diff.time)}:</b>"
        if diff.change_type == ChangeType.DELETED:
            old_escaped = html.escape(diff.old_value or "")
            lines.append(f"• {time_tag} <i>[Удалено: {old_escaped}]</i>")
        else:
            new_escaped = html.escape(diff.new_value or "")
            lines.append(f"• {time_tag} {new_escaped}")

    if report.phones:
        lines.append("\n📞 <b>Номера телефонов:</b>")
        for phone in report.phones:
            lines.append(f"• <code>{html.escape(phone)}</code>")

    if report.full_schedule:
        schedule_lines = [
            f"• <b>{html.escape(slot.time)}:</b> {html.escape(slot.value)}"
            for slot in report.full_schedule
        ]
        schedule_block = "\n".join(schedule_lines)
        lines.append(f"\n<blockquote expandable><b>Полное расписание на день:</b>\n{schedule_block}</blockquote>")
    else:
        lines.append("\n<blockquote expandable><b>Полное расписание на день:</b>\n<i>Расписание пусто</i></blockquote>")

    return "\n".join(lines)


def format_current_schedule_message(
    manager: str,
    date: str,
    slots: list[ScheduleSlot],
    phones: list[str],
) -> str:
    """Format on-demand schedule view into Telegram HTML message."""
    manager_escaped = html.escape(manager)
    date_escaped = html.escape(date)

    lines: list[str] = [
        "📅 <b>Актуальное расписание на сегодня</b>",
        f"👤 <b>Менеджер:</b> {manager_escaped}",
        f"🗓 <b>Дата:</b> {date_escaped}\n",
    ]

    if phones:
        lines.append("📞 <b>Номера телефонов:</b>")
        for phone in phones:
            lines.append(f"• <code>{html.escape(phone)}</code>")
        lines.append("")

    if slots:
        schedule_lines = [
            f"• <b>{html.escape(slot.time)}:</b> {html.escape(slot.value)}"
            for slot in slots
        ]
        schedule_block = "\n".join(schedule_lines)
        lines.append(f"<blockquote expandable><b>Полное расписание на день:</b>\n{schedule_block}</blockquote>")
    else:
        lines.append("<i>На сегодня расписание пусто</i>")

    return "\n".join(lines)

