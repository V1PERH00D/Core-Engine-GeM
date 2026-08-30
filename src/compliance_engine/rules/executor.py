"""Minimal executor for requirement evaluation using rule implementations."""

from __future__ import annotations

from typing import Any

from compliance_engine.models import (
    Applicability,
    ComplianceResult,
    ComplianceStatus,
    Evidence,
    Requirement,
)
from compliance_engine.rules.base import Rule


class RequirementExecutor:
    """Execute tender requirements using supplied rules and produce ComplianceResult objects.
    
    The executor is a thin orchestration layer:
    - Routes requirements to their corresponding rules
    - Handles NOT_APPLICABLE and UNKNOWN applicability
    - Reports missing rules deterministically
    - Does not contain capability-specific logic
    - Does not perform scoring, risk analysis, or anomaly detection
    """

    def execute(
        self,
        requirements: list[Requirement],
        evidence: list[Evidence],
        rules: dict[str, Rule],
        provider: Any = None,
        **context: Any,
    ) -> list[ComplianceResult]:
        """Execute requirements using supplied rules.
        
        Args:
            requirements: List of normalized Requirement objects
            evidence: List of normalized Evidence objects
            rules: Mapping of rule_id -> Rule instance
            provider: Optional verification provider or context passed to rules
            **context: Additional context passed to rules
        
        Returns:
            List of ComplianceResult objects, one per requirement
        
        Behavior:
        - NOT_APPLICABLE: produces NOT_APPLICABLE result without executing rule
        - UNKNOWN: produces UNVERIFIABLE result without executing rule
        - missing rule: produces NOT_CHECKED result deterministically
        - rule execution errors: propagate (unexpected exceptions expose bugs)
        - provider/source unavailability: handled through VerificationStatus codes
        """
        results = []
        for requirement in requirements:
            if requirement.applicability == Applicability.NOT_APPLICABLE:
                results.append(self._not_applicable_result(requirement))
            elif requirement.applicability == Applicability.UNKNOWN:
                results.append(self._unknown_applicability_result(requirement))
            else:
                rule = rules.get(requirement.rule_id)
                if rule is None:
                    results.append(self._missing_rule_result(requirement))
                else:
                    result = rule.evaluate(
                        evidence,
                        requirement=requirement,
                        provider=provider,
                        **context,
                    )
                    results.append(result)
        return results

    def _not_applicable_result(self, requirement: Requirement) -> ComplianceResult:
        """Produce a NOT_APPLICABLE result for non-applicable requirements."""
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=ComplianceStatus.NOT_APPLICABLE,
            reason="Requirement is not applicable to this bidder or tender.",
            expected=requirement.expected,
            actual=None,
            evidence_refs=[],
            verification_refs=[],
            flags=[],
            rule_id=requirement.rule_id,
        )

    def _unknown_applicability_result(self, requirement: Requirement) -> ComplianceResult:
        """Produce an UNVERIFIABLE result for requirements with unknown applicability.
        
        UNVERIFIABLE is the most appropriate status because applicability
        cannot be determined, not because the requirement was verified to pass.
        """
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=ComplianceStatus.UNVERIFIABLE,
            reason="Requirement applicability is unknown; verification deferred.",
            expected=requirement.expected,
            actual=None,
            evidence_refs=[],
            verification_refs=[],
            flags=[],
            rule_id=requirement.rule_id,
        )

    def _missing_rule_result(self, requirement: Requirement) -> ComplianceResult:
        """Produce a NOT_CHECKED result when no rule is available for the requirement.
        
        NOT_CHECKED is chosen because the requirement was not evaluated
        (there is no rule to evaluate it), but this is not an error condition—
        it is a known limitation: the capability may be unimplemented.
        """
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=ComplianceStatus.NOT_CHECKED,
            reason=f"No rule implementation found for rule_id={requirement.rule_id!r}.",
            expected=requirement.expected,
            actual=None,
            evidence_refs=[],
            verification_refs=[],
            flags=[],
            rule_id=requirement.rule_id,
        )
