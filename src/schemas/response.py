"""Pydantic schemas for contract generation responses."""

from pathlib import Path

from pydantic import BaseModel, Field


class ContractGenerationResponse(BaseModel):
    """Result returned by the contract engine."""

    pdf_path: Path
    warnings: list[str] = Field(default_factory=list)

