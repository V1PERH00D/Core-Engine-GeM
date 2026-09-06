"""Deterministic aggregation of risk signals into a BidderRiskAssessment.

Aggregation formula
-------------------

The aggregate bidder risk score is the strongest signal score boosted
by a bounded contribution from independent supporting signals, then
clamped into ``[0, 1]``::

    aggregate_score = clamp(
        strongest_score * (1.0 + boost),
        0.0,
        1.0,
    )

where::

    boost = min(
        num_independent_supporting * SUPPORTING_BOOST_PER_SIGNAL,
        SUPPORTING_BOOST_CAP,
    )

Risk state machine
------------------

The aggregate score maps to a :class:`RiskState` as follows:

* INDETERMINATE if any of:
    - critical required capability is verified-unavailable AND there
      are no actionable signals,
    - evidence quality is UNKNOWN AND there are no actionable
      signals,
    - (Note: when there are no verifications at all AND no signals,
      the state is CLEAR -- absence of evidence is not epistemic
      uncertainty when nothing was attempted.)
* CLEAR        when there are no actionable signals or the strongest
               actionable signal's severity is below MEDIUM.
* HIGH_RISK    if score > HIGH_RISK_THRESHOLD and the strongest
               actionable signal is at least MEDIUM severity.
* REVIEW       if REVIEW_THRESHOLD <= score <= HIGH_RISK_THRESHOLD and
               the strongest actionable signal is at least MEDIUM
               severity.

HIGH_RISK means the evidence supports a strong risk signal.
INDETERMINATE means the system cannot establish a sufficiently
reliable assessment. INDETERMINATE is uncertainty, NOT risk.
"""

from __future__ import annotations

from typing import Iterable

from compliance_engine.flags import FlagSeverity

from .models import (
    BidderRiskAssessment,
    CorrelationKey,
    EvidenceAvailability,
    EvidenceState,
    ReasonCode,
    RiskSignal,
    RiskState,
)
from .policy import (
    HIGH_RISK_THRESHOLD,
    INDETERMINATE_MIN_STRONGEST_SEVERITY,
    REVIEW_THRESHOLD,
    SUPPORTING_BOOST_CAP,
    SUPPORTING_BOOST_PER_SIGNAL,
)
from .severity import normalize_severity


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _normalize_severity(severity: str) -> FlagSeverity | None:
    return normalize_severity(severity)


_SEVERITY_RANK: dict[FlagSeverity, int] = {
    FlagSeverity.CRITICAL: 4,
    FlagSeverity.HIGH: 3,
    FlagSeverity.MEDIUM: 2,
    FlagSeverity.LOW: 1,
    FlagSeverity.INFO: 0,
}


def _severity_rank(severity: str) -> int:
    enum_value = _normalize_severity(severity)
    if enum_value is None:
        return -1
    return _SEVERITY_RANK.get(enum_value, -1)

def deduplicate_signals(
    signals: Iterable[RiskSignal],
) -> tuple[tuple[RiskSignal, ...], int]:
    """Deduplicate signals by CorrelationKey.

    When multiple signals share a correlation key, only the strongest
    one survives. Tie-break: severity rank, then signal id.

    Returns ``(deduplicated_signals, dedup_count)`` where dedup_count
    is the number of signals suppressed.
    """

    ordered = tuple(sorted(signals, key=lambda s: s.signal_id))
    groups: dict[CorrelationKey, list[RiskSignal]] = {}
    for signal in ordered:
        groups.setdefault(signal.correlation_key, []).append(signal)

    survivors: list[RiskSignal] = []
    dedup_count = 0
    for key in sorted(groups.keys(), key=lambda k: k.model_dump_json()):
        bucket = groups[key]
        bucket_sorted = sorted(
            bucket,
            key=lambda s: (
                -s.score,
                -_severity_rank(s.severity),
                s.signal_id,
            ),
        )
        survivors.append(bucket_sorted[0])
        dedup_count += len(bucket) - 1
    return tuple(survivors), dedup_count


def select_strongest_signal(
    signals: Iterable[RiskSignal],
) -> RiskSignal | None:
    """Return the strongest signal by score.

    Tie-break: severity rank, then signal id. Returns None for empty.
    """

    ordered = list(signals)
    if not ordered:
        return None
    ordered.sort(
        key=lambda s: (
            -s.score,
            -_severity_rank(s.severity),
            s.signal_id,
        )
    )
    return ordered[0]


def compute_aggregate_score(
    strongest: RiskSignal,
    independent_supporting: Iterable[RiskSignal],
) -> float:
    """Compute the aggregate score using the documented formula."""

    supporting = list(independent_supporting)
    raw_boost = min(
        len(supporting) * SUPPORTING_BOOST_PER_SIGNAL,
        SUPPORTING_BOOST_CAP,
    )
    return _clamp(strongest.score * (1.0 + raw_boost))


def determine_risk_state(
    aggregate_score: float,
    strongest: RiskSignal | None,
    *,
    evidence_availability: EvidenceAvailability,
    no_signals: bool,
    no_verifications: bool,
) -> RiskState:
    """Compute the final RiskState.

    Decision order:

    1. INDETERMINATE conditions.
    2. CLEAR when there are no signals and verification was sufficient.
    3. HIGH_RISK / REVIEW based on the aggregate score and the
       strongest signal's severity.
    4. CLEAR otherwise.
    """

    if _is_indeterminate(
        evidence_availability,
        no_verifications=no_verifications,
        strongest=strongest,
    ):
        return RiskState.INDETERMINATE

    if no_signals or strongest is None:
        return RiskState.CLEAR

    if _severity_rank(strongest.severity) < _SEVERITY_RANK[
        INDETERMINATE_MIN_STRONGEST_SEVERITY
    ]:
        return RiskState.CLEAR

    if aggregate_score > HIGH_RISK_THRESHOLD:
        return RiskState.HIGH_RISK
    if aggregate_score >= REVIEW_THRESHOLD:
        return RiskState.REVIEW
    return RiskState.CLEAR


def _is_indeterminate(
    evidence_availability: EvidenceAvailability,
    *,
    no_verifications: bool,
    strongest: RiskSignal | None,
) -> bool:
    """Apply the INDETERMINATE override rules.

    INDETERMINATE means the system cannot establish a sufficiently
    reliable assessment because critical evidence / verification is
    unavailable. It is *uncertainty*, NOT an accusation of risk.

    Rules:

    1. When the bidder has *attempted* verifications (i.e. at least
       one Verification record exists) but no critical required
       capability is verified AND there are no actionable signals
       -> INDETERMINATE. Without a critical capability we cannot
       ground the assessment; but a strong actionable signal alone
       can keep the score-driven state.

    2. When no verifications were attempted at all AND there are no
       signals at all -> CLEAR (nothing to assess, no risk to flag).

    3. The evidence-quality state is UNAVAILABLE (UNKNOWN) AND there
       are no actionable signals -> INDETERMINATE.
    """

    if no_verifications and strongest is None:
        return False

    if not evidence_availability.critical_required_capabilities_present:
        if strongest is None:
            return True

    if (
        evidence_availability.overall_state is EvidenceState.UNAVAILABLE
        and strongest is None
    ):
        return True

    return False


def _severity_reason_code(severity: str) -> str:
    enum_value = _normalize_severity(severity)
    if enum_value is FlagSeverity.CRITICAL:
        return ReasonCode.STRONGEST_CRITICAL_SEVERITY.value
    if enum_value is FlagSeverity.HIGH:
        return ReasonCode.STRONGEST_HIGH_SEVERITY.value
    if enum_value is FlagSeverity.MEDIUM:
        return ReasonCode.STRONGEST_MEDIUM_SEVERITY.value
    if enum_value is FlagSeverity.LOW:
        return ReasonCode.STRONGEST_LOW_SEVERITY.value
    return ReasonCode.STRONGEST_INFO_SEVERITY.value


def collect_reason_codes(
    *,
    risk_state: RiskState,
    strongest: RiskSignal | None,
    supporting_count: int,
    dedup_count: int,
    no_signals: bool,
    evidence_availability: EvidenceAvailability,
    no_verifications: bool,
    indeterminate_overrode_high_risk: bool,
) -> tuple[str, ...]:
    """Return deterministic reason codes for the assessment."""

    codes: list[str] = []
    if no_signals:
        codes.append(ReasonCode.NO_RISK_SIGNALS_PRESENT.value)
    if strongest is not None:
        codes.append(_severity_reason_code(strongest.severity))
    if supporting_count > 0:
        codes.append(ReasonCode.INDEPENDENT_SUPPORTING_SIGNALS.value)
    if dedup_count > 0:
        codes.append(ReasonCode.CORRELATED_SIGNALS_DEDUPLICATED.value)

    if evidence_availability.overall_state is EvidenceState.UNAVAILABLE:
        codes.append(ReasonCode.EVIDENCE_QUALITY_UNKNOWN.value)
    elif evidence_availability.overall_state is EvidenceState.INSUFFICIENT:
        codes.append(ReasonCode.EVIDENCE_QUALITY_DEGRADED.value)

    if no_verifications:
        codes.append(ReasonCode.NO_VERIFICATIONS_PRESENT.value)
    if not evidence_availability.critical_required_capabilities_present:
        codes.append(ReasonCode.CRITICAL_VERIFICATIONS_UNAVAILABLE.value)

    if indeterminate_overrode_high_risk:
        codes.append(ReasonCode.INDETERMINATE_OVERRIDES_HIGH_RISK.value)

    return tuple(codes)


def build_assessment(
    bidder_id: str,
    signals: Iterable[RiskSignal],
    *,
    evidence_availability: EvidenceAvailability,
    no_verifications: bool,
) -> BidderRiskAssessment:
    """Assemble the final BidderRiskAssessment from raw signals."""

    deduped, dedup_count = deduplicate_signals(signals)

    # Separate signals into "actionable" (contribute to score) and
    # "informational" (only expose uncertainty / context).
    actionable_signals: tuple[RiskSignal, ...] = tuple(
        s for s in deduped if s.is_actionable
    )

    strongest = select_strongest_signal(actionable_signals)

    supporting: tuple[RiskSignal, ...] = tuple(
        sorted(
            (
                s
                for s in actionable_signals
                if strongest is None
                or s.correlation_key != strongest.correlation_key
            ),
            key=lambda s: (
                -s.score,
                -_severity_rank(s.severity),
                s.signal_id,
            ),
        )
    )

    no_actionable_signals = len(actionable_signals) == 0
    if strongest is None:
        aggregate_score = 0.0
    else:
        aggregate_score = compute_aggregate_score(strongest, supporting)

    pre_override_score = aggregate_score
    risk_state = determine_risk_state(
        aggregate_score,
        strongest,
        evidence_availability=evidence_availability,
        no_signals=no_actionable_signals,
        no_verifications=no_verifications,
    )

    indeterminate_overrode_high_risk = (
        risk_state is RiskState.INDETERMINATE
        and pre_override_score >= HIGH_RISK_THRESHOLD
    )

    reason_codes = collect_reason_codes(
        risk_state=risk_state,
        strongest=strongest,
        supporting_count=len(supporting),
        dedup_count=dedup_count,
        no_signals=no_actionable_signals,
        evidence_availability=evidence_availability,
        no_verifications=no_verifications,
        indeterminate_overrode_high_risk=indeterminate_overrode_high_risk,
    )

    return BidderRiskAssessment(
        bidder_id=bidder_id,
        risk_state=risk_state,
        aggregate_score=_clamp(aggregate_score),
        signals=deduped,
        strongest_signal=strongest,
        supporting_signals=supporting,
        deduplicated_signal_count=dedup_count,
        evidence_availability=evidence_availability,
        reason_codes=reason_codes,
        summary="",
    )


__all__ = [
    "build_assessment",
    "compute_aggregate_score",
    "deduplicate_signals",
    "determine_risk_state",
    "select_strongest_signal",
]
