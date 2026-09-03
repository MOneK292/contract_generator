"""Time and date utility functions for schedule parsing and timezone operations."""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def parse_time_slot(raw_value: Any) -> str | None:
    """Convert Excel decimal or string time to normalized 'HH:MM' if within 10:00-19:00.
    
    Returns 'HH:MM' string or None if invalid/out of range.
    """
    if raw_value is None:
        return None

    # Handle float / numeric Excel serial time (fraction of a 24-hour day)
    try:
        if isinstance(raw_value, (int, float)):
            num = float(raw_value)
            if 0.0 <= num <= 1.0:
                total_seconds = round(num * 86400)
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                if 10 <= hours <= 19:
                    return f"{hours:02d}:{minutes:02d}"
                return None
    except (ValueError, TypeError):
        pass

    # Handle string representation
    text = str(raw_value).strip()
    if not text:
        return None

    # Try numeric string (e.g. "0.4166666666666667")
    try:
        num = float(text)
        if 0.0 <= num <= 1.0:
            total_seconds = round(num * 86400)
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            if 10 <= hours <= 19:
                return f"{hours:02d}:{minutes:02d}"
            return None
    except ValueError:
        pass

    # Try HH:MM, HH.MM, HH:MM:SS formats
    match = re.match(r"^(\d{1,2})[:.](\d{2})(?::\d{2})?$", text)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        if 0 <= minutes < 60 and 10 <= hours <= 19:
            return f"{hours:02d}:{minutes:02d}"

    return None


def get_moscow_now(tz_name: str = "Europe/Moscow") -> datetime:
    """Get current datetime in specified timezone (default Moscow)."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = MOSCOW_TZ
    return datetime.now(tz)


def get_moscow_today_str(tz_name: str = "Europe/Moscow") -> str:
    """Get current date formatted as DD.MM.YYYY in Moscow timezone."""
    now = get_moscow_now(tz_name)
    return now.strftime("%d.%m.%Y")


def get_moscow_iso_week(tz_name: str = "Europe/Moscow") -> int:
    """Get current ISO week number in Moscow timezone."""
    now = get_moscow_now(tz_name)
    return now.isocalendar()[1]


def clean_cell_text(value: Any) -> str:
    """Clean cell string from trailing/leading spaces, CR, and control characters."""
    if value is None:
        return ""
    text = str(value).replace("\r", "").strip()
    # Remove control characters except standard whitespace
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


def is_within_time_window(
    start_time_str: str = "09:00",
    end_time_str: str = "20:00",
    current_time: datetime | None = None,
    tz_name: str = "Europe/Moscow",
) -> bool:
    """Check if the current (or given) time is within the allowed daily notification window.
    
    Default window: 09:00 to 20:00 Europe/Moscow.
    """
    try:
        start_t = datetime.strptime(start_time_str.strip(), "%H:%M").time()
        end_t = datetime.strptime(end_time_str.strip(), "%H:%M").time()
    except Exception:
        # Fallback to standard 09:00 - 20:00 if invalid format
        start_t = datetime.strptime("09:00", "%H:%M").time()
        end_t = datetime.strptime("20:00", "%H:%M").time()

    now_dt = current_time or get_moscow_now(tz_name)
    now_t = now_dt.time()

    if start_t <= end_t:
        return start_t <= now_t <= end_t
    else:
        # Overnight range, e.g. 22:00 to 06:00
        return now_t >= start_t or now_t <= end_t

