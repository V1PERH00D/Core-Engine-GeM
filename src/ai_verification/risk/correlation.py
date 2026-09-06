"""Deterministic correlation keys for risk-signal deduplication.

The correlation key uniquely identifies the underlying event a risk
signal represents. Two signals with the same correlation key are
deduplicated into a single contribution.

Algorithm
---------

The correlation key is built from only identifiers that already exist
on the source artefacts:

* bidder ID,
* risk category,
* finding ID (when the signal comes from a VerificationFinding),
* canonical flag ID (when present),
* verification IDs (sorted, deduplicated),
* evidence IDs (sorted, deduplicated),
* document IDs (sorted, deduplicated),
* related bidder IDs (sorted, deduplicated).

The correlation key never invents an identifier. When a field is
absent, it contributes nothing.
"""

from __future__ import annotations

from typing import Iterable

from compliance_engine.models import ComplianceResult, IdentityFinding
from compliance_engine.models.verification import Verification

from ai_verification.cross_bidder.trace import SimilarityTrace
from ai_verification.models.contracts import VerificationFinding

from .models import CorrelationKey, RiskCategory


def _sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    """Return the sorted unique tuple of ``values``.

    Empty strings and ``None``-likes are filtered out, so the output
    is always deterministic.
    """

    cleaned = sorted({v for v in values if v})
    return tuple(cleaned)


def _refs(records: Iterable[object], attr: str) -> tuple[str, ...]:
    """Return the sorted unique values of ``attr`` over ``records``."""

    values: list[str] = []
    for record in records:
        value = getattr(record, attr, None)
        if value is None:
            continue
        if isinstance(value, str) and value:
            values.append(value)
        elif isinstance(value, list):
            values.extend(v for v in value if isinstance(v, str) and v)
    return _sorted_unique(values)


def correlation_key_from_compliance_result(
    bidder_id: str,
    result: ComplianceResult,
) -> CorrelationKey:
    """Build a correlation key for one ComplianceResult."""

    evidence_ids: tuple[str, ...] = tuple(
        sorted({*result.evidence_refs, result.requirement_id})
    )
    flag_id: str | None = result.flags[0] if result.flags else None
    return CorrelationKey(
        category=RiskCategory.COMPLIANCE,
        primary_bidder_id=bidder_id,
        flag_id=flag_id,
        verification_ids=tuple(sorted(set(result.verification_refs))),
        evidence_ids=evidence_ids,
        document_ids=(),
        related_bidder_ids=(),
    )


def correlation_key_from_verification_finding(
    bidder_id: str,
    finding: VerificationFinding,
) -> CorrelationKey:
    """Build a correlation key for one VerificationFinding."""

    return CorrelationKey(
        category=_category_for_flag(finding.flag_id),
        primary_bidder_id=bidder_id,
        flag_id=finding.flag_id,
        verification_ids=tuple(sorted(set(finding.verification_refs))),
        evidence_ids=tuple(sorted(set(finding.evidence_refs))),
        document_ids=(),
        related_bidder_ids=tuple(sorted(set(finding.related_bidder_ids))),
    )


def correlation_key_from_identity_finding(
    bidder_id: str,
    finding: IdentityFinding,
) -> CorrelationKey:
    """Build a correlation key for one IdentityFinding."""

    document_ids = tuple(
        sorted({finding.left_document_id, finding.right_document_id})
    )
    evidence_ids = tuple(sorted(set(finding.evidence_refs)))
    return CorrelationKey(
        category=RiskCategory.IDENTITY,
        primary_bidder_id=bidder_id,
        flag_id=finding.flag_id,
        verification_ids=(),
        evidence_ids=evidence_ids,
        document_ids=document_ids,
        related_bidder_ids=(),
    )


def correlation_key_from_similarity_trace(
    bidder_id: str,
    finding: VerificationFinding,
    trace: SimilarityTrace,
) -> CorrelationKey:
    """Build a correlation key for a cross-bidder finding backed by a
    SimilarityTrace."""

    document_ids = tuple(
        sorted({trace.left_document_id, trace.right_document_id})
    )
    related_bidders = tuple(
        sorted(
            set(finding.related_bidder_ids) | {trace.right_bidder_id}
        )
    )
    return CorrelationKey(
        category=RiskCategory.DOCUMENT_REUSE,
        primary_bidder_id=bidder_id,
        flag_id=finding.flag_id,
        verification_ids=tuple(sorted(set(finding.verification_refs))),
        evidence_ids=tuple(sorted(set(finding.evidence_refs))),
        document_ids=document_ids,
        related_bidder_ids=related_bidders,
    )


def correlation_key_for_verification_availability(
    bidder_id: str,
    verifications: Iterable[Verification],
) -> CorrelationKey:
    """Build a correlation key for the verification-availability signal."""

    v_records = list(verifications)
    return CorrelationKey(
        category=RiskCategory.VERIFICATION_AVAILABILITY,
        primary_bidder_id=bidder_id,
        flag_id=None,
        verification_ids=tuple(sorted({r.verification_id for r in v_records})),
        evidence_ids=_refs(v_records, "evidence_id"),
        document_ids=_refs(v_records, "document_id"),
        related_bidder_ids=(),
    )


def correlation_key_for_evidence_quality(
    bidder_id: str,
    quality_assessments: Iterable[object],
) -> CorrelationKey:
    """Build a correlation key for the evidence-quality signal."""

    assessment_list = list(quality_assessments)
    document_ids: list[str] = []
    evidence_ids: list[str] = []
    for assessment in assessment_list:
        for attr in ("document_id", "left_document_id", "right_document_id"):
            value = getattr(assessment, attr, None)
            if isinstance(value, str) and value:
                document_ids.append(value)
        for attr in ("evidence_id", "left_evidence_id", "right_evidence_id"):
            value = getattr(assessment, attr, None)
            if isinstance(value, str) and value:
                evidence_ids.append(value)
    return CorrelationKey(
        category=RiskCategory.EVIDENCE_QUALITY,
        primary_bidder_id=bidder_id,
        flag_id=None,
        verification_ids=(),
        evidence_ids=_sorted_unique(evidence_ids),
        document_ids=_sorted_unique(document_ids),
        related_bidder_ids=(),
    )

# Flag-id -> risk-category mapping.
# The categories reflect the *kind* of evidence the flag points to,
# not the policy the flag implies.

_DOCUMENT_REUSE_FLAGS: frozenset[str] = frozenset({
    "CROSS_BIDDER_DOCUMENT_REUSED",
    "CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE",
    "ADDRESS_SHARING_SUSPICIOUS",
    "EXACT_DUPLICATE_BIDDER_DETECTED",
    "NEAR_DUPLICATE_BIDDER_DETECTED",
    "SUSPICIOUS_BIDDER_RELATIONSHIP_DETECTED",
    "DIRECTOR_SHARING_SUSPICIOUS",
    "FINANCIAL_PROFILE_ANOMALY",
    "CROSS_BIDDER_VERIFICATION_INCOMPLETE",
})


_IDENTITY_FLAGS: frozenset[str] = frozenset({
    "CROSS_SOURCE_IDENTITY_MISMATCH",
    "BIDDER_NAME_MISMATCH",
    "ADDRESS_MISMATCH",
    "GST_IDENTITY_MISMATCH",
    "UDYAM_IDENTITY_MISMATCH",
    "STARTUP_IDENTITY_MISMATCH",
    "CROSS_DOCUMENT_ADDRESS_CONFLICT",
    "CROSS_DOCUMENT_ENTITY_TYPE_CONFLICT",
    "CROSS_DOCUMENT_IDENTIFIER_CONFLICT",
    "CROSS_DOCUMENT_DATE_SEQUENCE_INVALID",
    "CROSS_DOCUMENT_PRODUCT_MISMATCH",
    "CROSS_DOCUMENT_MANUFACTURER_MISMATCH",
})


_EVIDENCE_QUALITY_FLAGS: frozenset[str] = frozenset({
    "EVIDENCE_GROUNDING_UNRELIABLE",
    "EVIDENCE_PROVENANCE_UNCLEAR",
    "EVIDENCE_QUALITY_VERIFICATION_INCOMPLETE",
    "EVIDENCE_LINKAGE_BROKEN",
    "GROUNDING_INSUFFICIENT",
    "SOURCE_DOCUMENT_UNRECOVERABLE",
    "VERIFICATION_NON_REPRODUCIBLE",
    "AUDITABILITY_VERIFICATION_INCOMPLETE",
})


_VERIFICATION_AVAILABILITY_FLAGS: frozenset[str] = frozenset({
    "VERIFICATION_PROVIDER_UNAVAILABLE",
    "VERIFICATION_PROVIDER_TIMEOUT",
    "VERIFICATION_PROVIDER_ERROR",
    "CRITICAL_SOURCE_UNAVAILABLE",
    "GST_VERIFICATION_UNAVAILABLE",
    "UDYAM_VERIFICATION_UNAVAILABLE",
    "STARTUP_VERIFICATION_UNAVAILABLE",
    "STATUTORY_VERIFICATION_UNAVAILABLE",
    "TENDER_SPECIFIC_VERIFICATION_UNAVAILABLE",
    "FINANCIAL_VERIFICATION_UNAVAILABLE",
    "DEBARMENT_VERIFICATION_UNAVAILABLE",
    "PROCUREMENT_ELIGIBILITY_UNVERIFIABLE",
    "FALLBACK_VERIFICATION_INCOMPLETE",
})


def _category_for_flag(flag_id: str | None) -> RiskCategory:
    """Map a flag ID to a RiskCategory.

    Falls back to COMPLIANCE for everything else so generic compliance
    failures still get a category.
    """

    if not flag_id:
        return RiskCategory.COMPLIANCE
    if flag_id in _DOCUMENT_REUSE_FLAGS:
        return RiskCategory.DOCUMENT_REUSE
    if flag_id in _IDENTITY_FLAGS:
        return RiskCategory.IDENTITY
    if flag_id in _EVIDENCE_QUALITY_FLAGS:
        return RiskCategory.EVIDENCE_QUALITY
    if flag_id in _VERIFICATION_AVAILABILITY_FLAGS:
        return RiskCategory.VERIFICATION_AVAILABILITY
    return RiskCategory.COMPLIANCE


__all__ = [
    "correlation_key_for_evidence_quality",
    "correlation_key_for_verification_availability",
    "correlation_key_from_compliance_result",
    "correlation_key_from_identity_finding",
    "correlation_key_from_similarity_trace",
    "correlation_key_from_verification_finding",
]
