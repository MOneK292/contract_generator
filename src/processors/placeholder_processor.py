"""Placeholder compatibility processor."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.processors.base import FieldProcessor
from src.processors.placeholder_aliases import PLACEHOLDER_ALIASES


@dataclass
class PlaceholderProcessor(FieldProcessor):
    """Add only explicitly configured placeholder aliases.

    The processor does not inspect templates and does not overwrite values that
    came from HR input or earlier processors. It applies only
    `PLACEHOLDER_ALIASES`; fields without an explicit rule must remain
    unresolved so Telegram can ask HR for them.
    """

    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
        init=False,
        repr=False,
    )

    def process(self, data: dict[str, str]) -> dict[str, str]:
        """Return employee data with non-destructive placeholder aliases added."""
        result = dict(data)

        for placeholder, rule in PLACEHOLDER_ALIASES.items():
            value = rule(result)
            if value is not None:
                self._set_missing(result, placeholder, value)

        self._logger.debug("Explicit placeholder aliases processed")
        return result

    def _set_missing(self, data: dict[str, str], key: str, value: str) -> None:
        if not self._has_value(data, key):
            data[key] = value

    def _has_value(self, data: dict[str, str], key: str) -> bool:
        return bool(str(data.get(key, "")).strip())
