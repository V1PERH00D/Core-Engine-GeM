"""DigiLocker document verification rule (``DIGILOCKER_VERIFICATION_001``).

DigiLocker establishes provenance/authenticity of a retrieved digital
document. It is *not* a generic compliance authority. The rule only:

* verifies the referenced document resolves/verifies,
* compares its issuer / document type / integrity hash against explicitly
  configured requirements,
* never turns an unavailable DigiLocker source into a negative compliance
  result.

Only explicitly configured parameters are checked; no sensitive personal
identifier is stored or derived.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from compliance_engine.anomalies.identity import normalize_identity_name
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


class DigiLockerParameters(BaseModel):
    """Typed, explicit DigiLocker requirement parameters (``extra="forbid"``)."""

    model_config = ConfigDict(extra="forbid")

    require_verified_document: bool | None = None
    required_issuer: str | None = None
    required_document_type: str | None = None


def _flag(flag_id: str) -> str:
    return get_flag_definition(flag_id).flag_id


_DIGILOCKER_DOC_TYPES = {"DIGILOCKER", "DIGILOCKER_DOCUMENT", "DIGITAL_DOCUMENT"}

_INVALID_FLAG_BY_RESULT = {
    "SIGNATURE_INVALID": "DIGITAL_DOCUMENT_SIGNATURE_INVALID",
    "HASH_MISMATCH": "DIGITAL_DOCUMENT_HASH_MISMATCH",
    "REVOKED": "DIGITAL_DOCUMENT_REVOKED",
    "EXPIRED": "DIGITAL_DOCUMENT_EXPIRED",
    "ISSUER_NOT_RECOGNIZED": "ISSUING_AUTHORITY_NOT_RECOGNIZED",
}


class DigiLockerVerificationRule(Rule):
    """Evaluate a DigiLocker-referenced document against tender requirements."""

    rule_id = "DIGILOCKER_VERIFICATION_001"
    name = "DigiLocker document verification"
    required_providers = (Capability.DIGILOCKER,)

    def evaluate(
        self,
        evidence: list[Evidence],
        provider: VerificationProvider | None = None,
        requirement: Requirement | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ComplianceResult:
        if provider is None:
            raise ValueError("provider is required for DigiLockerVerificationRule.evaluate")
        if requirement is None:
            raise ValueError("requirement is required for DigiLockerVerificationRule.evaluate")

        access_id = next(
            (
                item
                for item in evidence
                if item.field_name == "document_access_id"
                and item.document_type.upper() in _DIGILOCKER_DOC_TYPES
            ),
            None,
        )
        if access_id is None:
            return self._missing(requirement, evidence_refs=[])
        if access_id.value is None:
            return self._missing(requirement, evidence_refs=[access_id.evidence_id])

        verification = provider.verify(access_id.bidder_id, str(access_id.value))
        verification = verification.model_copy(
            update={
                "evidence_id": access_id.evidence_id,
                "document_id": access_id.document_id,
            }
        )
        register = getattr(provider, "register", None)
        if callable(register):
            register(verification)

        if verification.status is not VerificationStatus.VERIFIED:
            return self._provider_outcome(requirement, verification, access_id)

        params = DigiLockerParameters(**(requirement.parameters or {}))
        return self._interpret_verified(
            requirement, verification, access_id, params, evidence
        )

    # -- helpers ---------------------------------------------------------

    def _provider_outcome(
        self,
        requirement: Requirement,
        verification: Verification,
        access_id: Evidence,
    ) -> ComplianceResult:
        if verification.status is VerificationStatus.INVALID:
            result = verification.data.get("verification_result")
            flag_id = str(
                _INVALID_FLAG_BY_RESULT.get(result, "DIGITAL_SIGNATURE_VERIFICATION_FAILED")
            )
            return self._result(
                requirement, ComplianceStatus.FAIL,
                "The referenced digital document failed verification in the source.",
                verification, access_id, flags=[_flag(flag_id)],
            )
        if verification.status is VerificationStatus.NOT_FOUND:
            return self._result(
                requirement, ComplianceStatus.UNVERIFIABLE,
                "The digital document was not found in the source, so it could not be verified.",
                verification, access_id, flags=[_flag("DIGITAL_DOCUMENT_NOT_FOUND")],
            )
        return self._result(
            requirement, ComplianceStatus.UNVERIFIABLE,
            "The DigiLocker verification source is unavailable or errored, so the document could not be verified.",
            verification, access_id, flags=[_flag("DIGILOCKER_VERIFICATION_UNAVAILABLE")],
        )

    def _interpret_verified(
        self,
        requirement: Requirement,
        verification: Verification,
        access_id: Evidence,
        params: DigiLockerParameters,
        evidence: list[Evidence],
    ) -> ComplianceResult:
        data = verification.data

        if params.required_issuer is not None:
            if normalize_identity_name(data.get("issuer")) != normalize_identity_name(
                params.required_issuer
            ):
                return self._result(
                    requirement, ComplianceStatus.FAIL,
                    "The document issuer does not match the required issuing authority.",
                    verification, access_id, flags=[_flag("ISSUING_AUTHORITY_INVALID")],
                )

        if params.required_document_type is not None and not self._token_match(
            data.get("document_type"), params.required_document_type
        ):
            return self._result(
                requirement, ComplianceStatus.FAIL,
                "The document type does not match the required document type.",
                verification, access_id, flags=[],
            )

        if data.get("document_hash") is not None:
            evidence_hash = self._evidence_hash(evidence)
            if evidence_hash is not None and evidence_hash != str(data["document_hash"]):
                return self._result(
                    requirement, ComplianceStatus.FAIL,
                    "The supplied document hash does not match the source hash.",
                    verification, access_id, flags=[_flag("DIGITAL_DOCUMENT_HASH_MISMATCH")],
                )

        return self._result(
            requirement, ComplianceStatus.PASS,
            "The referenced digital document was verified and meets the configured requirements.",
            verification, access_id, flags=[],
        )

    @staticmethod
    def _token_match(provided: Any, required: str) -> bool:
        if provided is None:
            return False
        return required.casefold() in str(provided).casefold()

    @staticmethod
    def _evidence_hash(evidence: list[Evidence]) -> str | None:
        for item in evidence:
            if item.field_name == "document_hash" and item.value is not None:
                return str(item.value)
        return None

    def _result(
        self,
        requirement: Requirement,
        status: ComplianceStatus,
        reason: str,
        verification: Verification,
        access_id: Evidence,
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
            evidence_refs=[access_id.evidence_id],
            verification_refs=[verification.verification_id],
            flags=flags,
            rule_id=requirement.rule_id,
        )

    def _missing(self, requirement: Requirement, *, evidence_refs: list[str]) -> ComplianceResult:
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=ComplianceStatus.MISSING,
            reason="Digital document evidence is missing, so document verification cannot be evaluated.",
            expected=requirement.expected,
            actual=None,
            evidence_refs=evidence_refs,
            verification_refs=[],
            flags=[_flag("REQUIRED_FIELD_MISSING")],
            rule_id=requirement.rule_id,
        )


__all__ = ["DigiLockerParameters", "DigiLockerVerificationRule"]