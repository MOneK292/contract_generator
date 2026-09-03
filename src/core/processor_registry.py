"""Processor registration and execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.processors.base import FieldProcessor


@dataclass
class ProcessorRegistry:
    """Stores processors and applies them to employee data."""

    _processors: list[FieldProcessor] = field(default_factory=list, init=False)
    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
        init=False,
        repr=False,
    )

    def register(self, processor: FieldProcessor) -> None:
        """Register a processor instance."""
        if not callable(getattr(processor, "process", None)):
            raise TypeError("Processor must provide a callable `process` method")

        self._processors.append(processor)
        self._logger.debug("Registered processor: %s", processor.__class__.__name__)

    def process(self, data: dict[str, str]) -> dict[str, str]:
        """Apply registered processors to data in registration order."""
        result = dict(data)

        for processor in self._processors:
            self._logger.debug("Running processor: %s", processor.__class__.__name__)
            result = processor.process(result)

        return result
