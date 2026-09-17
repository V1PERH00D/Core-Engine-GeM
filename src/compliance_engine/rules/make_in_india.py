"""Make-in-India / local content rule (``MAKE_IN_INDIA_001``).

Provider-free evidence rule. The engine has no authoritative local-content
portal contract, so the rule deterministically evaluates submitted evidence
against explicitly configured tender parameters. The threshold always comes
from the tender — there is no universal local-content percentage.

Operator comparison reuses the existing
:func:`~compliance_engine.financial.thresholds.evaluate_threshold` and
:class:`~compliance_engine.financial.models.ComparisonOperator` semantics
(``>=``, ``>``, ``=``, ``<=``, ``<``). Missing evidence yields a controlled
MISSING / NOT_CHECKED; contradictory evidence yields a canonical
inconsistency flag; an insufficient calculation yields UNVERIFIABLE.

Indian origin is never inferred merely from an Indian company name/address.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from compliance_engine.flags import get_flag_definition
from compliance_engine.models import (
    ComplianceResult,
    ComplianceStatus,
    Evidence,
    Requirement,
)
from compliance_engine.financial.thresholds import evaluate_threshold
from compliance_engine.rules.base import Rule


class MakeInIndiaParameters(BaseModel):
    """Typed, explicit Make-in-India/local-content parameters (``extra="forbid"``)."""

    model_config = ConfigDict(extra="forbid")

    minimum_local_content_percentage: float | None = None
    local_content_operator: str = ">="
    required_country_of_origin: str | None = None
    required_manufacturing_location: str | None = None
    required_certificate: str | None = None
    evaluation_date: str | None = None


def _flag(flag_id: str) -> str:
    return get_flag_definition(flag_id).flag_id


_MII_DOC_TYPES = {"MAKE_IN_INDIA", "LOCAL_CONTENT", "MAKE_IN_INDIA_LOCAL_CONTENT"}


def _find(evidence: list[Evidence], field_name: str) -> list[Evidence]:
    return [
        item
        for item in evidence
        if item.document_type.upper() in _MII_DOC_TYPES
        and item.field_name == field_name
    ]


def _coerce_percentage(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


class MakeInIndiaRule(Rule):
    """Evaluate Make-in-India / local-content evidence against tender parameters."""

    rule_id = "MAKE_IN_INDIA_001"
    name = "Make in India / local content"
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
            raise ValueError("requirement is required for MakeInIndiaRule.evaluate")

        params = MakeInIndiaParameters(**(requirement.parameters or {}))
        pct_evidence = _find(evidence, "local_content_percentage")
        evidence_refs = list(
            dict.fromkeys(
                item.evidence_id
                for item in evidence
                if item.document_type.upper() in _MII_DOC_TYPES
            )
        )

        if not pct_evidence:
            return self._missing(requirement, params, evidence_refs)

        values = [_coerce_percentage(e.value) for e in pct_evidence]
        if any(v is None for v in values):
            return self._unverifiable(
                requirement,
                "Local content percentage is malformed, so it cannot be evaluated.",
                evidence_refs,
                flags=[],
            )

        distinct = {round(v, 12) for v in values}
        if len(distinct) > 1:
            return self._unverifiable(
                requirement,
                "Conflicting local content percentages were submitted.",
                evidence_refs,
                flags=[_flag("LOCAL_CONTENT_CLAIM_INCONSISTENT")],
            )

        declared = values[0]

        if params.required_certificate is not None:
            cert = _find(evidence, params.required_certificate)
            if not cert or all(c.value is None for c in cert):
                return self._missing(requirement, params, evidence_refs, certificate=True)

        if params.required_country_of_origin is not None:
            origin = _find(evidence, "country_of_origin")
            if not self._country_matches(origin, params.required_country_of_origin):
                return self._result(
                    requirement, ComplianceStatus.FAIL,
                    "The country of origin does not match the required origin.",
                    evidence_refs, flags=[_flag("SOURCING_LOCATION_MISMATCH")],
                )

        if params.required_manufacturing_location is not None:
            loc = _find(evidence, "manufacturing_location")
            if not self._token_in(loc, params.required_manufacturing_location):
                return self._result(
                    requirement, ComplianceStatus.FAIL,
                    "The manufacturing location does not match the required location.",
                    evidence_refs, flags=[_flag("MANUFACTURING_LOCATION_INELIGIBLE")],
                )

        if params.minimum_local_content_percentage is None:
            return self._result(
                requirement, ComplianceStatus.NOT_CHECKED,
                "No local-content threshold was configured, so the requirement was not checked.",
                evidence_refs, flags=[],
            )

        passed = evaluate_threshold(
            declared,
            params.local_content_operator,
            params.minimum_local_content_percentage,
        )
        if passed is None:
            return self._unverifiable(
                requirement,
                "The local-content operator is unsupported/ambiguous, so the requirement could not be evaluated.",
                evidence_refs,
                flags=[],
            )
        if passed:
            return self._result(
                requirement, ComplianceStatus.PASS,
                "The declared local content meets the configured requirement.",
                evidence_refs, flags=[],
            )
        return self._result(
            requirement, ComplianceStatus.FAIL,
            "The declared local content is below the configured requirement.",
            evidence_refs, flags=[_flag("LOCAL_CONTENT_BELOW_THRESHOLD")],
        )

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _country_matches(origin_evidence: list[Evidence], required: str) -> bool:
        if not origin_evidence:
            return False
        required = required.casefold()
        for item in origin_evidence:
            if item.value is not None and required in str(item.value).casefold():
                return True
        return False

    @staticmethod
    def _token_in(items: list[Evidence], required: str) -> bool:
        if not items:
            return False
        required = required.casefold()
        for item in items:
            if item.value is not None and required in str(item.value).casefold():
                return True
        return False

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

    def _unverifiable(
        self,
        requirement: Requirement,
        reason: str,
        evidence_refs: list[str],
        *,
        flags: list[str],
    ) -> ComplianceResult:
        return self._result(
            requirement, ComplianceStatus.UNVERIFIABLE, reason, evidence_refs, flags=flags
        )

    def _missing(
        self,
        requirement: Requirement,
        params: MakeInIndiaParameters,
        evidence_refs: list[str],
        *,
        certificate: bool = False,
    ) -> ComplianceResult:
        reason = (
            "The required local-content certification is missing."
            if certificate
            else "Local content percentage evidence is missing, so the requirement could not be evaluated."
        )
        return self._result(
            requirement,
            ComplianceStatus.MISSING,
            reason,
            evidence_refs,
            flags=[_flag("LOCAL_CONTENT_EVIDENCE_MISSING")],
        )


__all__ = ["MakeInIndiaParameters", "MakeInIndiaRule"]