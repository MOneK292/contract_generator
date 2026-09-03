"""Pydantic schemas for contract generation requests."""

from pydantic import BaseModel


class ContractGenerationRequest(BaseModel):
    """Input data required to generate a contract."""

    project_id: str
    vacancy_id: str
    employee_text: str

