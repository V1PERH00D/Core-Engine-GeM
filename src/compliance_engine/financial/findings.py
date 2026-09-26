"""Convert financial outcomes into engine artefacts.

:func:`outcome_to_compliance_result` maps a :class:`FinancialOutcome`
onto the generic :class:`ComplianceResult` consumed by the executor
and risk engine.

The mapping of financial-only results (``ConsistencyFinding``,
``TrendAnomaly``) onto the downstream AI-verification
``VerificationFinding`` contract lives outside the Compliance Engine,
in the downstream ``ai_verification.financial_bridge`` module.
"""

from __future__ import annotations

from compliance_engine.models import ComplianceResult, Requirement

from compliance_engine.financial.outcome import FinancialOutcome


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


__all__ = [
    "outcome_to_compliance_result",
]
