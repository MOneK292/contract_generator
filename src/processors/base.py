"""Base processor contract."""

from __future__ import annotations

from abc import ABC, abstractmethod


class FieldProcessor(ABC):
    """Adds or normalizes fields in employee data."""

    @abstractmethod
    def process(self, data: dict[str, str]) -> dict[str, str]:
        """Process employee data and return updated data."""
        raise NotImplementedError
