"""Vacancy model."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Vacancy:
    """Vacancy available inside a project."""

    id: str
    name: str
    template_id: str

