"""Normalized tender requirements."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Applicability(StrEnum):
    """Whether a requirement applies to the current bidder and tender."""

    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class Requirement(BaseModel):
    """A tender-derived requirement ready for later rule evaluation."""

    requirement_id: str
    capability: str
    description: str
    mandatory: bool
    applicability: Applicability
    operator: str | None = None
    expected: Any = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    required_evidence: list[str] = Field(default_factory=list)
    required_source: str | None = None
    rule_id: str
