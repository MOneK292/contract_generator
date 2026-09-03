"""FIO-derived fields processor."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.processors.base import FieldProcessor


@dataclass
class FioProcessor(FieldProcessor):
    """Adds surname, name, and patronymic fields from full name."""

    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
        init=False,
        repr=False,
    )

    def process(self, data: dict[str, str]) -> dict[str, str]:
        """Add `Ф`, `И`, and `О` fields when `ФИО` is present."""
        result = dict(data)
        full_name = result.get("ФИО")
        if not full_name:
            self._logger.debug("Skipping FIO processing: field is absent")
            return result

        parts = full_name.split()
        if len(parts) >= 1:
            result["Ф"] = parts[0]
        if len(parts) >= 2:
            result["И"] = parts[1]
        if len(parts) >= 3:
            result["О"] = " ".join(parts[2:])

        self._logger.debug("Processed FIO field")
        return result
