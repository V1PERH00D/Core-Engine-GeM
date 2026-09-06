"""Risk-signal extraction from already-produced engine outputs.

The extractor consumes the existing artefacts produced elsewhere in
the project and produces one RiskSignal per relevant input artefact.
It is deterministic and non-mutating.

Confidence handling
-------------------

The signal's confidence is taken from the upstream artefact when one
is present. For compliance results, confidence is derived
deterministically from the requirement status.
"""

from __future__ import annotations

from typing import Iterable

from compliance_engine.flags import FlagSeverity, get_flag_definition
from compliance_engine.models import ComplianceResult, IdentityFinding
from compliance_engine.models.result import ComplianceStatus
from compliance_engine.models.verification import Verification, VerificationStatus

from ai_verification.cross_bidder.trace import SimilarityTrace
from ai_verification.evidence_quality import (
    EvidenceQualityAssessment,
    QualityState,
)
from ai_verification.models.contracts import VerificationFinding

from .correlation import (
    correlation_key_for_evidence_quality,
    correlation_key_for_verification_availability,
    correlation_key_from_identity_finding,
    correlation_key_from_similarity_trace,
    correlation_key_from_verification_finding,
)
from .models import CorrelationKey, ReasonCode, RiskCategory, RiskSignal
from .severity import (
    normalize_severity,
    severity_weight,
)


_COMPLIANCE_STATUS_CONFIDENCE: dict[ComplianceStatus, float] = {
    ComplianceStatus.PASS: 1.0,
    ComplianceStatus.FAIL: 1.0,
    ComplianceStatus.WARNING: 0.9,
    ComplianceStatus.MISSING: 0.0,
    ComplianceStatus.UNVERIFIABLE: 0.0,
    ComplianceStatus.NOT_APPLICABLE: 0.0,
    ComplianceStatus.NOT_CHECKED: 0.0,
}


def _confidence_from_status(status: ComplianceStatus) -> float:
    return _COMPLIANCE_STATUS_CONFIDENCE.get(status, 0.0)


_COMPLIANCE_RISK_STATUSES: frozenset[ComplianceStatus] = frozenset({
    ComplianceStatus.FAIL,
    ComplianceStatus.WARNING,
    ComplianceStatus.MISSING,
})


def _severity_for_compliance_result(
    result: ComplianceResult,
) -> str | None:
    """Determine the canonical severity string for a ComplianceResult."""

    if result.flags:
        try:
            definition = get_flag_definition(result.flags[0])
            return definition.severity.value
        except KeyError:
            pass
    if result.status is ComplianceStatus.FAIL:
        return FlagSeverity.HIGH.value
    if result.status is ComplianceStatus.WARNING:
        return FlagSeverity.MEDIUM.value
    if result.status is ComplianceStatus.MISSING:
        return FlagSeverity.MEDIUM.value
    return FlagSeverity.INFO.value


def _reason_code_for_compliance(status: ComplianceStatus) -> str:
    if status is ComplianceStatus.FAIL:
        return ReasonCode.STRONGEST_HIGH_SEVERITY.value
    if status is ComplianceStatus.WARNING:
        return ReasonCode.STRONGEST_MEDIUM_SEVERITY.value
    if status is ComplianceStatus.MISSING:
        return ReasonCode.STRONGEST_MEDIUM_SEVERITY.value
    return ReasonCode.STRONGEST_INFO_SEVERITY.value

def signal_from_compliance_result(
    bidder_id: str,
    result: ComplianceResult,
) -> RiskSignal | None:
    """Convert one ComplianceResult into a RiskSignal.

    Returns None for statuses that do not represent a risk
    contribution (PASS, NOT_APPLICABLE, UNVERIFIABLE, NOT_CHECKED).
    """

    if result.status not in _COMPLIANCE_RISK_STATUSES:
        return None

    severity_str: str | None = _severity_for_compliance_result(result)
    severity_enum = (
        normalize_severity(severity_str) if severity_str else None
    )
    weight = severity_weight(severity_enum) if severity_enum else 0.60
    confidence = _confidence_from_status(result.status)

    evidence_ids = tuple(
        sorted({*result.evidence_refs, result.requirement_id})
    )
    verification_ids = tuple(sorted(set(result.verification_refs)))
    flag_id: str | None = result.flags[0] if result.flags else None

    correlation = CorrelationKey(
        category=RiskCategory.COMPLIANCE,
        primary_bidder_id=bidder_id,
        flag_id=flag_id,
        verification_ids=verification_ids,
        evidence_ids=evidence_ids,
        document_ids=(),
        related_bidder_ids=(),
    )

    is_actionable = result.status in (
        ComplianceStatus.FAIL,
        ComplianceStatus.WARNING,
    )

    human_reason = (
        f"Compliance requirement '{result.requirement_id}' "
        f"evaluated to {result.status.value}"
    )
    if flag_id:
        human_reason += f" (flag {flag_id})"

    return RiskSignal(
        bidder_id=bidder_id,
        signal_id=f"compliance:{bidder_id}:{result.requirement_id}",
        correlation_key=correlation,
        category=RiskCategory.COMPLIANCE,
        severity=severity_str or FlagSeverity.MEDIUM.value,
        score=weight,
        confidence=confidence,
        is_actionable=is_actionable,
        finding_refs=(),
        verification_refs=verification_ids,
        evidence_refs=evidence_ids,
        document_refs=(),
        related_bidder_ids=(),
        reason_code=_reason_code_for_compliance(result.status),
        human_reason=human_reason,
        provenance=("compliance",),
    )


_AVAILABILITY_STATUSES: frozenset[VerificationStatus] = frozenset({
    VerificationStatus.UNAVAILABLE,
    VerificationStatus.ERROR,
    VerificationStatus.NOT_FOUND,
})


_CRITICAL_CAPABILITIES: frozenset[str] = frozenset({
    "GST / GSTN",
    "PAN / Income Tax",
    "Bidder Identity",
})


def availability_signal_from_verifications(
    bidder_id: str,
    verifications: Iterable[Verification],
) -> RiskSignal | None:
    """Build a single availability signal when at least one
    verification is unavailable / error / not-found.

    Returns None when every verification is verified or inactive.
    """

    unavailable_records = [
        v for v in verifications if v.status in _AVAILABILITY_STATUSES
    ]
    if not unavailable_records:
        return None

    correlation = correlation_key_for_verification_availability(
        bidder_id, unavailable_records
    )

    has_critical = any(
        v.capability in _CRITICAL_CAPABILITIES for v in unavailable_records
    )
    severity = (
        FlagSeverity.HIGH.value if has_critical else FlagSeverity.MEDIUM.value
    )
    weight = severity_weight(
        FlagSeverity.HIGH if has_critical else FlagSeverity.MEDIUM
    )

    return RiskSignal(
        bidder_id=bidder_id,
        signal_id=f"availability:{bidder_id}",
        correlation_key=correlation,
        category=RiskCategory.VERIFICATION_AVAILABILITY,
        severity=severity,
        score=weight,
        confidence=1.0,
        is_actionable=False,
        finding_refs=(),
        verification_refs=correlation.verification_ids,
        evidence_refs=correlation.evidence_ids,
        document_refs=correlation.document_ids,
        related_bidder_ids=(),
        reason_code=(
            ReasonCode.CRITICAL_VERIFICATIONS_UNAVAILABLE.value
            if has_critical
            else ReasonCode.NO_VERIFICATIONS_PRESENT.value
        ),
        human_reason=(
            f"{len(unavailable_records)} verification(s) unavailable"
        ),
        provenance=("verification_availability",),
    )


def signal_from_identity_finding(
    bidder_id: str,
    finding: IdentityFinding,
) -> RiskSignal | None:
    """Convert one IdentityFinding into a RiskSignal."""

    severity_enum = _severity_for_flag_id(finding.flag_id)
    weight = severity_weight(severity_enum)
    confidence = 0.9
    correlation = correlation_key_from_identity_finding(bidder_id, finding)

    human_reason = (
        f"Cross-source identity mismatch between "
        f"{finding.left_document_id} and {finding.right_document_id}"
    )

    return RiskSignal(
        bidder_id=bidder_id,
        signal_id=(
            f"identity:{bidder_id}:{finding.left_document_id}"
            f":{finding.right_document_id}"
        ),
        correlation_key=correlation,
        category=RiskCategory.IDENTITY,
        severity=severity_enum.value,
        score=weight,
        confidence=confidence,
        is_actionable=True,
        finding_refs=(),
        verification_refs=(),
        evidence_refs=tuple(sorted(set(finding.evidence_refs))),
        document_refs=correlation.document_ids,
        related_bidder_ids=(),
        reason_code=_reason_code_for_severity(severity_enum),
        human_reason=human_reason,
        provenance=("identity",),
    )


def _severity_for_flag_id(
    flag_id: str | None,
) -> FlagSeverity | None:
    if not flag_id:
        return None
    try:
        definition = get_flag_definition(flag_id)
    except KeyError:
        return None
    return definition.severity


def _reason_code_for_severity(severity: FlagSeverity | None) -> str:
    if severity is None:
        return ReasonCode.STRONGEST_INFO_SEVERITY.value
    if severity is FlagSeverity.CRITICAL:
        return ReasonCode.STRONGEST_CRITICAL_SEVERITY.value
    if severity is FlagSeverity.HIGH:
        return ReasonCode.STRONGEST_HIGH_SEVERITY.value
    if severity is FlagSeverity.MEDIUM:
        return ReasonCode.STRONGEST_MEDIUM_SEVERITY.value
    if severity is FlagSeverity.LOW:
        return ReasonCode.STRONGEST_LOW_SEVERITY.value
    return ReasonCode.STRONGEST_INFO_SEVERITY.value


def signal_from_verification_finding(
    bidder_id: str,
    finding: VerificationFinding,
) -> RiskSignal | None:
    """Convert one VerificationFinding into a RiskSignal."""

    severity_enum = _severity_for_flag_id(finding.flag_id)
    if severity_enum is None:
        return None
    weight = severity_weight(severity_enum)

    return RiskSignal(
        bidder_id=bidder_id,
        signal_id=f"finding:{finding.finding_id}",
        correlation_key=correlation_key_from_verification_finding(
            bidder_id, finding
        ),
        category=_category_for_finding(finding),
        severity=severity_enum.value,
        score=weight,
        confidence=float(finding.confidence),
        is_actionable=True,
        finding_refs=(finding.finding_id,),
        verification_refs=tuple(sorted(set(finding.verification_refs))),
        evidence_refs=tuple(sorted(set(finding.evidence_refs))),
        document_refs=(),
        related_bidder_ids=tuple(sorted(set(finding.related_bidder_ids))),
        reason_code=_reason_code_for_severity(severity_enum),
        human_reason=finding.explanation,
        provenance=("ai_verification",),
    )


def signal_from_cross_bidder_finding(
    bidder_id: str,
    finding: VerificationFinding,
    trace: SimilarityTrace,
) -> RiskSignal | None:
    """Convert a cross-bidder VerificationFinding + SimilarityTrace into
    a RiskSignal."""

    severity_enum = _severity_for_flag_id(finding.flag_id)
    if severity_enum is None:
        return None
    weight = severity_weight(severity_enum)

    correlation = correlation_key_from_similarity_trace(
        bidder_id, finding, trace
    )

    return RiskSignal(
        bidder_id=bidder_id,
        signal_id=f"reuse:{finding.finding_id}:{bidder_id}",
        correlation_key=correlation,
        category=RiskCategory.DOCUMENT_REUSE,
        severity=severity_enum.value,
        score=weight,
        confidence=float(finding.confidence),
        is_actionable=True,
        finding_refs=(finding.finding_id,),
        verification_refs=tuple(sorted(set(finding.verification_refs))),
        evidence_refs=tuple(sorted(set(finding.evidence_refs))),
        document_refs=correlation.document_ids,
        related_bidder_ids=correlation.related_bidder_ids,
        reason_code=_reason_code_for_severity(severity_enum),
        human_reason=finding.explanation,
        provenance=("cross_bidder",),
    )


def signal_from_evidence_quality(
    bidder_id: str,
    assessments: Iterable[EvidenceQualityAssessment],
) -> RiskSignal | None:
    """Convert evidence-quality assessments into a RiskSignal.

    Returns None when every assessment is GOOD.
    """

    assessment_list = list(assessments)
    if not assessment_list:
        return None
    if all(a.state is QualityState.GOOD for a in assessment_list):
        return None

    has_unknown = any(
        a.state is QualityState.UNKNOWN for a in assessment_list
    )
    severity_enum = FlagSeverity.HIGH
    weight = severity_weight(severity_enum)

    correlation = correlation_key_for_evidence_quality(
        bidder_id, assessment_list
    )

    reason_code = (
        ReasonCode.EVIDENCE_QUALITY_UNKNOWN.value
        if has_unknown
        else ReasonCode.EVIDENCE_QUALITY_DEGRADED.value
    )

    return RiskSignal(
        bidder_id=bidder_id,
        signal_id=f"quality:{bidder_id}",
        correlation_key=correlation,
        category=RiskCategory.EVIDENCE_QUALITY,
        severity=FlagSeverity.HIGH.value,
        score=weight,
        confidence=1.0,
        is_actionable=False,
        finding_refs=(),
        verification_refs=(),
        evidence_refs=correlation.evidence_ids,
        document_refs=correlation.document_ids,
        related_bidder_ids=(),
        reason_code=reason_code,
        human_reason=(
            f"{len(assessment_list)} evidence-quality assessment(s); "
            f"state={'UNKNOWN' if has_unknown else 'DEGRADED'}"
        ),
        provenance=("evidence_quality",),
    )


def _category_for_finding(finding: VerificationFinding) -> RiskCategory:
    """Map a VerificationFinding's flag_id to a RiskCategory."""

    from .correlation import _category_for_flag

    return _category_for_flag(finding.flag_id)


__all__ = [
    "availability_signal_from_verifications",
    "signal_from_compliance_result",
    "signal_from_cross_bidder_finding",
    "signal_from_evidence_quality",
    "signal_from_identity_finding",
    "signal_from_verification_finding",
]
