"""Engine-produced compliance outcomes."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ComplianceStatus(StrEnum):
    """Result of evaluating one requirement. Distinct from source-query status."""

    PASS = "PASS"
    FAIL = "FAIL"
    MISSING = "MISSING"
    UNVERIFIABLE = "UNVERIFIABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    WARNING = "WARNING"
    NOT_CHECKED = "NOT_CHECKED"


class ComplianceResult(BaseModel):
    """Explainable outcome for a single requirement."""

    requirement_id: str
    capability: str
    status: ComplianceStatus
    reason: str
    expected: Any = None
    actual: Any = None
    evidence_refs: list[str] = Field(default_factory=list)
    verification_refs: list[str] = Field(default_factory=list)
    flags: list[str] = Field(
        default_factory=list,
        description="Machine-readable flag IDs from the verification flag registry.",
    )
    rule_id: str
