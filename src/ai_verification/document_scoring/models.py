"""Immutable models for deterministic document-priority scoring."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

DocumentScore = Annotated[float, Field(ge=0.0, le=100.0)]


class DocumentPriority(StrEnum):
    """Relative importance of a document type for the current assessment."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class TrafficLight(StrEnum):
    """Final procurement-review category."""

    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"


class DocumentScoreReason(StrEnum):
    """Stable machine-readable reasons contributing to a document score."""

    DOCUMENT_MISSING = "DOCUMENT_MISSING"
    NO_EVIDENCE = "NO_EVIDENCE"
    LOW_EVIDENCE_CONFIDENCE = "LOW_EVIDENCE_CONFIDENCE"
    COMPLIANCE_FAILED = "COMPLIANCE_FAILED"
    COMPLIANCE_MISSING = "COMPLIANCE_MISSING"
    COMPLIANCE_UNVERIFIABLE = "COMPLIANCE_UNVERIFIABLE"
    COMPLIANCE_WARNING = "COMPLIANCE_WARNING"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    VERIFICATION_UNAVAILABLE = "VERIFICATION_UNAVAILABLE"
    MATERIAL_FINDING = "MATERIAL_FINDING"
    EVIDENCE_QUALITY_DEGRADED = "EVIDENCE_QUALITY_DEGRADED"
    EVIDENCE_QUALITY_UNKNOWN = "EVIDENCE_QUALITY_UNKNOWN"
    UNKNOWN_DOCUMENT_TYPE = "UNKNOWN_DOCUMENT_TYPE"
    VERIFIED = "VERIFIED"
    NO_MATERIAL_ISSUES = "NO_MATERIAL_ISSUES"


class DocumentInput(BaseModel):
    """Minimal submitted-document metadata consumed by the scoring engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    document_type: str


class DocumentImportance(BaseModel):
    """Tender-configurable priority and aggregation weight for one type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    priority: DocumentPriority
    weight: float = Field(gt=0.0)


class DocumentScoreDetail(BaseModel):
    """Auditable score for one submitted or expected document type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str | None = None
    document_type: str
    source_document_types: tuple[str, ...] = ()
    priority: DocumentPriority
    weight: float = Field(gt=0.0)
    present: bool
    evidence_count: int = Field(ge=0)
    average_evidence_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    compliance_statuses: tuple[str, ...] = ()
    verification_statuses: tuple[str, ...] = ()
    finding_flag_ids: tuple[str, ...] = ()
    reasons: tuple[DocumentScoreReason, ...] = ()
    score: DocumentScore

    @field_validator("compliance_statuses", "verification_statuses", "finding_flag_ids", "reasons")
    @classmethod
    def _ordered_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class BidderDocumentScore(BaseModel):
    """Final weighted document score and traffic-light category."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bidder_id: str
    submission_id: str | None = None
    score: DocumentScore
    category: TrafficLight
    documents: tuple[DocumentScoreDetail, ...] = ()
    reason_codes: tuple[DocumentScoreReason, ...] = ()
    summary: str

    @property
    def is_green(self) -> bool:
        return self.category is TrafficLight.GREEN

    @property
    def is_yellow(self) -> bool:
        return self.category is TrafficLight.YELLOW

    @property
    def is_red(self) -> bool:
        return self.category is TrafficLight.RED


__all__ = [
    "BidderDocumentScore",
    "DocumentImportance",
    "DocumentInput",
    "DocumentPriority",
    "DocumentScore",
    "DocumentScoreDetail",
    "DocumentScoreReason",
    "TrafficLight",
]
