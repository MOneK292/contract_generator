"""Application-specific exceptions."""


class ContractGeneratorError(Exception):
    """Base exception for the contract generator."""


class ConfigurationError(ContractGeneratorError):
    """Raised when configuration is missing or invalid."""


class TemplateNotFoundError(ContractGeneratorError):
    """Raised when a template cannot be found."""


class RenderingError(ContractGeneratorError):
    """Raised when DOCX rendering fails."""


class PdfConversionError(ContractGeneratorError):
    """Raised when PDF conversion fails."""

