"""Convert an :class:`IdentityAggregation` into findings.

The module produces two complementary artefacts:

* :class:`compliance_engine.models.IdentityFinding` records.
* :class:`ai_verification.models.VerificationFinding` records.

Both are derived from the same aggregation and stay consistent.

The canonical flag is :data:`CROSS_SOURCE_IDENTITY_MISMATCH` --
registered in ``compliance_engine.flags.registry`` under the
``Bidder Identity`` capability with ``HIGH`` severity.
"""

from __future__ import annotations

from typing import List, Tuple

from compliance_engine.flags import get_flag_definition
from compliance_engine.models import Capability, IdentityFinding

from ai_verification.models.contracts import VerificationFinding

from .models import (
    ComparisonOutcome,
    IdentityAggregation,
    IdentityPairwiseComparison,
)


#: Canonical flag ID for cross-source identity mismatch.
CROSS_SOURCE_IDENTITY_MISMATCH: str = get_flag_definition(
    "CROSS_SOURCE_IDENTITY_MISMATCH"
).flag_id


# ---------------------------------------------------------------------------
# Compliance-Engine IdentityFinding conversion
# ---------------------------------------------------------------------------


def to_identity_findings(
    aggregation: IdentityAggregation,
) -> List[IdentityFinding]:
    """Return one :class:`IdentityFinding` per pairwise mismatch.

    The Compliance Engine's :class:`IdentityFinding` model is bound
    to two documents (``left_document_id`` / ``right_document_id``)
    and two evidence refs; we project each source-level comparison
    into that shape using the per-source ``document_ref`` /
    ``evidence_ref`` carried over from the observation.
    """

    findings: List[IdentityFinding] = []
    for pair in aggregation.disagreeing_pairs:
        left_doc_id = pair.left_document_ref or pair.left_source
        right_doc_id = pair.right_document_ref or pair.right_source
        left_evidence = pair.left_evidence_ref or pair.left_verification_id
        right_evidence = pair.right_evidence_ref or pair.right_verification_id
        compared_values = _safe_str_pair(
            pair.left_original, pair.right_original
        )
        normalized_values = _safe_str_pair(
            pair.left_normalized, pair.right_normalized
        )
        findings.append(
            IdentityFinding(
                flag_id=CROSS_SOURCE_IDENTITY_MISMATCH,
                capability=Capability.BIDDER_IDENTITY,
                message=pair.explanation,
                evidence_refs=[left_evidence, right_evidence],
                compared_values=compared_values,
                normalized_values=normalized_values,
                left_document_id=left_doc_id,
                right_document_id=right_doc_id,
            )
        )
    return findings


# ---------------------------------------------------------------------------
# AI Verification Engine VerificationFinding conversion
# ---------------------------------------------------------------------------


def _comparison_confidence(comp: IdentityPairwiseComparison) -> float:
    """Return a deterministic confidence score for a comparison outcome.

    The score is bounded in ``[0.0, 1.0]`` and reflects how
    confident the engine is in declaring the outcome. MATCH_EXACT
    and MATCH_NORMALIZED deserve high confidence; MISMATCH is also
    high; INSUFFICIENT_EVIDENCE is zero so a future policy layer
    can drop those findings if it wants.
    """

    if comp.outcome == ComparisonOutcome.MATCH_EXACT:
        return 1.0
    if comp.outcome == ComparisonOutcome.MATCH_NORMALIZED:
        return 0.95
    if comp.outcome == ComparisonOutcome.MISMATCH:
        return 0.9
    return 0.0


def to_verification_findings(
    aggregation: IdentityAggregation,
    *,
    bidder_id: str | None = None,
) -> List[VerificationFinding]:
    """Return one :class:`VerificationFinding` per pairwise mismatch.

    Only ``MISMATCH`` outcomes are emitted as findings. ``MATCH_*``
    outcomes are intentional positive signals and would only add
    noise; ``INSUFFICIENT_EVIDENCE`` outcomes are surfaced via the
    aggregation itself and should be consumed via the aggregation
    summary.

    The ``verification_refs`` are populated from each side's
    ``verification_id`` so the audit trail is end-to-end. The
    ``severity`` is copied from the canonical flag registry so the
    finding always carries the authoritative severity.

    When ``bidder_id`` is supplied it overrides the aggregation's
    bidder_id on every emitted finding. This is the
    forward-compatibility seam the :class:`VerificationEngine`
    relies on.
    """

    findings: List[VerificationFinding] = []
    severity = get_flag_definition(
        CROSS_SOURCE_IDENTITY_MISMATCH
    ).severity
    effective_bidder_id = bidder_id or aggregation.bidder_id
    for pair in aggregation.disagreeing_pairs:
        verification_refs = [
            pair.left_verification_id,
            pair.right_verification_id,
        ]
        evidence_refs: list[str] = []
        for ref in (pair.left_evidence_ref, pair.right_evidence_ref):
            if ref and ref not in evidence_refs:
                evidence_refs.append(ref)
        explanation = (
            f"Cross-source identity mismatch between {pair.left_source} "
            f"and {pair.right_source}: {pair.explanation}"
        )
        finding_id = (
            f"identity-mismatch:{effective_bidder_id}:"
            f"{pair.left_verification_id}:{pair.right_verification_id}"
        )
        findings.append(
            VerificationFinding(
                finding_id=finding_id,
                bidder_id=effective_bidder_id,
                flag_id=CROSS_SOURCE_IDENTITY_MISMATCH,
                severity=severity,
                confidence=_comparison_confidence(pair),
                explanation=explanation,
                evidence_refs=evidence_refs,
                verification_refs=verification_refs,
                related_bidder_ids=[],
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_str_pair(
    left: str | None, right: str | None
) -> Tuple[str, str]:
    """Coerce ``None`` to the empty string for the compliance model."""

    return (left if left is not None else "", right if right is not None else "")


__all__ = [
    "CROSS_SOURCE_IDENTITY_MISMATCH",
    "to_identity_findings",
    "to_verification_findings",
]