"""DOCX placeholder extraction."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.text.paragraph import CT_P

from src.core.exceptions import RenderingError


@dataclass
class PlaceholderExtractor:
    """Finds placeholders with the <Field> format inside DOCX templates.

    The extractor reads Word XML paragraphs (`w:p`) from the document body and
    header/footer parts. For each paragraph it concatenates descendant `w:t`
    text nodes before applying the placeholder regular expression. This mirrors
    the renderer's split-run handling, so placeholders split across several
    runs are extracted as one logical value.
    """

    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
        init=False,
        repr=False,
    )
    _pattern: re.Pattern[str] = field(
        default_factory=lambda: re.compile(r"<([^<>\r\n]+)>"),
        init=False,
        repr=False,
    )

    def extract(self, docx_path: str | Path) -> set[str]:
        """Extract placeholder names from a DOCX file without angle brackets."""
        path = Path(docx_path)
        if not path.exists():
            raise RenderingError(f"DOCX template does not exist: {path}")

        try:
            document = Document(path)
        except Exception as error:
            raise RenderingError(f"Failed to open DOCX template: {path}") from error

        placeholders = self.extract_from_document(document)
        self._logger.debug("Extracted DOCX placeholders: %s", len(placeholders))
        return placeholders

    def extract_from_document(self, document: DocxDocument) -> set[str]:
        """Extract placeholder names from an opened python-docx document."""
        placeholders: set[str] = set()
        for paragraph in self.iter_paragraph_elements(document):
            text = self.paragraph_text(paragraph)
            placeholders.update(match.group(1) for match in self._pattern.finditer(text))
        return placeholders

    def iter_paragraph_elements(self, document: DocxDocument) -> Iterable[CT_P]:
        """Yield XML paragraph elements from the document body and headers/footers."""
        yielded: set[CT_P] = set()

        for paragraph in document.element.xpath(".//w:p"):
            yielded.add(paragraph)
            yield paragraph

        for section in document.sections:
            for container in (section.header, section.footer):
                for paragraph in container.paragraphs:
                    paragraph_element = paragraph._p
                    if paragraph_element in yielded:
                        continue
                    yielded.add(paragraph_element)
                    yield paragraph_element

        for related_part in document.part.related_parts.values():
            element = getattr(related_part, "element", None)
            if element is None:
                continue
            for paragraph in element.xpath(".//w:p"):
                if paragraph in yielded:
                    continue
                yielded.add(paragraph)
                yield paragraph

    def paragraph_text(self, paragraph: CT_P) -> str:
        """Return concatenated text from all text nodes inside a paragraph."""
        return "".join(node.text or "" for node in paragraph.xpath(".//w:t"))

    def placeholder_pattern(self) -> re.Pattern[str]:
        """Return the regular expression used to detect placeholders."""
        return self._pattern
