"""Convert financial outcomes and findings into engine artefacts.

* :func:`outcome_to_compliance_result` maps a :class:`FinancialOutcome`
  onto the generic :class:`ComplianceResult` consumed by the executor
  and risk engine.
* :func:`consistency_finding_to_verification_finding` and
  :func:`trend_anomaly_to_verification_finding` map financial-only
  results onto the AI-verification :class:`VerificationFinding` contract
  so financial signals flow into :class:`BidderRiskEngine` unchanged.
"""

from __future__ import annotations

from compliance_engine.flags import get_flag_definition
from compliance_engine.models import ComplianceResult, Requirement

from ai_verification.models.contracts import VerificationFinding

from compliance_engine.financial.consistency import ConsistencyFinding
from compliance_engine.financial.models import Confidence
from compliance_engine.financial.outcome import FinancialOutcome
from compliance_engine.financial.trend import TrendAnomaly


def outcome_to_compliance_result(
    outcome: FinancialOutcome,
    requirement: Requirement,
) -> ComplianceResult:
    """Map a financial outcome onto a :class:`ComplianceResult`."""

    return ComplianceResult(
        requirement_id=requirement.requirement_id,
        capability=requirement.capability,
        status=outcome.status,
        reason=outcome.reason,
        expected=outcome.expected,
        actual=outcome.actual,
        evidence_refs=list(outcome.evidence_refs),
        verification_refs=[],
        flags=list(outcome.flags),
        rule_id=requirement.rule_id,
    )


def _confidence(confidence: Confidence | None) -> float:
    return confidence if confidence is not None else 0.9


def consistency_finding_to_verification_finding(
    bidder_id: str,
    finding: ConsistencyFinding,
) -> VerificationFinding:
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


__all__ = [
    "consistency_finding_to_verification_finding",
    "outcome_to_compliance_result",
    "trend_anomaly_to_verification_finding",
]