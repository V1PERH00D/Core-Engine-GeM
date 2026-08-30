"""Udyam registration validity rule."""

from __future__ import annotations

from typing import Any

from compliance_engine.flags import get_flag_definition
from compliance_engine.models import (
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
    VerificationStatus.INACTIVE: "UDYAM_INACTIVE",
    VerificationStatus.INVALID: "UDYAM_INVALID",
    VerificationStatus.NOT_FOUND: "UDYAM_NOT_FOUND",
    VerificationStatus.UNAVAILABLE: "UDYAM_VERIFICATION_UNAVAILABLE",
    VerificationStatus.ERROR: "UDYAM_VERIFICATION_UNAVAILABLE",
}

_REASONS = {
    VerificationStatus.VERIFIED: (
        "Udyam registration was verified successfully by the authoritative source and is active."
    ),
    VerificationStatus.INACTIVE: (
        "Udyam registration is inactive according to the authoritative source."
    ),
    VerificationStatus.INVALID: (
        "Udyam registration number is invalid according to the authoritative source."
    ),
    VerificationStatus.NOT_FOUND: (
        "Udyam registration was not found in the authoritative source, so it could not be verified."
    ),
    VerificationStatus.UNAVAILABLE: (
        "The Udyam verification source is unavailable, so registration validity could not be confirmed."
    ),
    VerificationStatus.ERROR: (
        "The Udyam verification source returned an error, so registration validity could not be confirmed."
    ),
}


class UdyamRegistrationRule(Rule):
    """Evaluate whether the submitted Udyam registration is valid and active."""

    rule_id = "UDYAM_REGISTRATION_001"
    name = "Udyam registration validity"
    required_providers = (Capability.UDYAM,)

    def evaluate(
        self,
        evidence: list[Evidence],
        provider: VerificationProvider | None = None,
        requirement: Requirement | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ComplianceResult:
        """Return a compliance result for Udyam registration validity only."""

        if provider is None:
            raise ValueError("provider is required for UdyamRegistrationRule.evaluate")
        if requirement is None:
            raise ValueError("requirement is required for UdyamRegistrationRule.evaluate")

        udyam = next(
            (
                item
                for item in evidence
                if item.document_type == "UDYAM" and item.field_name == "udyam_registration_number"
            ),
            None,
        )
        if udyam is None:
            return self._missing(
                requirement,
                reason="Udyam registration evidence is missing, so validity cannot be evaluated.",
                evidence_refs=[],
            )
        if udyam.value is None:
            return self._missing(
                requirement,
                reason="Udyam registration evidence is present but the extracted value is null, so validity cannot be evaluated.",
                evidence_refs=[udyam.evidence_id],
            )

        verification = provider.verify(udyam.bidder_id, str(udyam.value))
        status = _PROVIDER_TO_COMPLIANCE[verification.status]
        flag_id = _FLAG_BY_STATUS.get(verification.status)
        flags = [] if flag_id is None else [get_flag_definition(flag_id).flag_id]

        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=status,
            reason=self._reason(verification.status),
            expected=requirement.expected,
            actual=self._actual(verification),
            evidence_refs=[udyam.evidence_id],
            verification_refs=[verification.verification_id],
            flags=flags,
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
            flags=[get_flag_definition("REQUIRED_FIELD_MISSING").flag_id],
            rule_id=requirement.rule_id,
        )

    def _reason(self, verification_status: VerificationStatus) -> str:
        return _REASONS[verification_status]

    def _actual(self, verification: Verification) -> dict[str, Any]:
        return {
            "status": verification.status,
            "data": verification.data,
        }
