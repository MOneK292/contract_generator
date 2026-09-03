"""Template model."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Template:
    """DOCX template metadata."""

    id: str
    name: str
    google_drive_file_id: str

