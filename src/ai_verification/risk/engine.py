"""Bidder-level risk engine: the public API.

The engine is a thin orchestrator. It accepts already-produced
verification / finding / identity / evidence-quality artefacts and
returns a deterministic BidderRiskAssessment.

The engine never mutates its inputs, never calls the network, and
never invents identifiers.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Sequence

from compliance_engine.models import ComplianceResult, Evidence, IdentityFinding
from compliance_engine.models.verification import (
    Verification,
    VerificationStatus,
)

from ai_verification.cross_bidder.trace import SimilarityTrace
from ai_verification.evidence_quality import EvidenceQualityAssessment
from ai_verification.models.contracts import VerificationFinding

from .aggregation import build_assessment
from .explanation import render_summary
from .models import (
    BidderRiskAssessment,
    EvidenceAvailability,
    EvidenceState,
)
from .signals import (
    availability_signal_from_verifications,
    signal_from_compliance_result,
    signal_from_cross_bidder_finding,
    signal_from_evidence_quality,
    signal_from_identity_finding,
    signal_from_verification_finding,
)


_CRITICAL_CAPABILITIES: tuple[str, ...] = (
    "GST / GSTN",
    "PAN / Income Tax",
    "Bidder Identity",
)


_UNAVAILABLE_STATUSES: frozenset[VerificationStatus] = frozenset({
    VerificationStatus.UNAVAILABLE,
    VerificationStatus.ERROR,
    VerificationStatus.NOT_FOUND,
    VerificationStatus.INVALID,
    VerificationStatus.INACTIVE,
})

class BidderRiskEngine:
    """Deterministic bidder-level risk aggregator.

    Stateless. Safe to construct once and reuse across many assess
    calls.
    """

    def assess(
        self,
        bidder_id: str,
        *,
        compliance_results: Sequence[ComplianceResult] = (),
        verification_records: Sequence[Verification] = (),
        findings: Sequence[VerificationFinding] = (),
        identity_findings: Sequence[IdentityFinding] = (),
        traces: Sequence[SimilarityTrace] = (),
        evidence_quality_assessments: Sequence[EvidenceQualityAssessment] = (),
        evidence: Sequence[Evidence] = (),
        critical_capabilities: tuple[str, ...] = _CRITICAL_CAPABILITIES,
    ) -> BidderRiskAssessment:
        """Run the bidder-level risk aggregation for one bidder."""

        signals: list = []

        for r in compliance_results:
            s = signal_from_compliance_result(bidder_id, r)
            if s is not None:
                signals.append(s)

        for f in identity_findings:
            s = signal_from_identity_finding(bidder_id, f)
            if s is not None:
                signals.append(s)

        for finding in findings:
            trace = _find_trace_for_finding(finding, traces)
            if trace is not None:
                s = signal_from_cross_bidder_finding(
                    bidder_id, finding, trace
                )
                if s is not None:
                    signals.append(s)
                continue
            s = signal_from_verification_finding(bidder_id, finding)
            if s is not None:
                signals.append(s)

        availability = availability_signal_from_verifications(
            bidder_id, verification_records
        )
        if availability is not None:
            signals.append(availability)

        quality_signal = signal_from_evidence_quality(
            bidder_id, evidence_quality_assessments
        )
        if quality_signal is not None:
            signals.append(quality_signal)

        evidence_availability = _build_evidence_availability(
            verification_records=verification_records,
            evidence=evidence,
            critical_capabilities=critical_capabilities,
            evidence_quality_assessments=evidence_quality_assessments,
        )

        assessment = build_assessment(
            bidder_id,
            signals,
            evidence_availability=evidence_availability,
            no_verifications=len(verification_records) == 0,
        )

        summary = render_summary(assessment)
        return assessment.model_copy(update={"summary": summary})


def _find_trace_for_finding(
    finding: VerificationFinding,
    traces: Iterable[SimilarityTrace],
) -> SimilarityTrace | None:
    """Return the trace paired with the given finding, if any.

    The trace is matched by ``left_bidder_id == finding.bidder_id``
    and ``right_bidder_id in finding.related_bidder_ids``. When
    multiple candidates exist the first one encountered wins.
    """

    matches = [
        t
        for t in traces
        if t.left_bidder_id == finding.bidder_id
        and t.right_bidder_id in finding.related_bidder_ids
    ]
    if matches:
        return matches[0]
    candidates = [
        t
        for t in traces
        if finding.bidder_id in (t.left_bidder_id, t.right_bidder_id)
    ]
    if candidates:
        return candidates[0]
    return None


def _build_evidence_availability(
    *,
    verification_records: Sequence[Verification],
    evidence: Sequence[Evidence],
    critical_capabilities: tuple[str, ...],
    evidence_quality_assessments: Sequence[EvidenceQualityAssessment],
) -> EvidenceAvailability:
    """Compute the EvidenceAvailability summary."""

    verified_verifications = sum(
        1 for v in verification_records if v.status is VerificationStatus.VERIFIED
    )
    unavailable_verifications = sum(
        1 for v in verification_records if v.status in _UNAVAILABLE_STATUSES
    )

    verified_capabilities = {
        v.capability
        for v in verification_records
        if v.status is VerificationStatus.VERIFIED
    }
    critical_required_present = all(
        cap in verified_capabilities for cap in critical_capabilities
    )

    verified_evidence_count = len(evidence)
    insufficient_evidence_count = 0
    unavailable_evidence_count = 0

    if evidence_quality_assessments:
        states = Counter(
            a.state.value for a in evidence_quality_assessments
        )
        if states.get("UNKNOWN", 0) > 0:
            overall_state = EvidenceState.UNAVAILABLE
        elif states.get("DEGRADED", 0) > 0:
            overall_state = EvidenceState.INSUFFICIENT
        else:
            overall_state = EvidenceState.VERIFIED
    else:
        if unavailable_verifications > 0 and verified_verifications == 0:
            overall_state = EvidenceState.UNAVAILABLE
        elif unavailable_verifications > 0 or verified_verifications == 0:
            overall_state = EvidenceState.INSUFFICIENT
        else:
            overall_state = EvidenceState.VERIFIED

    return EvidenceAvailability(
        verified_evidence_count=verified_evidence_count,
        insufficient_evidence_count=insufficient_evidence_count,
        unavailable_evidence_count=unavailable_evidence_count,
        verified_verification_count=verified_verifications,
        unavailable_verification_count=unavailable_verifications,
        critical_required_capabilities_present=critical_required_present,
        overall_state=overall_state,
    )


__all__ = ["BidderRiskEngine"]
