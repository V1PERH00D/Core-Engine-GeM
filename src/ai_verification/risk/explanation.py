"""Deterministic explanation builder.

The risk engine never uses an LLM for explanation. The summary is
derived strictly from facts actually present in the
:class:`BidderRiskAssessment`. It does *not* claim intent, fraud,
collusion, or illegality.

Output structure
----------------

The explanation exposes:

* the risk state,
* the aggregate score,
* the strongest contributing signal,
* a deterministic human-readable summary line,
* an enumeration of the strongest + supporting signals.

All text is generated from facts in the assessment -- no fabricated
identifiers, no claims about intent.
"""

from __future__ import annotations

from typing import Iterable

from .models import BidderRiskAssessment, EvidenceState, RiskSignal, RiskState


def render_summary(assessment: BidderRiskAssessment) -> str:
    """Render a deterministic human-readable summary.

    Returns a single-line audit-safe sentence that summarises the
    risk state, the aggregate score, and the strongest contributing
    signal when there is one.

    Examples::

        "Bidder bidder-1: HIGH_RISK (score 0.81) driven by a HIGH-
         severity cross-bidder document reuse signal."

        "Bidder bidder-1: REVIEW (score 0.42) driven by a MEDIUM-
         severity cross-source identity mismatch; 1 supporting signal."

        "Bidder bidder-1: INDETERMINATE; critical verification was
         unavailable."

        "Bidder bidder-1: CLEAR."
    """

    parts: list[str] = []

    parts.append(f"Bidder {assessment.bidder_id}: {assessment.risk_state.value}")

    if assessment.aggregate_score > 0.0:
        parts.append(
            f"(score {assessment.aggregate_score:.4f})"
        )

    strongest = assessment.strongest_signal
    supporting = assessment.supporting_signals
    dedup = assessment.deduplicated_signal_count

    if strongest is not None:
        parts.append(
            f"driven by a {_severity_phrase(strongest.severity)}-"
            f"severity {_category_phrase(strongest.category)} signal"
        )
    elif assessment.risk_state is RiskState.INDETERMINATE:
        if assessment.evidence_availability.overall_state is EvidenceState.UNAVAILABLE:
            parts.append("critical verification was unavailable")
        elif not assessment.evidence_availability.critical_required_capabilities_present:
            parts.append("critical required evidence is missing")
        else:
            parts.append("insufficient evidence for a reliable assessment")
    elif assessment.risk_state is RiskState.CLEAR:
        parts.append("no material risk-relevant evidence found")

    if len(supporting) > 0:
        plural = "s" if len(supporting) != 1 else ""
        parts.append(f"{len(supporting)} supporting signal{plural}")

    if dedup > 0:
        plural = "s" if dedup != 1 else ""
        parts.append(f"{dedup} correlated duplicate{plural} suppressed")

    return "; ".join(parts) + "."


def render_summary_per_signal(
    signals: Iterable[RiskSignal],
) -> list[str]:
    """Return a one-line description of each signal.

    The descriptions are deterministic and contain only the IDs that
    are already on the signal -- no fabricated identifiers.
    """

    return [_describe_signal(s) for s in sorted(signals, key=lambda x: x.signal_id)]


def _severity_phrase(severity: str) -> str:
    return str(severity).lower()


def _category_phrase(category: str) -> str:
    value = str(category).lower()
    return value.replace("_", " ")


def _describe_signal(signal: RiskSignal) -> str:
    refs: list[str] = []
    if signal.finding_refs:
        refs.append("findings=" + ",".join(signal.finding_refs))
    if signal.verification_refs:
        refs.append("verifications=" + ",".join(signal.verification_refs))
    if signal.evidence_refs:
        refs.append("evidence=" + ",".join(signal.evidence_refs))
    if signal.document_refs:
        refs.append("documents=" + ",".join(signal.document_refs))
    if signal.related_bidder_ids:
        refs.append("related_bidders=" + ",".join(signal.related_bidder_ids))
    refs_str = " ".join(refs)
    return (
        f"[{signal.signal_id}] category={signal.category.value} "
        f"severity={signal.severity} score={signal.score:.4f} "
        f"confidence={signal.confidence:.4f} "
        f"actionable={signal.is_actionable} reason={signal.reason_code} "
        f"refs=[{refs_str}]"
    )


__all__ = ["render_summary", "render_summary_per_signal"]