"""Typed Pydantic models for the bidder-level risk engine."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


# Shared bounded numeric alias.
BoundedUnitScore = Annotated[float, Field(ge=0.0, le=1.0)]


class RiskCategory(StrEnum):
    """Controlled taxonomy of risk signal categories."""

    COMPLIANCE = "COMPLIANCE"
    IDENTITY = "IDENTITY"
    DOCUMENT_REUSE = "DOCUMENT_REUSE"
    EVIDENCE_QUALITY = "EVIDENCE_QUALITY"
    VERIFICATION_AVAILABILITY = "VERIFICATION_AVAILABILITY"


class RiskState(StrEnum):
    """Final aggregate bidder risk state."""

    CLEAR = "CLEAR"
    REVIEW = "REVIEW"
    HIGH_RISK = "HIGH_RISK"
    INDETERMINATE = "INDETERMINATE"


class EvidenceState(StrEnum):
    """Per-bucket state of the evidence base."""

    VERIFIED = "VERIFIED"
    INSUFFICIENT = "INSUFFICIENT"
    UNAVAILABLE = "UNAVAILABLE"


class ReasonCode(StrEnum):
    """Deterministic reason codes used in the explanation."""

    STRONGEST_HIGH_SEVERITY = "STRONGEST_HIGH_SEVERITY"
    STRONGEST_MEDIUM_SEVERITY = "STRONGEST_MEDIUM_SEVERITY"
    STRONGEST_LOW_SEVERITY = "STRONGEST_LOW_SEVERITY"
    STRONGEST_INFO_SEVERITY = "STRONGEST_INFO_SEVERITY"
    STRONGEST_CRITICAL_SEVERITY = "STRONGEST_CRITICAL_SEVERITY"

    INDEPENDENT_SUPPORTING_SIGNALS = "INDEPENDENT_SUPPORTING_SIGNALS"
    CORRELATED_SIGNALS_DEDUPLICATED = "CORRELATED_SIGNALS_DEDUPLICATED"
    NO_RISK_SIGNALS_PRESENT = "NO_RISK_SIGNALS_PRESENT"

    CRITICAL_VERIFICATIONS_UNAVAILABLE = "CRITICAL_VERIFICATIONS_UNAVAILABLE"
    NO_VERIFICATIONS_PRESENT = "NO_VERIFICATIONS_PRESENT"
    EVIDENCE_QUALITY_DEGRADED = "EVIDENCE_QUALITY_DEGRADED"
    EVIDENCE_QUALITY_UNKNOWN = "EVIDENCE_QUALITY_UNKNOWN"

    INDETERMINATE_OVERRIDES_HIGH_RISK = "INDETERMINATE_OVERRIDES_HIGH_RISK"


class CorrelationKey(BaseModel):
    """Deterministic identity of one underlying risk-contributing event.

    Two signals with the same :class:`CorrelationKey` describe the
    *same* underlying event and must be deduplicated into a single
    contribution.

    The key intentionally excludes the finding ID: two detectors can
    independently emit findings for the same underlying event with
    different IDs, and the risk engine must treat them as one
    contribution.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: RiskCategory
    primary_bidder_id: str
    flag_id: str | None = None
    verification_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    related_bidder_ids: tuple[str, ...] = ()


class RiskSignal(BaseModel):
    """One risk-relevant signal attached to a single bidder."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bidder_id: str
    signal_id: str
    correlation_key: CorrelationKey
    category: RiskCategory
    severity: str
    score: BoundedUnitScore
    confidence: BoundedUnitScore
    is_actionable: bool
    finding_refs: tuple[str, ...] = ()
    verification_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    document_refs: tuple[str, ...] = ()
    related_bidder_ids: tuple[str, ...] = ()
    reason_code: str
    human_reason: str
    provenance: tuple[str, ...] = ()


class EvidenceAvailability(BaseModel):
    """Per-bucket summary of evidence availability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verified_evidence_count: int = 0
    insufficient_evidence_count: int = 0
    unavailable_evidence_count: int = 0
    verified_verification_count: int = 0
    unavailable_verification_count: int = 0
    critical_required_capabilities_present: bool = True
    overall_state: EvidenceState = EvidenceState.VERIFIED


class BidderRiskAssessment(BaseModel):
    """Deterministic aggregate risk picture for one bidder."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bidder_id: str
    risk_state: RiskState
    aggregate_score: BoundedUnitScore
    signals: tuple[RiskSignal, ...] = ()
    strongest_signal: RiskSignal | None = None
    supporting_signals: tuple[RiskSignal, ...] = ()
    deduplicated_signal_count: int = 0
    evidence_availability: EvidenceAvailability = Field(
        default_factory=EvidenceAvailability
    )
    reason_codes: tuple[str, ...] = ()
    summary: str = ""


__all__ = [
    "BidderRiskAssessment",
    "BoundedUnitScore",
    "CorrelationKey",
    "EvidenceAvailability",
    "EvidenceState",
    "ReasonCode",
    "RiskCategory",
    "RiskSignal",
    "RiskState",
]