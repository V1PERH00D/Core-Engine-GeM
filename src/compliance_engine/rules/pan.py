"""PAN validation rule."""

from __future__ import annotations

from typing import Any

from compliance_engine.flags import get_flag_definition
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
from compliance_engine.verification.base import VerificationProvider

_PROVIDER_TO_COMPLIANCE = {
    VerificationStatus.VERIFIED: ComplianceStatus.PASS,
    VerificationStatus.INACTIVE: ComplianceStatus.FAIL,
    VerificationStatus.INVALID: ComplianceStatus.FAIL,
    VerificationStatus.NOT_FOUND: ComplianceStatus.UNVERIFIABLE,
    VerificationStatus.UNAVAILABLE: ComplianceStatus.UNVERIFIABLE,
    VerificationStatus.ERROR: ComplianceStatus.UNVERIFIABLE,
}

_FLAG_BY_STATUS = {
    VerificationStatus.VERIFIED: None,
    VerificationStatus.INACTIVE: "PAN_INACTIVE",
    VerificationStatus.INVALID: "PAN_INVALID",
    VerificationStatus.NOT_FOUND: "PAN_NOT_FOUND",
    VerificationStatus.UNAVAILABLE: "PAN_VERIFICATION_UNAVAILABLE",
    VerificationStatus.ERROR: "PAN_VERIFICATION_UNAVAILABLE",
}

_REASONS = {
    VerificationStatus.VERIFIED: (
        "PAN was verified successfully by the authoritative source and is active."
    ),
    VerificationStatus.INACTIVE: (
        "PAN is inactive according to the authoritative source."
    ),
    VerificationStatus.INVALID: (
        "PAN is invalid according to the authoritative source."
    ),
    VerificationStatus.NOT_FOUND: (
        "PAN was not found in the authoritative source, so it could not be verified."
    ),
    VerificationStatus.UNAVAILABLE: (
        "The PAN verification source is unavailable, so PAN validity could not be confirmed."
    ),
    VerificationStatus.ERROR: (
        "The PAN verification source returned an error, so PAN validity could not be confirmed."
    ),
}


class PANValidationRule(Rule):
    """Evaluate whether a submitted PAN is valid and active."""

    rule_id = "PAN_VALIDATION_001"
    name = "PAN validity"
    required_providers = (Capability.PAN_INCOME_TAX,)

    def evaluate(
        self,
        evidence: list[Evidence],
        provider: VerificationProvider | None = None,
        requirement: Requirement | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ComplianceResult:
        """Return a compliance result for PAN validity only."""

        if provider is None:
            raise ValueError("provider is required for PANValidationRule.evaluate")
        if requirement is None:
            raise ValueError("requirement is required for PANValidationRule.evaluate")

        pan = next(
            (
                item
                for item in evidence
                if item.document_type == "PAN" and item.field_name == "pan_number"
            ),
            None,
        )
        if pan is None:
            return self._missing(
                requirement,
                reason="PAN evidence is missing, so PAN validity cannot be evaluated.",
                evidence_refs=[],
            )
        if pan.value is None:
            return self._missing(
                requirement,
                reason="PAN evidence is present but the extracted value is null, so PAN validity cannot be evaluated.",
                evidence_refs=[pan.evidence_id],
            )

        verification = provider.verify(pan.bidder_id, str(pan.value))
        status = _PROVIDER_TO_COMPLIANCE[verification.status]
        flag_id = _FLAG_BY_STATUS.get(verification.status)
        if flag_id is not None:
            flag = get_flag_definition(flag_id).flag_id
        else:
            flag = None

        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=status,
            reason=self._reason(verification.status),
            expected=requirement.expected,
            actual=self._actual(verification),
            evidence_refs=[pan.evidence_id],
            verification_refs=[verification.verification_id],
            flags=[] if flag is None else [flag],
            rule_id=requirement.rule_id,
        )

    def _missing(
        self,
        requirement: Requirement,
        reason: str,
        evidence_refs: list[str],
    ) -> ComplianceResult:
        flag = get_flag_definition("REQUIRED_FIELD_MISSING").flag_id
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=ComplianceStatus.MISSING,
            reason=reason,
            expected=requirement.expected,
            actual=None,
            evidence_refs=evidence_refs,
            verification_refs=[],
            flags=[flag],
            rule_id=requirement.rule_id,
        )

    def _reason(self, verification_status: VerificationStatus) -> str:
        return _REASONS[verification_status]

    def _actual(self, verification: Verification) -> dict[str, Any]:
        return {
            "status": verification.status,
            "data": verification.data,
        }
