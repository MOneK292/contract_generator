"""Date-derived fields processor."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from src.processors.base import FieldProcessor


@dataclass
class DateProcessor(FieldProcessor):
    """Adds day, month, month number, and year fields from date fields."""

    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
        init=False,
        repr=False,
    )

    def process(self, data: dict[str, str]) -> dict[str, str]:
        """Add date components for every `ДД.ММ.ГГГГ` field containing `Дата`."""
        result = dict(data)

        for field_name, field_value in data.items():
            if not self._is_date_field(field_name):
                continue

            parsed_date = self._parse_date(field_value)
            if parsed_date is None:
                self._logger.debug("Skipping invalid date field: %s", field_name)
                continue

            self._add_components(result, field_name, parsed_date)

        return result

    def _is_date_field(self, field_name: str) -> bool:
        return "дата" in field_name.lower()

    def _parse_date(self, value: str) -> datetime | None:
        try:
            return datetime.strptime(value.strip(), "%d.%m.%Y")
        except ValueError:
            return None

    def _add_components(
        self,
        result: dict[str, str],
        prefix: str,
        parsed_date: datetime,
    ) -> None:
        suffix = f"{prefix} " if prefix else ""
        result[f"{suffix}День"] = parsed_date.strftime("%d")
        result[f"{suffix}Месяц"] = self._month_name(parsed_date.month)
        result[f"{suffix}МесяцЧ"] = parsed_date.strftime("%m")
        result[f"{suffix}Год"] = parsed_date.strftime("%Y")

    def _month_name(self, month_number: int) -> str:
        month_names = (
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
        return month_names[month_number - 1]
