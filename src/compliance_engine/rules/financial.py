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
    FinancialRequirementParams,
    determine_focus,
    evaluate,
    normalize_financial_profile,
    outcome_to_compliance_result,
)
from compliance_engine.financial.outcome import FinancialOutcome
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
