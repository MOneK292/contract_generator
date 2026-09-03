"""Data models for schedule tracker service."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ChangeType(str, Enum):
    """Type of schedule change."""

    NEW = "new"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass(frozen=True)
class ScheduleSlot:
    """Represents a time slot in the schedule."""

    time: str
    value: str


@dataclass(frozen=True)
class ScheduleDiff:
    """Represents a single detected difference in schedule."""

    time: str
    old_value: str | None
    new_value: str | None
    change_type: ChangeType


@dataclass(frozen=True)
class ScheduleReport:
    """Full update report ready for formatting and sending."""

    manager: str
    date: str
    diffs: list[ScheduleDiff]
    phones: list[str]
    full_schedule: list[ScheduleSlot]
    new_schedule: dict[str, str]
