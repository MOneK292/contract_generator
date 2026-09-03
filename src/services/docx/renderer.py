"""DOCX rendering service."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.text.paragraph import CT_P

from src.core.exceptions import RenderingError
from src.services.docx.placeholders import PlaceholderExtractor


class RenderResult(NamedTuple):
    """Result of rendering a DOCX template."""

    success: bool
    unresolved_placeholders: list[str]


@dataclass
class DocxRenderer:
    """Replaces placeholders in a DOCX template with prepared data.

    The renderer works at the Word XML paragraph level. For each paragraph it
    reads all descendant `w:t` text nodes, builds one logical text string, finds
    placeholders with the `<Field>` format, and writes updated text back to the
    same text nodes.

    This is important for split-runs: Word may store `<Field>` as `<Fi`, `el`,
    `d>` in separate runs. The renderer maps every character in the logical
    paragraph text back to its original text node. Text outside replaced
    placeholders remains in the same nodes, so its run formatting is preserved.
    When a placeholder spans multiple runs, the replacement value is written to
    the node containing the first placeholder character; the replacement
    therefore inherits that first run's formatting.
    """

    _extractor: PlaceholderExtractor = field(default_factory=PlaceholderExtractor)
    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(__name__),
        init=False,
        repr=False,
    )

    def render(
        self,
        template_path: str | Path,
        data: dict[str, object],
        output_path: str | Path,
    ) -> RenderResult:
        """Render a DOCX file from a template into `output_path`.

        Unknown placeholders are left unchanged. After saving, the rendered file
        is scanned again and the remaining placeholder names are returned in
        `RenderResult.unresolved_placeholders`.
        """
        template = Path(template_path)
        output = Path(output_path)

        if not template.exists():
            raise RenderingError(f"DOCX template does not exist: {template}")

        try:
            document = Document(template)
        except Exception as error:
            raise RenderingError(f"Failed to open DOCX template: {template}") from error

        replacements = self._render_document(document, data)
        output.parent.mkdir(parents=True, exist_ok=True)

        try:
            document.save(output)
        except Exception as error:
            raise RenderingError(f"Failed to save rendered DOCX: {output}") from error

        unresolved = sorted(self._extractor.extract(output))
        self._logger.info(
            "Rendered DOCX: %s placeholders replaced, %s unresolved",
            replacements,
            len(unresolved),
        )
        return RenderResult(success=True, unresolved_placeholders=unresolved)

    def _render_document(self, document: DocxDocument, data: dict[str, object]) -> int:
        replacements = 0
        for paragraph in self._extractor.iter_paragraph_elements(document):
            replacements += self._replace_paragraph_placeholders(paragraph, data)
        return replacements

    def _replace_paragraph_placeholders(
        self,
        paragraph: CT_P,
        data: dict[str, object],
    ) -> int:
        text_nodes = paragraph.xpath(".//w:t")
        if not text_nodes:
            return 0

        node_texts = [node.text or "" for node in text_nodes]
        original_text = "".join(node_texts)
        pattern = self._extractor.placeholder_pattern()

        matches = list(pattern.finditer(original_text))
        if not matches:
            return 0

        owners: list[int] = []
        for node_index, text in enumerate(node_texts):
            owners.extend([node_index] * len(text))

        rendered_node_texts = ["" for _ in text_nodes]
        cursor = 0
        replacements = 0

        for match in matches:
            self._append_original_text(
                original_text,
                owners,
                rendered_node_texts,
                cursor,
                match.start(),
            )

            key = match.group(1)
            if key in data:
                first_node_index = owners[match.start()]
                rendered_node_texts[first_node_index] += str(data[key])
                replacements += 1
            else:
                self._append_original_text(
                    original_text,
                    owners,
                    rendered_node_texts,
                    match.start(),
                    match.end(),
                )

            cursor = match.end()

        self._append_original_text(
            original_text,
            owners,
            rendered_node_texts,
            cursor,
            len(original_text),
        )

        if replacements == 0:
            return 0

        for node, text in zip(text_nodes, rendered_node_texts):
            node.text = text

        return replacements

    def _append_original_text(
        self,
        original_text: str,
        owners: list[int],
        rendered_node_texts: list[str],
        start: int,
        end: int,
    ) -> None:
        for position in range(start, end):
            rendered_node_texts[owners[position]] += original_text[position]
