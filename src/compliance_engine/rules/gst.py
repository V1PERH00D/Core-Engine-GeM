"""GST registration validity rule."""

from typing import Any

from compliance_engine.flags import GSTIN_MISSING
from compliance_engine.models import (
    Capability,
    ComplianceResult,
    ComplianceStatus,
    Evidence,
    Requirement,
    Verification,
    VerificationStatus,
)
from compliance_engine.rules.base import Rule
from compliance_engine.verification import VerificationProvider

_PROVIDER_TO_COMPLIANCE = {
    VerificationStatus.VERIFIED: ComplianceStatus.PASS,
    VerificationStatus.INACTIVE: ComplianceStatus.FAIL,
    VerificationStatus.INVALID: ComplianceStatus.FAIL,
    VerificationStatus.NOT_FOUND: ComplianceStatus.UNVERIFIABLE,
    VerificationStatus.UNAVAILABLE: ComplianceStatus.UNVERIFIABLE,
    VerificationStatus.ERROR: ComplianceStatus.UNVERIFIABLE,
}

_REASONS = {
    ComplianceStatus.PASS: (
        "GST registration was verified as valid and active by the authoritative source."
    ),
    VerificationStatus.INACTIVE: (
        "GST registration is inactive according to the authoritative source."
    ),
    VerificationStatus.INVALID: (
        "GSTIN is invalid according to the authoritative source."
    ),
    VerificationStatus.NOT_FOUND: (
        "GSTIN was not found in the authoritative source, so registration "
        "could not be verified."
    ),
    VerificationStatus.UNAVAILABLE: (
        "The GST verification source is unavailable, so registration "
        "could not be verified."
    ),
    VerificationStatus.ERROR: (
        "The GST verification source returned an error, so registration "
        "could not be verified."
    ),
}


class GSTRegistrationRule(Rule):
    """Evaluate whether GST registration is valid and active."""

    rule_id = "GST_REGISTRATION_001"
    name = "GST registration validity"
    required_providers = (Capability.GST,)

    def evaluate(
        self,
        evidence: list[Evidence],
        provider: VerificationProvider | None = None,
        requirement: Requirement | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ComplianceResult:
        """Return a compliance result for GST registration status only."""

        if provider is None:
            raise ValueError("provider is required for GSTRegistrationRule.evaluate")
        if requirement is None:
            raise ValueError("requirement is required for GSTRegistrationRule.evaluate")

        gstin = next(
            (
                item
                for item in evidence
                if item.document_type == "GST" and item.field_name == "gstin"
            ),
            None,
        )
        if gstin is None:
            return self._missing(
                requirement,
                reason="GSTIN evidence is missing, so GST registration cannot be evaluated.",
                evidence_refs=[],
            )
        if gstin.value is None:
            return self._missing(
                requirement,
                reason=(
                    "GSTIN evidence is present but the extracted value is null, "
                    "so GST registration cannot be evaluated."
                ),
                evidence_refs=[gstin.evidence_id],
            )

        verification = provider.verify(gstin.bidder_id, str(gstin.value))
        status = _PROVIDER_TO_COMPLIANCE[verification.status]
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=status,
            reason=self._reason(verification, status),
            expected=requirement.expected,
            actual=self._actual(verification),
            evidence_refs=[gstin.evidence_id],
            verification_refs=[verification.verification_id],
            flags=[],
            rule_id=requirement.rule_id,
        )

    def _missing(
        self,
        requirement: Requirement,
        reason: str,
        evidence_refs: list[str],
    ) -> ComplianceResult:
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=ComplianceStatus.MISSING,
            reason=reason,
            expected=requirement.expected,
            actual=None,
            evidence_refs=evidence_refs,
            verification_refs=[],
            flags=[GSTIN_MISSING],
            rule_id=requirement.rule_id,
        )

    def _reason(self, verification: Verification, status: ComplianceStatus) -> str:
        if status is ComplianceStatus.PASS:
            return _REASONS[ComplianceStatus.PASS]
        return _REASONS[verification.status]

    def _actual(self, verification: Verification) -> dict[str, Any]:
        return {
            "status": verification.status,
            "data": verification.data,
        }
