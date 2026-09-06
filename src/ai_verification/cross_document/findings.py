"""Convert a CrossDocumentAggregation into findings."""


from typing import List

from compliance_engine.flags import get_flag_definition

from ai_verification.evidence_quality import QualityState
from ai_verification.models.contracts import VerificationFinding

from .models import (
    ConsistencyDimension,
    CrossDocumentAggregation,
    DateComparisonOutcome,
    FieldObservation,
    PairwiseComparison,
)


FLAG_ID_BY_DIMENSION: dict[ConsistencyDimension, str] = {
    ConsistencyDimension.IDENTIFIER: "CROSS_DOCUMENT_IDENTIFIER_CONFLICT",
    ConsistencyDimension.ADDRESS: "CROSS_DOCUMENT_ADDRESS_CONFLICT",
    ConsistencyDimension.DATE: "CROSS_DOCUMENT_DATE_SEQUENCE_INVALID",
    ConsistencyDimension.PRODUCT: "CROSS_DOCUMENT_PRODUCT_MISMATCH",
    ConsistencyDimension.MANUFACTURER: "CROSS_DOCUMENT_MANUFACTURER_MISMATCH",
}


_OUTCOME_BASE_CONFIDENCE = {
    "MISMATCH": 0.9,
    "VALIDITY_CONFLICT": 0.95,
}


_QUALITY_STATE_DELTA = {
    QualityState.GOOD: 0.0,
    QualityState.DEGRADED: -0.1,
    QualityState.UNKNOWN: -0.2,
}


def to_verification_findings(
    aggregation: CrossDocumentAggregation,
) -> List[VerificationFinding]:
    findings: List[VerificationFinding] = []
    for comparison in aggregation.mismatching_comparisons:
        findings.extend(_to_findings_for(aggregation, comparison))
    return findings


def _to_findings_for(
    aggregation: CrossDocumentAggregation,
    comparison: PairwiseComparison,
) -> List[VerificationFinding]:
    dimension = comparison.dimension
    flag_id = FLAG_ID_BY_DIMENSION.get(dimension)
    if flag_id is None:
        return []

    severity = get_flag_definition(flag_id).severity
    confidence = _confidence_for(comparison)
    finding_id = _finding_id(aggregation.bidder_id, comparison)
    verification_refs = _verification_refs(comparison)
    evidence_refs = _evidence_refs(comparison)

    explanation = (
        f"Cross-document {dimension.value.lower()} mismatch: "
        f"{comparison.explanation} "
        f"Comparability reason: {comparison.comparability_reason}"
    )

    return [
        VerificationFinding(
            finding_id=finding_id,
            bidder_id=aggregation.bidder_id,
            flag_id=flag_id,
            severity=severity,
            confidence=confidence,
            explanation=explanation,
            evidence_refs=evidence_refs,
            verification_refs=verification_refs,
            related_bidder_ids=[],
        )
    ]


def _confidence_for(comparison: PairwiseComparison) -> float:
    base = _OUTCOME_BASE_CONFIDENCE.get(comparison.outcome, 0.9)
    delta = 0.0
    for state in (comparison.left_quality_state, comparison.right_quality_state):
        if state is None:
            continue
        delta += _QUALITY_STATE_DELTA.get(state, 0.0)
    if delta < -0.4:
        delta = -0.4
    confidence = base + delta
    if confidence < 0.0:
        confidence = 0.0
    if confidence > 1.0:
        confidence = 1.0
    return confidence


def _finding_id(bidder_id: str, comparison: PairwiseComparison) -> str:
    left, right = sorted(
        (comparison.left_evidence_id, comparison.right_evidence_id)
    )
    return (
        f"cross-document:{bidder_id}:{comparison.dimension.value}:"
        f"{left}:{right}"
    )


def _verification_refs(comparison: PairwiseComparison) -> list[str]:
    return [
        comparison.left_evidence_id,
        comparison.right_evidence_id,
    ]


def _evidence_refs(comparison: PairwiseComparison) -> list[str]:
    refs = [
        comparison.left_evidence_id,
        comparison.right_evidence_id,
    ]
    seen: set = set()
    ordered: list[str] = []
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        ordered.append(ref)
    return ordered


def strongest_mismatches(
    aggregation: CrossDocumentAggregation,
) -> List[PairwiseComparison]:
    by_dim: dict[ConsistencyDimension, PairwiseComparison] = {}
    for comp in aggregation.mismatching_comparisons:
        existing = by_dim.get(comp.dimension)
        if existing is None:
            by_dim[comp.dimension] = comp
            continue
        if (
            comp.outcome == DateComparisonOutcome.VALIDITY_CONFLICT.value
            and existing.outcome != DateComparisonOutcome.VALIDITY_CONFLICT.value
        ):
            by_dim[comp.dimension] = comp
    return [
        by_dim[d] for d in ConsistencyDimension if d in by_dim
    ]


def observations_for_comparison(
    aggregation: CrossDocumentAggregation,
    comparison: PairwiseComparison,
) -> tuple[FieldObservation | None, FieldObservation | None]:
    left = next(
        (o for o in aggregation.observations
         if o.evidence_id == comparison.left_evidence_id),
        None,
    )
    right = next(
        (o for o in aggregation.observations
         if o.evidence_id == comparison.right_evidence_id),
        None,
    )
    return left, right


__all__ = [
    "FLAG_ID_BY_DIMENSION",
    "observations_for_comparison",
    "strongest_mismatches",
    "to_verification_findings",
]
