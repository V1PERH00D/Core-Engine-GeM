"""MCA21 company registration compliance rule (rule id ``MCA21_REGISTRATION_001``).

The rule consumes a ``Verification`` produced by :class:`McaAdapter` and emits a
:class:`ComplianceResult`. It keeps the architecture's distinction:
provider status is *not* compliance status. A provider ``UNAVAILABLE``/``ERROR``
is ``UNVERIFIABLE``; ``NOT_FOUND`` is ``UNVERIFIABLE``; ``VERIFIED`` is PASS;
``INACTIVE``/``INVALID`` are FAIL with the appropriate flags.

Only explicitly configured parameters are checked:

- ``require_registration``: when explicitly ``False`` the requirement is
  NOT_APPLICABLE.
- ``required_status``: when explicitly set (e.g. ``"ACTIVE"``) a verified
  registration whose normalized data reports a contradicting company
  status is a deterministic FAIL with the appropriate registry flag.

"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

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


class McaParameters(BaseModel):
    """Typed, explicit MCA21 requirement parameters (``extra="forbid"``).

    Only explicitly configured parameters are checked.
    """

    model_config = ConfigDict(extra="forbid")

    require_registration: bool | None = None
    required_status: str | None = None  # e.g. "ACTIVE"


def _flag(flag_id: str) -> str:
    return get_flag_definition(flag_id).flag_id


_PROVIDER_TO_COMPLIANCE = {
    VerificationStatus.VERIFIED: ComplianceStatus.PASS,
    VerificationStatus.INACTIVE: ComplianceStatus.FAIL,
    VerificationStatus.INVALID: ComplianceStatus.FAIL,
    VerificationStatus.NOT_FOUND: ComplianceStatus.UNVERIFIABLE,
    VerificationStatus.UNAVAILABLE: ComplianceStatus.UNVERIFIABLE,
    VerificationStatus.ERROR: ComplianceStatus.UNVERIFIABLE,
}

_MCA_DOC_TYPES = {"MCA", "MCA21", "MCA21_REGISTRATION", "COMPANY_REGISTRATION"}

_FLAG_BY_STATUS = {
    VerificationStatus.VERIFIED: None,
    VerificationStatus.INACTIVE: "COMPANY_INACTIVE",
    VerificationStatus.INVALID: "CIN_INVALID",
    VerificationStatus.NOT_FOUND: "CIN_NOT_FOUND",
    VerificationStatus.UNAVAILABLE: "MCA_VERIFICATION_UNAVAILABLE",
    VerificationStatus.ERROR: "MCA_VERIFICATION_UNAVAILABLE",
}

# Reported company-status value -> registry flag, used when an explicitly
# configured ``required_status`` is contradicted by the normalized data.
_STATUS_FLAG_BY_REPORTED = {
    "INACTIVE": "COMPANY_INACTIVE",
    "STRIKE_OFF": "COMPANY_STRIKE_OFF",
    "UNDER_LIQUIDATION": "COMPANY_UNDER_LIQUIDATION",
}


def _find_cin_evidence(evidence: list[Evidence]) -> Evidence | None:
    for item in evidence:
        if (
            item.document_type.upper() in _MCA_DOC_TYPES
            and item.field_name == "cin"
        ):
            return item
    return None


class McaRegistrationRule(Rule):
    """Evaluate MCA21 company registration against configured requirements."""

    rule_id = "MCA21_REGISTRATION_001"
    name = "MCA21 company registration verification"
    required_providers = (Capability.MCA21,)

    def evaluate(
        self,
        evidence: list[Evidence],
        provider: VerificationProvider | None = None,
        requirement: Requirement | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ComplianceResult:
        """Evaluate MCA21 registration against configured requirements."""
        if provider is None:
            raise ValueError("provider is required for McaRegistrationRule.evaluate")
        if requirement is None:
            raise ValueError("requirement is required for McaRegistrationRule.evaluate")

        params = McaParameters(**(requirement.parameters or {}))

        if params.require_registration is False:
            return self._not_applicable(requirement)

        cin_evidence = _find_cin_evidence(evidence)
        if cin_evidence is None:
            return self._missing(requirement)
        if cin_evidence.value is None:
            return self._missing(requirement, evidence_refs=[cin_evidence.evidence_id])

        verification = provider.verify(cin_evidence.bidder_id, str(cin_evidence.value))
        verification = verification.model_copy(
            update={
                "evidence_id": cin_evidence.evidence_id,
                "document_id": cin_evidence.document_id,
            }
        )

        status = _PROVIDER_TO_COMPLIANCE[verification.status]
        flag_id = _FLAG_BY_STATUS.get(verification.status)

        # Explicitly configured status requirement: when the tender requires a
        # specific company status (e.g. "ACTIVE") and the verification PASSed,
        # a contradicting reported status in the normalized data is a
        # deterministic compliance failure (contradictory evidence).
        if params.required_status is not None and status is ComplianceStatus.PASS:
            reported = verification.data.get("company_status")
            if reported is not None and str(reported) != params.required_status:
                contradiction_flag = _STATUS_FLAG_BY_REPORTED.get(
                    str(reported), "COMPANY_INACTIVE"
                )
                return self._result(
                    requirement,
                    status=ComplianceStatus.FAIL,
                    reason=(
                        f"MCA21 company status {reported!r} does not match the "
                        f"required status {params.required_status!r}."
                    ),
                    verification=verification,
                    cin_evidence=cin_evidence,
                    flags=[_flag(contradiction_flag)],
                )

        return self._result(
            requirement,
            status=status,
            reason=self._reason(verification.status),
            verification=verification,
            cin_evidence=cin_evidence,
            flags=[_flag(flag_id)] if flag_id is not None else [],
        )

    def _reason(self, status: VerificationStatus) -> str:
        reasons = {
            VerificationStatus.VERIFIED: (
                "MCA21 company registration was verified as active."
            ),
            VerificationStatus.INACTIVE: (
                "MCA21 company registration is inactive (strike-off/liquidation)."
            ),
            VerificationStatus.INVALID: (
                "CIN is invalid according to the authoritative source."
            ),
            VerificationStatus.NOT_FOUND: (
                "CIN was not found in the MCA21 registry."
            ),
            VerificationStatus.UNAVAILABLE: (
                "MCA21 verification source is unavailable."
            ),
            VerificationStatus.ERROR: (
                "MCA21 verification source returned an error."
            ),
        }
        return reasons.get(
            status,
            "MCA21 verification status could not be determined.",
        )

    def _result(
        self,
        requirement: Requirement,
        status: ComplianceStatus,
        reason: str,
        verification: Verification,
        cin_evidence: Evidence,
        *,
        flags: list[str],
    ) -> ComplianceResult:
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=status,
            reason=reason,
            expected=requirement.expected,
            actual={"status": verification.status, "data": verification.data},
            evidence_refs=[cin_evidence.evidence_id],
            verification_refs=[verification.verification_id],
            flags=flags,
            rule_id=requirement.rule_id,
        )

    def _missing(
        self,
        requirement: Requirement,
        evidence_refs: list[str] | None = None,
    ) -> ComplianceResult:
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=ComplianceStatus.MISSING,
            reason="MCA21/CIN evidence is missing, so company registration cannot be evaluated.",
            expected=requirement.expected,
            actual=None,
            evidence_refs=evidence_refs or [],
            verification_refs=[],
            flags=[_flag("REQUIRED_FIELD_MISSING")],
            rule_id=requirement.rule_id,
        )

    def _not_applicable(self, requirement: Requirement) -> ComplianceResult:
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=ComplianceStatus.NOT_APPLICABLE,
            reason="MCA21 registration is not required for this tender.",
            expected=requirement.expected,
            actual=None,
            evidence_refs=[],
            verification_refs=[],
            flags=[],
            rule_id=requirement.rule_id,
        )


__all__ = ["McaRegistrationRule", "McaParameters"]