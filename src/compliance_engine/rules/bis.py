"""BIS / product certification compliance rule (rule id ``BIS_CERTIFICATION_001``).

The rule interprets a ``Verification`` produced by a BIS provider and emits a
boolean-flag ``ComplianceResult``. It keeps the architecture's distinction:
provider status is *not* compliance status. A provider ``UNAVAILABLE``/``ERROR``
is ``UNVERIFIABLE``; a ``NOT_FOUND`` certificate is ``UNVERIFIABLE`` (not an
automatic FAIL); a ``VERIFIED`` payload is *interpreted* against the explicitly
configured requirement parameters.

Only explicitly configured parameters are checked. Validity is computed
against an explicit ``evaluation_date`` (never the machine clock).
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
from compliance_engine.rules._date_helpers import coerce_evaluation_date, parse_date_value
from compliance_engine.rules.base import Rule
from compliance_engine.verification.base import VerificationProvider


class BisParameters(BaseModel):
    """Typed, explicit BIS requirement parameters (``extra="forbid"``)."""

    model_config = ConfigDict(extra="forbid")

    require_bis: bool | None = None
    required_status: str | None = None
    required_standard: str | None = None
    required_product: str | None = None
    required_manufacturer: str | None = None
    required_facility_location: str | None = None
    evaluation_date: str | None = None


def _flag(flag_id: str) -> str:
    return get_flag_definition(flag_id).flag_id


_PROVIDER_TO_COMPLIANCE = {
    VerificationStatus.VERIFIED: ComplianceStatus.PASS,
    VerificationStatus.INVALID: ComplianceStatus.FAIL,
    VerificationStatus.NOT_FOUND: ComplianceStatus.UNVERIFIABLE,
    VerificationStatus.UNAVAILABLE: ComplianceStatus.UNVERIFIABLE,
    VerificationStatus.ERROR: ComplianceStatus.UNVERIFIABLE,
}

_BIS_DOC_TYPES = {"BIS", "BIS_CERTIFICATION", "BIS_PRODUCT_CERTIFICATION"}


def _find_certificate_evidence(evidence: list[Evidence]) -> Evidence | None:
    for item in evidence:
        if (
            item.document_type.upper() in _BIS_DOC_TYPES
            and item.field_name == "certificate_number"
        ):
            return item
    return None


class BisCertificationRule(Rule):
    """Evaluate BIS product certification against configured requirements."""

    rule_id = "BIS_CERTIFICATION_001"
    name = "BIS product certification"
    required_providers = (Capability.BIS,)

    def evaluate(
        self,
        evidence: list[Evidence],
        provider: VerificationProvider | None = None,
        requirement: Requirement | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ComplianceResult:
        if provider is None:
            raise ValueError("provider is required for BisCertificationRule.evaluate")
        if requirement is None:
            raise ValueError("requirement is required for BisCertificationRule.evaluate")

        params = BisParameters(**(requirement.parameters or {}))
        if params.require_bis is False:
            return self._not_applicable(requirement)

        cert_evidence = _find_certificate_evidence(evidence)
        if cert_evidence is None:
            return self._missing(requirement, evidence_refs=[])
        if cert_evidence.value is None:
            return self._missing(requirement, evidence_refs=[cert_evidence.evidence_id])

        verification = provider.verify(cert_evidence.bidder_id, str(cert_evidence.value))
        verification = verification.model_copy(
            update={
                "evidence_id": cert_evidence.evidence_id,
                "document_id": cert_evidence.document_id,
            }
        )
        register = getattr(provider, "register", None)
        if callable(register):
            register(verification)

        if verification.status is not VerificationStatus.VERIFIED:
            return self._provider_outcome(requirement, verification, cert_evidence)

        evaluation_date = coerce_evaluation_date(params.evaluation_date)
        return self._interpret_verified(
            requirement, verification, cert_evidence, params, evaluation_date
        )

    # -- non-verified provider outcomes -----------------------------------

    def _provider_outcome(
        self,
        requirement: Requirement,
        verification: Verification,
        cert_evidence: Evidence,
    ) -> ComplianceResult:
        status = _PROVIDER_TO_COMPLIANCE[verification.status]
        if verification.status is VerificationStatus.INVALID:
            return self._result(
                requirement, status, "BIS certificate is invalid according to the source.",
                verification, cert_evidence, flags=[_flag("BIS_CERTIFICATE_INVALID")],
            )
        if verification.status is VerificationStatus.NOT_FOUND:
            return self._result(
                requirement, status,
                "BIS certificate number was not found in the source, so it could not be verified.",
                verification, cert_evidence, flags=[_flag("BIS_CERTIFICATE_NOT_FOUND")],
            )
        return self._result(
            requirement, status,
            "BIS verification source is unavailable or errored, so certification could not be confirmed.",
            verification, cert_evidence, flags=[_flag("BIS_VERIFICATION_UNAVAILABLE")],
        )

    # -- verified interpretation -----------------------------------------

    def _interpret_verified(
        self,
        requirement: Requirement,
        verification: Verification,
        cert_evidence: Evidence,
        params: BisParameters,
        evaluation_date: Any,
    ) -> ComplianceResult:
        data = verification.data
        status = data.get("licence_status")

        if status in ("SUSPENDED", "REVOKED"):
            return self._result(
                requirement, ComplianceStatus.FAIL,
                "BIS certificate is suspended or revoked according to the source.",
                verification, cert_evidence,
                flags=[_flag("BIS_CERTIFICATE_SUSPENDED_REVOKED")],
            )

        if params.required_status is not None and str(status).upper() != params.required_status.upper():
            return self._result(
                requirement, ComplianceStatus.FAIL,
                "BIS licence status does not match the required status.",
                verification, cert_evidence, flags=[_flag("BIS_CERTIFICATE_INVALID")],
            )

        if params.required_standard is not None and not self._matches_token(
            data.get("standard"), params.required_standard
        ):
            return self._result(
                requirement, ComplianceStatus.FAIL,
                "BIS certification standard does not match the required standard.",
                verification, cert_evidence, flags=[],
            )

        if params.required_product is not None and not self._product_covered(
            data, params.required_product
        ):
            return self._result(
                requirement, ComplianceStatus.FAIL,
                "BIS certification scope does not cover the required product.",
                verification, cert_evidence, flags=[_flag("BIS_PRODUCT_SCOPE_MISMATCH")],
            )

        if params.required_manufacturer is not None:
            if normalize_identity_name(data.get("manufacturer")) != normalize_identity_name(
                params.required_manufacturer
            ):
                return self._result(
                    requirement, ComplianceStatus.FAIL,
                    "BIS certification manufacturer does not match the required manufacturer.",
                    verification, cert_evidence, flags=[],
                )

        if params.required_facility_location is not None and not self._matches_token(
            data.get("manufacturing_location"), params.required_facility_location
        ):
            return self._result(
                requirement, ComplianceStatus.FAIL,
                "BIS-certified facility location does not match the required location.",
                verification, cert_evidence,
                flags=[_flag("BIS_FACILITY_LOCATION_INELIGIBLE")],
            )

        validity = self._check_validity(data, evaluation_date)
        if validity == "MALFORMED":
            return self._result(
                requirement, ComplianceStatus.UNVERIFIABLE,
                "BIS certificate validity dates are malformed, so current validity could not be determined.",
                verification, cert_evidence, flags=[],
            )
        if validity == "FUTURE":
            return self._result(
                requirement, ComplianceStatus.FAIL,
                "BIS certificate is not yet valid on the evaluation date.",
                verification, cert_evidence, flags=[_flag("BIS_CERTIFICATE_INVALID")],
            )
        if validity == "EXPIRED":
            return self._result(
                requirement, ComplianceStatus.FAIL,
                "BIS certificate is expired as of the evaluation date.",
                verification, cert_evidence, flags=[_flag("BIS_CERTIFICATE_EXPIRED")],
            )

        return self._result(
            requirement, ComplianceStatus.PASS,
            "BIS certificate was verified and meets the configured requirements.",
            verification, cert_evidence, flags=[],
        )

    @staticmethod
    def _check_validity(data: dict[str, Any], evaluation_date: Any) -> str | None:
        """Return FUTURE / EXPIRED / MALFORMED / None (valid or unassessed)."""
        valid_from_raw = data.get("valid_from")
        valid_until_raw = data.get("valid_until")
        if valid_from_raw is None and valid_until_raw is None:
            return None
        if evaluation_date is None:
            return None
        valid_from = parse_date_value(valid_from_raw)
        valid_until = parse_date_value(valid_until_raw)
        if (valid_from_raw is not None and valid_from is None) or (
            valid_until_raw is not None and valid_until is None
        ):
            return "MALFORMED"
        if valid_from is not None and evaluation_date < valid_from:
            return "FUTURE"
        if valid_until is not None and evaluation_date > valid_until:
            return "EXPIRED"
        return None

    @staticmethod
    def _product_covered(data: dict[str, Any], required_product: str) -> bool:
        required = required_product.casefold()
        blobs: list[str] = []
        if data.get("product_description"):
            blobs.append(str(data["product_description"]))
        scope = data.get("scope_of_certification")
        if isinstance(scope, list):
            blobs.extend(str(s) for s in scope)
        elif scope:
            blobs.append(str(scope))
        return any(required in b.casefold() for b in blobs)

    @staticmethod
    def _matches_token(provided: Any, required: str) -> bool:
        if provided is None:
            return False
        return required.casefold() in str(provided).casefold()

    # -- builders / helpers ----------------------------------------------

    def _result(
        self,
        requirement: Requirement,
        status: ComplianceStatus,
        reason: str,
        verification: Verification,
        cert_evidence: Evidence,
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
            evidence_refs=[cert_evidence.evidence_id],
            verification_refs=[verification.verification_id],
            flags=flags,
            rule_id=requirement.rule_id,
        )

    def _missing(
        self, requirement: Requirement, *, evidence_refs: list[str]
    ) -> ComplianceResult:
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=ComplianceStatus.MISSING,
            reason="BIS certificate evidence is missing, so certification cannot be evaluated.",
            expected=requirement.expected,
            actual=None,
            evidence_refs=evidence_refs,
            verification_refs=[],
            flags=[_flag("REQUIRED_FIELD_MISSING")],
            rule_id=requirement.rule_id,
        )

    def _not_applicable(self, requirement: Requirement) -> ComplianceResult:
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=ComplianceStatus.NOT_APPLICABLE,
            reason="BIS certification is not required for this tender.",
            expected=requirement.expected,
            actual=None,
            evidence_refs=[],
            verification_refs=[],
            flags=[],
            rule_id=requirement.rule_id,
        )


__all__ = ["BisCertificationRule", "BisParameters"]