"""Pairwise identity comparison.

Given two :class:`IdentityObservation` objects, return an
:class:`IdentityPairwiseComparison` whose outcome is one of:

* :attr:`ComparisonOutcome.MATCH_EXACT`
* :attr:`ComparisonOutcome.MATCH_NORMALIZED`
* :attr:`ComparisonOutcome.MISMATCH`
* :attr:`ComparisonOutcome.INSUFFICIENT_EVIDENCE`

The comparison is strictly source-aware: an
:attr:`ComparisonOutcome.INSUFFICIENT_EVIDENCE` outcome is returned
whenever the source status of either side is anything other than
``VERIFIED``. Provider failure is therefore NEVER turned into a
mismatch.
"""

from __future__ import annotations

from typing import List, Tuple as TypingTuple

from .models import (
    ComparisonOutcome,
    IdentityObservation,
    IdentityPairwiseComparison,
    SourceAvailability,
)


#: Canonical ordered list of sources supported by the engine.
SUPPORTED_SOURCES: tuple[str, ...] = ("GST", "PAN", "UDYAM", "MCA")


# ---------------------------------------------------------------------------
# Pair enumeration
# ---------------------------------------------------------------------------


def enumerate_pairs(
    observations: List[IdentityObservation],
) -> List[TypingTuple[IdentityObservation, IdentityObservation]]:
    """Return all distinct (left, right) source pairs.

    * Pairs are emitted in a deterministic
      ``(left_source_index, right_source_index)`` order following
      :data:`SUPPORTED_SOURCES`.
    * A source is never paired with itself.
    * If multiple observations exist for the same source (e.g. two
      GST queries), the *first* one wins. Subsequent observations
      for the same source are kept on the aggregation for audit
      purposes but do not generate additional pairs.
    """

    by_source: dict[str, IdentityObservation] = {}
    for obs in observations:
        if obs.source not in by_source:
            by_source[obs.source] = obs

    ordered_sources = [s for s in SUPPORTED_SOURCES if s in by_source]
    pairs: List[TypingTuple[IdentityObservation, IdentityObservation]] = []
    for i, left_source in enumerate(ordered_sources):
        for right_source in ordered_sources[i + 1 :]:
            pairs.append((by_source[left_source], by_source[right_source]))
    return pairs


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _eligible(observation: IdentityObservation) -> bool:
    """Return True iff the observation has a verified, named status."""

    return (
        observation.source_status == SourceAvailability.VERIFIED
        and observation.normalized_name is not None
    )


def compare_pair(
    left: IdentityObservation,
    right: IdentityObservation,
) -> IdentityPairwiseComparison:
    """Compare two observations and return a typed result.

    See module docstring for the full set of outcomes. The function
    tolerates same-source calls by returning an
    :attr:`ComparisonOutcome.INSUFFICIENT_EVIDENCE` result rather
    than crashing, so the engine stays fail-safe.
    """

    if left.source == right.source:
        return _build(
            left,
            right,
            ComparisonOutcome.INSUFFICIENT_EVIDENCE,
            (
                "Both observations came from the same source; "
                "self-comparison is suppressed."
            ),
        )

    if not _eligible(left) or not _eligible(right):
        return _build(
            left,
            right,
            ComparisonOutcome.INSUFFICIENT_EVIDENCE,
            _insufficient_reason(left, right),
        )

    assert left.normalized_name is not None
    assert right.normalized_name is not None

    if (
        left.original_name == right.original_name
        and left.original_name is not None
    ):
        return _build(
            left,
            right,
            ComparisonOutcome.MATCH_EXACT,
            (
                f"Verified names from {left.source} and {right.source} "
                f"are byte-identical: {left.original_name!r}."
            ),
        )

    if left.normalized_name == right.normalized_name:
        return _build(
            left,
            right,
            ComparisonOutcome.MATCH_NORMALIZED,
            (
                f"Verified names from {left.source} ({left.original_name!r}) "
                f"and {right.source} ({right.original_name!r}) differ "
                f"originally but are identical after deterministic "
                f"normalization (version {left.normalization_version!r})."
            ),
        )

    return _build(
        left,
        right,
        ComparisonOutcome.MISMATCH,
        (
            f"Verified names from {left.source} ({left.original_name!r}) "
            f"and {right.source} ({right.original_name!r}) remain "
            f"materially different after deterministic normalization: "
            f"{left.normalized_name!r} vs {right.normalized_name!r}."
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_STATUS_LABELS: dict[SourceAvailability, str] = {
    SourceAvailability.NOT_QUERIED: "not queried",
    SourceAvailability.UNAVAILABLE: "unavailable",
    SourceAvailability.NOT_FOUND: "not found",
    SourceAvailability.VERIFIED_WITHOUT_NAME: "verified without name",
    SourceAvailability.INACTIVE: "inactive",
    SourceAvailability.VERIFIED: "verified",
}


def _insufficient_reason(
    left: IdentityObservation,
    right: IdentityObservation,
) -> str:
    """Build a deterministic, human-readable reason for insufficient evidence."""

    parts: list[str] = []
    for obs in (left, right):
        label = _STATUS_LABELS.get(obs.source_status, str(obs.source_status))
        parts.append(f"{obs.source} is {label}")
    joined = "; ".join(parts)
    return (
        f"Cannot compare {left.source} vs {right.source} due to "
        f"insufficient evidence: {joined}. Provider failure or "
        f"missing identity field is not treated as a mismatch."
    )


def _build(
    left: IdentityObservation,
    right: IdentityObservation,
    outcome: ComparisonOutcome,
    explanation: str,
) -> IdentityPairwiseComparison:
    """Construct the result with all audit fields populated verbatim."""

    return IdentityPairwiseComparison(
        left_source=left.source,
        right_source=right.source,
        left_verification_id=left.verification_id,
        right_verification_id=right.verification_id,
        outcome=outcome,
        left_original=left.original_name,
        right_original=right.original_name,
        left_normalized=left.normalized_name,
        right_normalized=right.normalized_name,
        explanation=explanation,
        left_evidence_ref=left.evidence_ref,
        right_evidence_ref=right.evidence_ref,
        left_document_ref=left.document_ref,
        right_document_ref=right.document_ref,
        left_queried_identifier=left.queried_identifier,
        right_queried_identifier=right.queried_identifier,
    )


__all__ = [
    "SUPPORTED_SOURCES",
    "compare_pair",
    "enumerate_pairs",
]