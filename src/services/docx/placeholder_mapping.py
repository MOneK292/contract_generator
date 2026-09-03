"""Placeholder mapping analysis for DOCX/DOCM templates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.processors.placeholder_aliases import PLACEHOLDER_ALIAS_SOURCES
from src.services.docx.placeholders import PlaceholderExtractor


@dataclass(frozen=True)
class PlaceholderMatch:
    """How a template placeholder can be populated."""

    placeholder: str
    source: str | None
    automatic: bool


@dataclass(frozen=True)
class TemplatePlaceholderMap:
    """Placeholder mapping report for one template."""

    template_name: str
    template_path: Path
    placeholders: tuple[str, ...]
    matches: tuple[PlaceholderMatch, ...]

    @property
    def unresolved(self) -> tuple[str, ...]:
        """Return placeholders that have no direct field or explicit alias rule."""
        return tuple(match.placeholder for match in self.matches if match.source is None)


class PlaceholderMappingBuilder:
    """Build explicit placeholder mapping reports for Word templates."""

    def __init__(self, extractor: PlaceholderExtractor | None = None) -> None:
        self.extractor = extractor or PlaceholderExtractor()

    def build_for_template(
        self,
        template_path: str | Path,
        *,
        template_name: str | None = None,
    ) -> TemplatePlaceholderMap:
        """Extract placeholders and map each one to direct input or an alias rule."""
        path = Path(template_path)
        placeholders = tuple(sorted(self.extractor.extract(path)))
        matches = tuple(self._match(placeholder) for placeholder in placeholders)
        return TemplatePlaceholderMap(
            template_name=template_name or path.name,
            template_path=path,
            placeholders=placeholders,
            matches=matches,
        )

    def _match(self, placeholder: str) -> PlaceholderMatch:
        if placeholder in PLACEHOLDER_ALIAS_SOURCES:
            return PlaceholderMatch(
                placeholder=placeholder,
                source=" + ".join(PLACEHOLDER_ALIAS_SOURCES[placeholder]),
                automatic=True,
            )
        return PlaceholderMatch(
            placeholder=placeholder,
            source=placeholder,
            automatic=False,
        )
