"""Multi-source identity aggregation.

Build an :class:`IdentityAggregation` from a list of
:class:`IdentityObservation` objects by:

1. Pairing observations across distinct sources in a stable order.
2. Computing each :class:`IdentityPairwiseComparison`.
3. Summarizing the verified-vs-insufficient source sets.

The aggregation deliberately does NOT apply any "majority truth"
rule: a downstream policy layer decides how to act on the evidence
graph this module produces.
"""

from __future__ import annotations

from typing import Iterable

from .comparison import compare_pair, enumerate_pairs
from .models import (
    IdentityAggregation,
    IdentityObservation,
    IdentityPairwiseComparison,
    SourceAvailability,
)
from .normalization import NAME_NORMALIZATION_VERSION


def aggregate(observations: Iterable[IdentityObservation]) -> IdentityAggregation:
    """Build a per-bidder aggregation.

    All supplied observations are expected to belong to the same
    bidder; the function picks the bidder ID from the first
    observation and verifies that the remaining observations agree.
    Mismatched bidder IDs raise :class:`ValueError` so the engine
    never silently merges different bidders.
    """

    obs_list = list(observations)
    if not obs_list:
        raise ValueError(
            "aggregate() requires at least one observation; got an empty list"
        )

    bidder_id = obs_list[0].bidder_id
    for obs in obs_list:
        if obs.bidder_id != bidder_id:
            raise ValueError(
                "aggregate() received observations from different bidders: "
                f"{bidder_id!r} vs {obs.bidder_id!r}"
            )

    pairs = enumerate_pairs(obs_list)
    comparisons: list[IdentityPairwiseComparison] = []
    for left, right in pairs:
        comparisons.append(compare_pair(left, right))

    verified_sources: list[str] = []
    insufficient_sources: list[str] = []
    seen_verified: set[str] = set()
    seen_insufficient: set[str] = set()
    for obs in obs_list:
        if obs.source_status == SourceAvailability.VERIFIED and (
            obs.normalized_name is not None
        ):
            if obs.source not in seen_verified:
                seen_verified.add(obs.source)
                verified_sources.append(obs.source)
        else:
            if obs.source not in seen_insufficient:
                seen_insufficient.add(obs.source)
                insufficient_sources.append(obs.source)

    disagreeing_pairs = tuple(
        c for c in comparisons if c.outcome.value == "MISMATCH"
    )

    return IdentityAggregation(
        bidder_id=bidder_id,
        observations=tuple(obs_list),
        comparisons=tuple(comparisons),
        verified_sources=tuple(verified_sources),
        insufficient_sources=tuple(insufficient_sources),
        disagreeing_pairs=disagreeing_pairs,
        normalization_version=NAME_NORMALIZATION_VERSION,
    )


__all__ = ["aggregate"]