"""DOCX services."""

from src.services.docx.compat import patch_python_docx_docm_support

patch_python_docx_docm_support()

from src.services.docx.placeholders import PlaceholderExtractor
from src.services.docx.renderer import DocxRenderer, RenderResult

__all__ = ["DocxRenderer", "PlaceholderExtractor", "RenderResult"]
