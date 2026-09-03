"""Compatibility patches for python-docx Word package opening."""

from __future__ import annotations

import os
from typing import IO, cast

import docx
import docx.api
from docx.document import Document as DocumentObject
from docx.opc.constants import CONTENT_TYPE as CT
from docx.opc.part import PartFactory
from docx.package import Package
from docx.parts.document import DocumentPart


DOCM_DOCUMENT_MAIN = "application/vnd.ms-word.document.macroEnabled.main+xml"
SUPPORTED_DOCUMENT_MAIN_CONTENT_TYPES = (
    CT.WML_DOCUMENT_MAIN,
    DOCM_DOCUMENT_MAIN,
)


def patch_python_docx_docm_support() -> None:
    """Allow python-docx to open DOCM packages as Word documents."""
    PartFactory.part_type_for[DOCM_DOCUMENT_MAIN] = DocumentPart
    docx.api.Document = _document_with_docm_support
    docx.Document = _document_with_docm_support


def _document_with_docm_support(docx_path: str | IO[bytes] | None = None) -> DocumentObject:
    document_path = _default_docx_path() if docx_path is None else docx_path
    document_part = cast("DocumentPart", Package.open(document_path).main_document_part)
    if document_part.content_type not in SUPPORTED_DOCUMENT_MAIN_CONTENT_TYPES:
        message = "file '%s' is not a Word file, content type is '%s'"
        raise ValueError(message % (document_path, document_part.content_type))
    return document_part.document


def _default_docx_path() -> str:
    package_dir = os.path.split(docx.__file__)[0]
    return os.path.join(package_dir, "templates", "default.docx")
