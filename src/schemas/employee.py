"""Pydantic schemas for employee input data."""

from pydantic import BaseModel, Field


class EmployeeSchema(BaseModel):
    """Dynamic employee fields parsed from user text."""

    fields: dict[str, str] = Field(default_factory=dict)

