"""Financial capacity rule.

Provider-free rule that turns canonical Evidence into a ComplianceResult
for a single tender-derived financial requirement. The rule selects one
financial check per requirement (turnover, net worth, solvency, audit,
balance sheet) from the requirement parameters and delegates the
deterministic evaluation to the financial package.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from compliance_engine.financial import (
    FinancialCheck,
    FinancialRequirementParams,
    check_financial_consistency,
    consistency_finding_to_verification_finding,
    determine_focus,
    evaluate,
    normalize_financial_profile,
    outcome_to_compliance_result,
)
from compliance_engine.financial.outcome import FinancialOutcome
from compliance_engine.financial.trend import (
    TrendAnomaly,
    detect_turnover_trend_anomaly,
)
from compliance_engine.financial.findings import (
    trend_anomaly_to_verification_finding,
)
from compliance_engine.flags import get_flag_definition
from compliance_engine.models import (
    Capability,
    ComplianceResult,
    ComplianceStatus,
    Evidence,
    Requirement,
)


_RULE_ID = "FINANCIAL_CAPACITY_001"


class FinancialCapacityRule:
    """Provider-free Financial Capacity rule."""

    rule_id = _RULE_ID
    name = "Financial capacity verification"
    required_providers: tuple = ()

    def evaluate(
        self,
        evidence: list[Evidence],
        *args: Any,
        requirement: Requirement | None = None,
        provider: Any | None = None,
        **kwargs: Any,
    ) -> ComplianceResult:
        if requirement is None:
            raise ValueError("requirement is required for FinancialCapacityRule.evaluate")

        # Parameters: parse strictly (extra="forbid" surfaces typos).
        try:
            params = FinancialRequirementParams.model_validate(
                requirement.parameters or {}
            )
        except ValidationError as exc:
            return _unknown_config_result(
                requirement,
                f"Financial requirement parameters are invalid: {exc.errors()}.",
            )

        focus = determine_focus(params)
        if focus is None:
            return ComplianceResult(
                requirement_id=requirement.requirement_id,
                capability=requirement.capability,
                status=ComplianceStatus.NOT_CHECKED,
                reason=(
                    "Cannot determine which financial check this requirement "
                    "asks for: parameters are missing or ambiguous."
                ),
                expected=requirement.expected,
                actual=None,
                evidence_refs=[],
                verification_refs=[],
                flags=[],
                rule_id=requirement.rule_id,
            )

        try:
            profile = normalize_financial_profile(evidence)
        except Exception as exc:
            return _unknown_config_result(requirement, str(exc))

        outcome: FinancialOutcome = evaluate(params, profile, focus=focus)
        result = outcome_to_compliance_result(outcome, requirement)

        # If the primary check produced no real evidence, surface a
        # high-level missing flag so downstream risk aggregation still
        # observes the gap.
        if result.status is ComplianceStatus.MISSING and not result.flags:
            result = result.model_copy(
                update={
                    "flags": [
                        get_flag_definition("FINANCIAL_CAPACITY_MISSING").flag_id
                    ]
                }
            )

        return result

    def run_extra_checks(
        self,
        bidder_id: str,
        evidence: list[Evidence],
    ) -> list:
        """Return cross-document consistency and trend findings.

        These are not ComplianceResults; they are VerificationFindings
        ready for the AI verification engine. The orchestrator can call
        this after the primary rule has run.
        """

        profile = normalize_financial_profile(evidence)
        findings = []

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


def _unknown_config_result(requirement: Requirement, detail: str) -> ComplianceResult:
    return ComplianceResult(
        requirement_id=requirement.requirement_id,
        capability=requirement.capability,
        status=ComplianceStatus.NOT_CHECKED,
        reason=detail,
        expected=requirement.expected,
        actual=None,
        evidence_refs=[],
        verification_refs=[],
        flags=[],
        rule_id=requirement.rule_id,
    )


__all__ = ["FinancialCapacityRule"]
