"""Project model."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Project:
    """Contract project available for user selection."""

    id: str
    name: str

