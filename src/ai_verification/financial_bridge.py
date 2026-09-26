"""Bridge from Compliance Engine financial signals to AI-verification findings.

This module is DOWNSTREAM code. It may import from the Compliance
Engine (DEPENDENCY DIRECTION: downstream -> CE); the Compliance Engine
itself must never import this module or anything else under
``ai_verification``.

It bridges the Compliance Engine's *financial-only* primitives
(``ConsistencyFinding``, ``TrendAnomaly``) into the AI-verification
:class:`VerificationFinding` contract so financial signals flow into
:class:`BidderRiskEngine` unchanged. It replaces the former
``FinancialCapacityRule.run_extra_checks()`` helper, which created
downstream ``VerificationFinding`` objects inside the engine boundary.
"""

from __future__ import annotations

from compliance_engine.flags import get_flag_definition
from compliance_engine.financial.consistency import (
    ConsistencyFinding,
    check_financial_consistency,
)
from compliance_engine.financial.normalization import normalize_financial_profile
from compliance_engine.financial.trend import (
    TrendAnomaly,
    detect_turnover_trend_anomaly,
)
from compliance_engine.models import Evidence

from ai_verification.models.contracts import VerificationFinding


def consistency_finding_to_verification_finding(
    bidder_id: str,
    finding: ConsistencyFinding,
) -> VerificationFinding:
    """Map a financial consistency finding onto a VerificationFinding."""

    flag_id = finding.flag_id
    severity = get_flag_definition(flag_id).severity
    return VerificationFinding(
        finding_id=(
            f"financial-consistency:{bidder_id}:{finding.metric}:"
            f"{finding.financial_year}:{finding.left_evidence_id}:"
            f"{finding.right_evidence_id}"
        ),
        bidder_id=bidder_id,
        flag_id=flag_id,
        severity=severity,
        confidence=0.9,
        explanation=(
            f"Inconsistent {finding.metric} for {finding.financial_year}: "
            f"₹{finding.left_value:g} crore vs ₹{finding.right_value:g} crore "
            f"({finding.formula})."
        ),
        evidence_refs=[finding.left_evidence_id, finding.right_evidence_id],
        verification_refs=[],
        related_bidder_ids=[],
    )


def trend_anomaly_to_verification_finding(
    bidder_id: str,
    anomaly: TrendAnomaly,
) -> VerificationFinding:
    """Map a turnover trend anomaly onto a VerificationFinding."""

    flag_id = anomaly.flag_id
    severity = get_flag_definition(flag_id).severity
    return VerificationFinding(
        finding_id=f"financial-trend:{bidder_id}:{'-'.join(anomaly.financial_years)}",
        bidder_id=bidder_id,
        flag_id=flag_id,
        severity=severity,
        confidence=0.7,
        explanation=anomaly.reason,
        evidence_refs=list(anomaly.evidence_refs),
        verification_refs=[],
        related_bidder_ids=[],
    )


def collect_financial_verification_findings(
    bidder_id: str,
    evidence: list[Evidence],
) -> list[VerificationFinding]:
    """Collect cross-document consistency and trend findings for a bidder.

    These are not ``ComplianceResult`` objects; they are
    ``VerificationFinding`` objects ready for the AI-verification
    engine. The orchestrator can call this after the
    ``FinancialCapacityRule`` has produced its compliance results.
    """

    profile = normalize_financial_profile(evidence)
    findings: list[VerificationFinding] = []

    for cf in check_financial_consistency(profile):
        findings.append(
            consistency_finding_to_verification_finding(bidder_id, cf)
        )

    anomaly: TrendAnomaly | None = detect_turnover_trend_anomaly(
        profile.annual_turnovers
    )
    if anomaly is not None:
        findings.append(
            trend_anomaly_to_verification_finding(bidder_id, anomaly)
        )

    return findings


__all__ = [
    "collect_financial_verification_findings",
    "consistency_finding_to_verification_finding",
    "trend_anomaly_to_verification_finding",
]
