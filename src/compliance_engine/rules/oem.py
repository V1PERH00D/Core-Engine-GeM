"""OEM / manufacturer authorization rule (``OEM_AUTHORIZATION_001``).

OEM authorization is evaluated as a provider-free evidence rule: the engine
has no authoritative OEM portal contract, so the rule deterministically checks
the submitted authorization evidence against explicitly configured tender
requirements. Name matching reuses the existing identity normalizer; a name
similarity does not, by itself, establish legal authorization.

Only explicitly configured requirements are checked. Validity is computed
against an explicit ``evaluation_date`` (never the machine clock).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from compliance_engine.anomalies.identity import normalize_identity_name
from compliance_engine.flags import get_flag_definition
from compliance_engine.models import (
    ComplianceResult,
    ComplianceStatus,
    Evidence,
    Requirement,
)
from compliance_engine.rules._date_helpers import coerce_evaluation_date, parse_date_value
from compliance_engine.rules.base import Rule


class OemParameters(BaseModel):
    """Typed, explicit OEM authorization parameters (``extra="forbid"``)."""

    model_config = ConfigDict(extra="forbid")

    require_authorization: bool | None = None
    required_oem: str | None = None
    required_bidder: str | None = None
    required_authorization_type: str | None = None
    required_product: str | None = None
    required_territory: str | None = None
    evaluation_date: str | None = None


def _flag(flag_id: str) -> str:
    return get_flag_definition(flag_id).flag_id


_OEM_DOC_TYPES = {"OEM", "OEM_AUTHORIZATION", "OEM_AUTHORIZATION_DOCUMENT"}


def _find(evidence: list[Evidence], field_name: str) -> Evidence | None:
    for item in evidence:
        if item.document_type.upper() in _OEM_DOC_TYPES and item.field_name == field_name:
            return item
    return None


def _value(evidence: list[Evidence], field_name: str) -> Any:
    item = _find(evidence, field_name)
    return item.value if item is not None else None


class OemAuthorizationRule(Rule):
    """Evaluate OEM authorization against configured requirements."""

    rule_id = "OEM_AUTHORIZATION_001"
    name = "OEM authorization"
    required_providers = ()

    def evaluate(
        self,
        evidence: list[Evidence],
        provider: Any = None,
        requirement: Requirement | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ComplianceResult:
        if requirement is None:
            raise ValueError("requirement is required for OemAuthorizationRule.evaluate")

        params = OemParameters(**(requirement.parameters or {}))
        if params.require_authorization is False:
            return self._not_applicable(requirement)

        oem_name_evidence = _find(evidence, "oem_name")
        if oem_name_evidence is None or oem_name_evidence.value is None:
            return self._missing(requirement)

        evidence_refs = list(
            dict.fromkeys(
                item.evidence_id
                for item in evidence
                if item.document_type.upper() in _OEM_DOC_TYPES
            )
        )

        if params.required_bidder is not None:
            authorized_bidder = _value(evidence, "authorized_bidder")
            if authorized_bidder is None or normalize_identity_name(
                authorized_bidder
            ) != normalize_identity_name(params.required_bidder):
                return self._result(
                    requirement, ComplianceStatus.FAIL,
                    "The authorization does not name the required bidder.",
                    evidence_refs, flags=[_flag("OEM_NAME_MISMATCH")],
                )

        if params.required_oem is not None:
            if normalize_identity_name(oem_name_evidence.value) != normalize_identity_name(
                params.required_oem
            ):
                return self._result(
                    requirement, ComplianceStatus.FAIL,
                    "The OEM name does not match the required manufacturer.",
                    evidence_refs, flags=[_flag("OEM_NAME_MISMATCH")],
                )

        if params.required_authorization_type is not None and not self._token_match(
            _value(evidence, "authorization_type"), params.required_authorization_type
        ):
            return self._result(
                requirement, ComplianceStatus.FAIL,
                "The authorization type does not match the required type.",
                evidence_refs, flags=[_flag("AUTHORIZATION_TYPE_MISMATCH")],
            )

        if params.required_product is not None and not self._product_covered(
            _value(evidence, "authorized_product_range"), params.required_product
        ):
            return self._result(
                requirement, ComplianceStatus.FAIL,
                "The authorized product range does not cover the required product.",
                evidence_refs, flags=[_flag("AUTHORIZED_PRODUCT_RANGE_INSUFFICIENT")],
            )

        if params.required_territory is not None and not self._token_match(
            _value(evidence, "authorization_territory"), params.required_territory
        ):
            return self._result(
                requirement, ComplianceStatus.FAIL,
                "The authorization territory does not cover the required territory.",
                evidence_refs, flags=[_flag("AUTHORIZATION_TERRITORY_MISMATCH")],
            )

        validity = self._check_validity(evidence, params.evaluation_date)
        if validity == "MALFORMED":
            return self._result(
                requirement, ComplianceStatus.UNVERIFIABLE,
                "The authorization validity dates are malformed, so current validity could not be determined.",
                evidence_refs, flags=[],
            )
        if validity == "FUTURE":
            return self._result(
                requirement, ComplianceStatus.FAIL,
                "The authorization is not yet valid on the evaluation date.",
                evidence_refs, flags=[_flag("OEM_AUTHORIZATION_INVALID")],
            )
        if validity == "EXPIRED":
            return self._result(
                requirement, ComplianceStatus.FAIL,
                "The authorization is expired as of the evaluation date.",
                evidence_refs, flags=[_flag("OEM_AUTHORIZATION_EXPIRED")],
            )

        return self._result(
            requirement, ComplianceStatus.PASS,
            "The OEM authorization meets the configured requirements.",
            evidence_refs, flags=[],
        )

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _check_validity(evidence: list[Evidence], evaluation_date: str | None) -> str | None:
        valid_from_raw = _value(evidence, "valid_from")
        valid_until_raw = _value(evidence, "valid_until")
        if valid_from_raw is None and valid_until_raw is None:
            return None
        evaluation = coerce_evaluation_date(evaluation_date)
        if evaluation is None:
            return None
        valid_from = parse_date_value(valid_from_raw)
        valid_until = parse_date_value(valid_until_raw)
        if (valid_from_raw is not None and valid_from is None) or (
            valid_until_raw is not None and valid_until is None
        ):
            return "MALFORMED"
        if valid_from is not None and evaluation < valid_from:
            return "FUTURE"
        if valid_until is not None and evaluation > valid_until:
            return "EXPIRED"
        return None

    @staticmethod
    def _token_match(provided: Any, required: str) -> bool:
        if provided is None:
            return False
        return required.casefold() in str(provided).casefold()

    @staticmethod
    def _product_covered(provided: Any, required_product: str) -> bool:
        if provided is None:
            return False
        required = required_product.casefold()
        if isinstance(provided, list):
            return any(required in str(p).casefold() for p in provided)
        return required in str(provided).casefold()

    def _result(
        self,
        requirement: Requirement,
        status: ComplianceStatus,
        reason: str,
        evidence_refs: list[str],
        *,
        flags: list[str],
    ) -> ComplianceResult:
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=status,
            reason=reason,
            expected=requirement.expected,
            actual=None,
            evidence_refs=evidence_refs,
            verification_refs=[],
            flags=flags,
            rule_id=requirement.rule_id,
        )

    def _missing(self, requirement: Requirement) -> ComplianceResult:
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=ComplianceStatus.MISSING,
            reason="OEM authorization evidence is missing, so authorization cannot be evaluated.",
            expected=requirement.expected,
            actual=None,
            evidence_refs=[],
            verification_refs=[],
            flags=[_flag("OEM_AUTHORIZATION_NOT_PROVIDED")],
            rule_id=requirement.rule_id,
        )

    def _not_applicable(self, requirement: Requirement) -> ComplianceResult:
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=ComplianceStatus.NOT_APPLICABLE,
            reason="OEM authorization is not required for this tender.",
            expected=requirement.expected,
            actual=None,
            evidence_refs=[],
            verification_refs=[],
            flags=[],
            rule_id=requirement.rule_id,
        )


__all__ = ["OemAuthorizationRule", "OemParameters"]