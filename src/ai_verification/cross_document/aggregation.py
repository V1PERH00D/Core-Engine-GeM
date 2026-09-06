"""Per-bidder aggregation of cross-document consistency comparisons."""


from typing import Iterable, List

from .models import (
    ConsistencyDimension,
    CrossDocumentAggregation,
    DimensionSummary,
    FieldObservation,
    PairwiseComparison,
)


_MISMATCH_OUTCOMES = frozenset({"MISMATCH", "VALIDITY_CONFLICT"})
_INSUFFICIENT_OUTCOMES = frozenset({"INSUFFICIENT_EVIDENCE"})


def aggregate(
    bidder_id: str,
    observations: Iterable[FieldObservation],
    comparisons: Iterable[PairwiseComparison],
    *,
    evaluation_date_iso: str | None = None,
) -> CrossDocumentAggregation:
    obs_list = list(observations)
    cmp_list = list(comparisons)
    if not obs_list:
        raise ValueError(
            "aggregate() requires at least one observation; got an empty list"
        )

    bidder = bidder_id or obs_list[0].bidder_id
    for obs in obs_list:
        if obs.bidder_id != bidder:
            raise ValueError(
                "aggregate() received observations from different bidders: "
                f"{bidder!r} vs {obs.bidder_id!r}"
            )

    summaries: List[DimensionSummary] = []
    for dimension in ConsistencyDimension:
        relevant = [c for c in cmp_list if c.dimension is dimension]
        matches = sum(
            1 for c in relevant
            if c.outcome not in _MISMATCH_OUTCOMES
            and c.outcome not in _INSUFFICIENT_OUTCOMES
        )
        mismatches = sum(
            1 for c in relevant if c.outcome in _MISMATCH_OUTCOMES
        )
        insufficient = sum(
            1 for c in relevant if c.outcome in _INSUFFICIENT_OUTCOMES
        )
        summaries.append(
            DimensionSummary(
                dimension=dimension,
                total_comparisons=len(relevant),
                matches=matches,
                mismatches=mismatches,
                insufficient_evidence=insufficient,
            )
        )

    mismatching = tuple(c for c in cmp_list if c.outcome in _MISMATCH_OUTCOMES)
    insufficient = tuple(
        c for c in cmp_list if c.outcome in _INSUFFICIENT_OUTCOMES
    )

    return CrossDocumentAggregation(
        bidder_id=bidder,
        observations=tuple(obs_list),
        comparisons=tuple(cmp_list),
        dimension_summaries=tuple(summaries),
        mismatching_comparisons=mismatching,
        insufficient_evidence_comparisons=insufficient,
        normalization_version=_aggregate_normalization_version(),
        evaluation_date_iso=evaluation_date_iso,
    )


def _aggregate_normalization_version() -> str:
    from .normalization import (
        ADDRESS_NORMALIZATION_VERSION,
        DATE_NORMALIZATION_VERSION,
        IDENTIFIER_NORMALIZATION_VERSION,
        MANUFACTURER_NORMALIZATION_VERSION,
        PRODUCT_NORMALIZATION_VERSION,
    )
    parts = (
        IDENTIFIER_NORMALIZATION_VERSION,
        ADDRESS_NORMALIZATION_VERSION,
        DATE_NORMALIZATION_VERSION,
        PRODUCT_NORMALIZATION_VERSION,
        MANUFACTURER_NORMALIZATION_VERSION,
    )
    return "+".join(parts)


__all__ = ["aggregate"]
