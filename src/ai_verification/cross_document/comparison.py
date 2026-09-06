"""Pairwise comparison across FieldObservation objects."""


from typing import Iterable, List, Tuple as TypingTuple

# Import via the fully-qualified package path and read the
# attribute off the module. This is the same style used by the
# package __init__.py and avoids the brittle ``from .extraction
# import ...`` form under partial-load in Python 3.14.
import ai_verification.cross_document.extraction as _extraction_mod
are_comparable = _extraction_mod.are_comparable
del _extraction_mod

from .models import (
    AddressComparisonOutcome,
    ConsistencyDimension,
    DateComparisonOutcome,
    FieldObservation,
    IdentifierComparisonOutcome,
    ManufacturerComparisonOutcome,
    PairwiseComparison,
    ProductComparisonOutcome,
)
from .normalization import (
    parse_iso_date,
)


_VERSION_FOR_DIMENSION = {}


def _norm_version(observation: FieldObservation) -> str:
    if observation.dimension in _VERSION_FOR_DIMENSION:
        return _VERSION_FOR_DIMENSION[observation.dimension]
    from .normalization import (
        ADDRESS_NORMALIZATION_VERSION,
        DATE_NORMALIZATION_VERSION,
        IDENTIFIER_NORMALIZATION_VERSION,
        MANUFACTURER_NORMALIZATION_VERSION,
        PRODUCT_NORMALIZATION_VERSION,
    )
    _VERSION_FOR_DIMENSION.update({
        ConsistencyDimension.IDENTIFIER: IDENTIFIER_NORMALIZATION_VERSION,
        ConsistencyDimension.ADDRESS: ADDRESS_NORMALIZATION_VERSION,
        ConsistencyDimension.DATE: DATE_NORMALIZATION_VERSION,
        ConsistencyDimension.PRODUCT: PRODUCT_NORMALIZATION_VERSION,
        ConsistencyDimension.MANUFACTURER: MANUFACTURER_NORMALIZATION_VERSION,
    })
    return _VERSION_FOR_DIMENSION.get(
        observation.dimension or ConsistencyDimension.IDENTIFIER,
        IDENTIFIER_NORMALIZATION_VERSION,
    )


def enumerate_pairs(
    observations: List[FieldObservation],
) -> List[TypingTuple[FieldObservation, FieldObservation]]:
    """Return all distinct (left, right) observation pairs."""
    comparable = [o for o in observations if o.is_comparable]
    pairs: List[TypingTuple[FieldObservation, FieldObservation]] = []
    seen: set = set()
    for i, left in enumerate(comparable):
        for right in comparable[i + 1:]:
            key = (left.evidence_id, right.evidence_id)
            if key in seen:
                continue
            seen.add(key)
            pairs.append((left, right))
    return pairs


def _compare_identifier(
    left: FieldObservation, right: FieldObservation
) -> PairwiseComparison:
    comparability = are_comparable(left, right)
    if not comparability.comparable:
        return _build_incomparable(left, right, comparability.reason)

    left_norm = left.normalized_value
    right_norm = right.normalized_value
    assert left_norm is not None and right_norm is not None

    left_original = left.original_value
    right_original = right.original_value
    if left_original == right_original:
        outcome = IdentifierComparisonOutcome.MATCH_EXACT
        explanation = (
            f"Identifier values from {left.short_reference()} and "
            f"{right.short_reference()} are byte-identical."
        )
    elif left_norm == right_norm:
        outcome = IdentifierComparisonOutcome.MATCH_NORMALIZED
        explanation = (
            f"Identifier values from {left.short_reference()} "
            f"({left_original!r}) and {right.short_reference()} "
            f"({right_original!r}) differ originally but are identical "
            f"after deterministic normalization "
            f"(version {_norm_version(left)})."
        )
    else:
        outcome = IdentifierComparisonOutcome.MISMATCH
        explanation = (
            f"Identifier values from {left.short_reference()} "
            f"({left_original!r}) and {right.short_reference()} "
            f"({right_original!r}) remain materially different after "
            f"deterministic normalization: {left_norm!r} vs "
            f"{right_norm!r}."
        )

    return _build(
        left, right, outcome.value, comparability.reason,
        left_norm, right_norm, explanation,
    )


def _compare_address(
    left: FieldObservation, right: FieldObservation
) -> PairwiseComparison:
    comparability = are_comparable(left, right)
    if not comparability.comparable:
        return _build_incomparable(left, right, comparability.reason)

    left_norm = left.normalized_value
    right_norm = right.normalized_value
    assert left_norm is not None and right_norm is not None

    left_original = left.original_value
    right_original = right.original_value
    if left_original == right_original:
        outcome = AddressComparisonOutcome.EXACT
        explanation = (
            f"Address values from {left.short_reference()} and "
            f"{right.short_reference()} are byte-identical."
        )
    elif left_norm == right_norm:
        outcome = AddressComparisonOutcome.NORMALIZED_MATCH
        explanation = (
            f"Address values from {left.short_reference()} and "
            f"{right.short_reference()} differ originally but are "
            f"identical after deterministic address normalization "
            f"(version {_norm_version(left)})."
        )
    else:
        outcome = AddressComparisonOutcome.MISMATCH
        explanation = (
            f"Address values from {left.short_reference()} "
            f"({left_original!r}) and {right.short_reference()} "
            f"({right_original!r}) remain materially different after "
            f"address normalization."
        )

    return _build(
        left, right, outcome.value, comparability.reason,
        left_norm, right_norm, explanation,
    )


def _compare_date(
    left: FieldObservation,
    right: FieldObservation,
    *,
    evaluation_date_iso: str | None = None,
) -> PairwiseComparison:
    comparability = are_comparable(left, right)
    if not comparability.comparable:
        return _build_incomparable(left, right, comparability.reason)

    left_norm = left.normalized_value
    right_norm = right.normalized_value
    assert left_norm is not None and right_norm is not None

    if left_norm == right_norm:
        outcome = DateComparisonOutcome.MATCH
        explanation = (
            f"Dates from {left.short_reference()} and "
            f"{right.short_reference()} are identical: {left_norm!r}."
        )
        return _build(
            left, right, outcome.value, comparability.reason,
            left_norm, right_norm, explanation,
        )

    outcome = DateComparisonOutcome.MISMATCH
    explanation = (
        f"Dates from {left.short_reference()} ({left_norm!r}) and "
        f"{right.short_reference()} ({right_norm!r}) differ; the "
        f"underlying documents report materially different dates for "
        f"the same semantic event."
    )

    eval_date = parse_iso_date(evaluation_date_iso) if evaluation_date_iso else None
    if eval_date is not None:
        left_parsed = parse_iso_date(left_norm)
        right_parsed = parse_iso_date(right_norm)
        if (
            left_parsed is not None
            and right_parsed is not None
            and eval_date > left_parsed
            and eval_date > right_parsed
        ):
            explanation = (
                f"Dates from {left.short_reference()} ({left_norm!r}) "
                f"and {right.short_reference()} ({right_norm!r}) differ "
                f"and both predate the explicit evaluation date "
                f"{evaluation_date_iso}, suggesting a validity conflict "
                f"rather than a benign ordering difference."
            )
            outcome = DateComparisonOutcome.VALIDITY_CONFLICT

    return _build(
        left, right, outcome.value, comparability.reason,
        left_norm, right_norm, explanation,
    )


def _compare_product(
    left: FieldObservation, right: FieldObservation
) -> PairwiseComparison:
    comparability = are_comparable(left, right)
    if not comparability.comparable:
        return _build_incomparable(left, right, comparability.reason)

    left_norm = left.normalized_value
    right_norm = right.normalized_value
    assert left_norm is not None and right_norm is not None

    left_original = left.original_value
    right_original = right.original_value
    if left_original == right_original:
        outcome = ProductComparisonOutcome.EXACT
        explanation = (
            f"Product values from {left.short_reference()} and "
            f"{right.short_reference()} are byte-identical."
        )
    elif left_norm == right_norm:
        outcome = ProductComparisonOutcome.NORMALIZED_MATCH
        explanation = (
            f"Product values from {left.short_reference()} and "
            f"{right.short_reference()} differ originally but are "
            f"identical after deterministic product normalization "
            f"(version {_norm_version(left)})."
        )
    else:
        outcome = ProductComparisonOutcome.MISMATCH
        explanation = (
            f"Product values from {left.short_reference()} "
            f"({left_original!r}) and {right.short_reference()} "
            f"({right_original!r}) remain materially different after "
            f"product normalization."
        )

    return _build(
        left, right, outcome.value, comparability.reason,
        left_norm, right_norm, explanation,
    )


def _compare_manufacturer(
    left: FieldObservation, right: FieldObservation
) -> PairwiseComparison:
    comparability = are_comparable(left, right)
    if not comparability.comparable:
        return _build_incomparable(left, right, comparability.reason)

    left_norm = left.normalized_value
    right_norm = right.normalized_value
    assert left_norm is not None and right_norm is not None

    left_original = left.original_value
    right_original = right.original_value
    if left_original == right_original:
        outcome = ManufacturerComparisonOutcome.MATCH_EXACT
        explanation = (
            f"Manufacturer values from {left.short_reference()} and "
            f"{right.short_reference()} are byte-identical."
        )
    elif left_norm == right_norm:
        outcome = ManufacturerComparisonOutcome.MATCH_NORMALIZED
        explanation = (
            f"Manufacturer values from {left.short_reference()} "
            f"({left_original!r}) and {right.short_reference()} "
            f"({right_original!r}) differ originally but are identical "
            f"after the shared identity-name normalization "
            f"(version {_norm_version(left)})."
        )
    else:
        outcome = ManufacturerComparisonOutcome.MISMATCH
        explanation = (
            f"Manufacturer values from {left.short_reference()} "
            f"({left_original!r}) and {right.short_reference()} "
            f"({right_original!r}) remain materially different after "
            f"normalization."
        )

    return _build(
        left, right, outcome.value, comparability.reason,
        left_norm, right_norm, explanation,
    )


def compare_pair(
    left: FieldObservation,
    right: FieldObservation,
    *,
    evaluation_date_iso: str | None = None,
) -> PairwiseComparison:
    if left.dimension is None or right.dimension is None:
        return _build_incomparable(
            left, right,
            "Field is not classifiable into a supported dimension.",
        )

    if left.evidence_id == right.evidence_id:
        return _build_self(left, right)

    if left.dimension is ConsistencyDimension.IDENTIFIER:
        return _compare_identifier(left, right)
    if left.dimension is ConsistencyDimension.ADDRESS:
        return _compare_address(left, right)
    if left.dimension is ConsistencyDimension.DATE:
        return _compare_date(
            left, right, evaluation_date_iso=evaluation_date_iso
        )
    if left.dimension is ConsistencyDimension.PRODUCT:
        return _compare_product(left, right)
    if left.dimension is ConsistencyDimension.MANUFACTURER:
        return _compare_manufacturer(left, right)
    return _build_incomparable(left, right, "Unsupported dimension.")


def compare_all(
    observations: Iterable[FieldObservation],
    *,
    evaluation_date_iso: str | None = None,
) -> List[PairwiseComparison]:
    obs_list = list(observations)
    pairs = enumerate_pairs(obs_list)
    return [
        compare_pair(left, right, evaluation_date_iso=evaluation_date_iso)
        for left, right in pairs
    ]


def _build(
    left: FieldObservation,
    right: FieldObservation,
    outcome_value: str,
    reason: str,
    left_norm: str | None,
    right_norm: str | None,
    explanation: str,
    *,
    is_self_comparison: bool = False,
) -> PairwiseComparison:
    return PairwiseComparison(
        bidder_id=left.bidder_id,
        dimension=left.dimension or ConsistencyDimension.IDENTIFIER,
        left_document_id=left.document_id,
        right_document_id=right.document_id,
        left_document_type=left.document_type,
        right_document_type=right.document_type,
        left_field_name=left.field_name,
        right_field_name=right.field_name,
        left_evidence_id=left.evidence_id,
        right_evidence_id=right.evidence_id,
        left_original=left.original_value,
        right_original=right.original_value,
        left_normalized=left_norm,
        right_normalized=right_norm,
        outcome=outcome_value,
        normalization_version=_norm_version(left),
        comparability_reason=reason,
        is_self_comparison=is_self_comparison,
        left_confidence=left.evidence_confidence,
        right_confidence=right.evidence_confidence,
        left_quality_state=left.quality_state,
        right_quality_state=right.quality_state,
        left_quality_score=left.quality_score,
        right_quality_score=right.quality_score,
        left_quality_reasons=left.quality_reasons,
        right_quality_reasons=right.quality_reasons,
        explanation=explanation,
    )


_INSUFFICIENT_EVIDENCE_REASON = (
    "Provider failure or missing field; never turned into a mismatch."
)


def _build_incomparable(
    left: FieldObservation,
    right: FieldObservation,
    reason: str,
) -> PairwiseComparison:
    dimension = left.dimension or right.dimension or ConsistencyDimension.IDENTIFIER
    outcome = _insufficient_outcome_for(dimension)
    explanation = (
        f"Cannot compare {left.short_reference()} vs "
        f"{right.short_reference()}: {reason} "
        f"{_INSUFFICIENT_EVIDENCE_REASON}"
    )
    return _build(
        left, right, outcome.value, reason,
        left.normalized_value, right.normalized_value, explanation,
    )


def _build_self(
    left: FieldObservation, right: FieldObservation
) -> PairwiseComparison:
    dimension = left.dimension or ConsistencyDimension.IDENTIFIER
    outcome = _insufficient_outcome_for(dimension)
    explanation = (
        f"Self-comparison suppressed for {left.short_reference()}."
    )
    return _build(
        left, right, outcome.value,
        "Self-comparison is suppressed by the engine.",
        left.normalized_value, right.normalized_value, explanation,
        is_self_comparison=True,
    )


def _insufficient_outcome(dimension: ConsistencyDimension):
    table = {
        ConsistencyDimension.IDENTIFIER: IdentifierComparisonOutcome.INSUFFICIENT_EVIDENCE,
        ConsistencyDimension.ADDRESS: AddressComparisonOutcome.INSUFFICIENT_EVIDENCE,
        ConsistencyDimension.DATE: DateComparisonOutcome.INSUFFICIENT_EVIDENCE,
        ConsistencyDimension.PRODUCT: ProductComparisonOutcome.INSUFFICIENT_EVIDENCE,
        ConsistencyDimension.MANUFACTURER: ManufacturerComparisonOutcome.INSUFFICIENT_EVIDENCE,
    }
    return table[dimension]


def _insufficient_outcome_for(dimension: ConsistencyDimension):
    return _insufficient_outcome(dimension)


__all__ = [
    "compare_all",
    "compare_pair",
    "enumerate_pairs",
]
