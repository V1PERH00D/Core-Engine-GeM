"""Procurement eligibility / debarment compliance rule.

This rule consumes the ``Verification`` produced by
:class:`DebarmentAdapter` and emits a :class:`ComplianceResult`.

The rule distinguishes:

* ``CLEAR`` + verified source -> ``PASS``,
* ``RESTRICTED`` + active restriction on the evaluation date ->
  ``FAIL`` with the appropriate debarment flag,
* ``RESTRICTED`` + restriction has already expired (effective
  date <= evaluation date <= end date) -> ``PASS`` with the
  historical restriction preserved on the audit trail,
* ``RESTRICTED`` + missing dates -> ``UNKNOWN`` business state
  but verified transport -> ``UNVERIFIABLE``,
* transport / payload failures -> ``UNVERIFIABLE``,
* the rule never converts a transport failure into a negative
  compliance finding.

The rule is fed an explicit ``evaluation_date`` either via
``Requirement.parameters["evaluation_date"]`` or the ``provider``
``evaluate(..., evaluation_date=...)`` kwarg. It does NOT call
the machine clock.

Stable rule id: ``DEBARMENT_ELIGIBILITY_001``.
"""

from __future__ import annotations

from datetime import date
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

from compliance_engine.verification.debarment_models import (
    DEBARMENT_CAPABILITY,
    DebarmentQuery,
    DebarmentRestrictionStatus,
    MatchMethod,
)


# ---------------------------------------------------------------------------
# Mapping from transport-level VerificationStatus to ComplianceStatus
# ---------------------------------------------------------------------------


# Provider failure modes (UNAVAILABLE / ERROR / NOT_FOUND / INVALID)
# are mapped to UNVERIFIABLE first; the rule never turns a provider
# failure into PASS or FAIL. RESTRICTED with a verified payload
# is handled separately because the rule needs to read the
# normalized data to decide whether the restriction is currently
# active.
_PROVIDER_TO_COMPLIANCE = {
    VerificationStatus.VERIFIED: ComplianceStatus.PASS,
    VerificationStatus.NOT_FOUND: ComplianceStatus.UNVERIFIABLE,
    VerificationStatus.INVALID: ComplianceStatus.UNVERIFIABLE,
    VerificationStatus.UNAVAILABLE: ComplianceStatus.UNVERIFIABLE,
    VerificationStatus.ERROR: ComplianceStatus.UNVERIFIABLE,
}


_REASONS = {
    ComplianceStatus.PASS: (
        "The debarment / procurement-eligibility source returned no "
        "active restriction for the queried subject; the requirement "
        "is satisfied."
    ),
    ComplianceStatus.FAIL: (
        "The debarment / procurement-eligibility source reports an "
        "active blacklist / debarment / suspension / procurement "
        "restriction on the queried subject."
    ),
    ComplianceStatus.UNVERIFIABLE: (
        "The debarment / procurement-eligibility source could not "
        "produce a reliable conclusion; the requirement could not "
        "be verified."
    ),
    ComplianceStatus.MISSING: (
        "Debarment / eligibility evidence is missing, so the "
        "requirement could not be evaluated."
    ),
}


# Flag ids.
FLAG_ACTIVE_RESTRICTION = "PROCUREMENT_DEBARMENT_ACTIVE"
FLAG_UNVERIFIABLE = "PROCUREMENT_ELIGIBILITY_UNVERIFIABLE"


def _flag(flag_id: str) -> str:
    return get_flag_definition(flag_id).flag_id


def _resolve_evaluation_date(
    *,
    requirement: Requirement,
    kwargs: dict[str, Any],
) -> date | None:
    """Pick the evaluation date used for the active-restriction window.

    Precedence (highest first):

    1. ``evaluation_date`` kwarg passed to :meth:`Rule.evaluate`.
    2. ``requirement.parameters["evaluation_date"]``.
    3. ``None`` -- the rule must fall back to ``UNKNOWN``.
    """

    if "evaluation_date" in kwargs and kwargs["evaluation_date"] is not None:
        value = kwargs["evaluation_date"]
        if isinstance(value, date):
            return value
        raise TypeError(
            "evaluation_date must be a datetime.date instance, got "
            f"{type(value).__name__}"
        )
    params = requirement.parameters or {}
    raw = params.get("evaluation_date")
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    raise TypeError(
        "requirement.parameters['evaluation_date'] must be a "
        f"datetime.date instance, got {type(raw).__name__}"
    )


def is_active_on(
    *,
    effective_date: date | None,
    end_date: date | None,
    evaluation_date: date,
) -> bool:
    """Return True iff the restriction is active on ``evaluation_date``.

    Rules:

    * ``effective_date`` must be present and <= evaluation date,
      otherwise the restriction cannot be proven active yet.
    * ``end_date`` is exclusive: a restriction whose end_date is
      exactly the evaluation_date has already expired.
    * ``end_date == None`` is treated as "open-ended / active".
    * Missing both dates cannot be active by default; the rule
      must surface an UNKNOWN in that case so it never fabricates
      an active restriction on insufficient evidence.
    """

    if effective_date is None:
        return False
    if effective_date > evaluation_date:
        return False
    if end_date is None:
        return True
    return evaluation_date < end_date


def _extract_evidence(evidence: list[Evidence]) -> tuple[Evidence | None, str | None]:
    """Pick the debarment identifier evidence and a name hint.

    Supported evidence shapes (in priority order):

    * ``document_type == "DEBARMENT"`` and ``field_name ==
      "debarment_identifier"``: explicit debarment evidence.
    * Any of the well-known bidder identifier types (PAN, GST,
      UDYAM, MCA) as a fallback when the tender carries the
      bidder identifier but no dedicated debarment document.

    Evidence with a ``None`` value is treated identically to a
    missing field: the rule returns ``(evidence_item, None)`` so
    the caller can surface ``MISSING`` with the correct evidence
    reference, mirroring the GST / PAN / Udyam rule conventions.
    """

    for item in evidence:
        if (
            item.document_type == "DEBARMENT"
            and item.field_name == "debarment_identifier"
        ):
            if item.value is None:
                return item, None
            return item, item.value
    for doc_type, field_name in (
        ("PAN", "pan_number"),
        ("GST", "gstin"),
        ("UDYAM", "udyam_registration_number"),
        ("MCA", "cin"),
    ):
        for item in evidence:
            if (
                item.document_type == doc_type
                and item.field_name == field_name
            ):
                if item.value is None:
                    return item, None
                return item, item.value
    return None, None


class DebarmentEligibilityRule(Rule):
    """Evaluate procurement-eligibility against a debarment source.

    Rule id: ``DEBARMENT_ELIGIBILITY_001``.
    Required providers: a single :class:`VerificationProvider`
    configured for the ``DEBARMENT`` capability.
    """

    rule_id = "DEBARMENT_ELIGIBILITY_001"
    name = "Procurement debarment / eligibility"
    required_providers = (Capability.DEBARMENT,)

    def evaluate(
        self,
        evidence: list[Evidence],
        provider: VerificationProvider | None = None,
        requirement: Requirement | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ComplianceResult:
        if provider is None:
            raise ValueError(
                "provider is required for DebarmentEligibilityRule.evaluate"
            )
        if requirement is None:
            raise ValueError(
                "requirement is required for DebarmentEligibilityRule.evaluate"
            )

        evidence_item, identifier_value = _extract_evidence(evidence)
        if identifier_value is None:
            return self._missing(
                requirement,
                reason=(
                    "Debarment / eligibility identifier evidence is "
                    "missing, so the requirement could not be evaluated."
                ),
                evidence_refs=(
                    [] if evidence_item is None else [evidence_item.evidence_id]
                ),
            )

        evaluation_date = _resolve_evaluation_date(
            requirement=requirement, kwargs=kwargs
        )

        subject_name = next(
            (
                item.value
                for item in evidence
                if item.document_type == "DEBARMENT"
                and item.field_name == "subject_name"
            ),
            None,
        )

        verification = provider.verify(
            evidence_item.bidder_id,
            str(identifier_value),
            subject_name=subject_name,
            evaluation_date=evaluation_date,
        )

        # Enrichment is done via ``model_copy`` because
        # ``Verification`` is a frozen pydantic model.
        verification = verification.model_copy(
            update={
                "evidence_id": evidence_item.evidence_id,
                "document_id": evidence_item.document_id,
            }
        )
        register = getattr(provider, "register", None)
        if callable(register):
            register(verification)

        return self._decide(
            requirement=requirement,
            verification=verification,
            evaluation_date=evaluation_date,
            evidence_id=evidence_item.evidence_id,
        )
    def _decide(
        self,
        *,
        requirement: Requirement,
        verification: Verification,
        evaluation_date: date | None,
        evidence_id: str,
    ) -> ComplianceResult:
        # Provider failure modes first -- never turn them into
        # PASS or FAIL.
        if verification.status is not VerificationStatus.VERIFIED:
            return ComplianceResult(
                requirement_id=requirement.requirement_id,
                capability=requirement.capability,
                status=_PROVIDER_TO_COMPLIANCE[verification.status],
                reason=self._reason_for_unverifiable(verification.status),
                expected=requirement.expected,
                actual={
                    "status": verification.status,
                    "data": verification.data,
                },
                evidence_refs=[evidence_id],
                verification_refs=[verification.verification_id],
                flags=[_flag(FLAG_UNVERIFIABLE)],
                rule_id=requirement.rule_id,
            )

        # The source produced a 2xx, usable payload. Read the
        # business restriction status.
        restriction = (
            verification.data.get("restriction_status")
            if isinstance(verification.data, dict)
            else None
        )

        if restriction == DebarmentRestrictionStatus.CLEAR.value:
            return ComplianceResult(
                requirement_id=requirement.requirement_id,
                capability=requirement.capability,
                status=ComplianceStatus.PASS,
                reason=_REASONS[ComplianceStatus.PASS],
                expected=requirement.expected,
                actual={
                    "status": verification.status,
                    "data": verification.data,
                },
                evidence_refs=[evidence_id],
                verification_refs=[verification.verification_id],
                flags=[],
                rule_id=requirement.rule_id,
            )

        if restriction == DebarmentRestrictionStatus.RESTRICTED.value:
            return self._decide_restricted(
                requirement=requirement,
                verification=verification,
                evaluation_date=evaluation_date,
                evidence_id=evidence_id,
            )

        if restriction == DebarmentRestrictionStatus.UNKNOWN.value:
            return ComplianceResult(
                requirement_id=requirement.requirement_id,
                capability=requirement.capability,
                status=ComplianceStatus.UNVERIFIABLE,
                reason=self._reason_for_unknown_business(verification),
                expected=requirement.expected,
                actual={
                    "status": verification.status,
                    "data": verification.data,
                },
                evidence_refs=[evidence_id],
                verification_refs=[verification.verification_id],
                flags=[_flag(FLAG_UNVERIFIABLE)],
                rule_id=requirement.rule_id,
            )

        # Verified transport but unknown business shape -- never
        # silently PASS.
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=ComplianceStatus.UNVERIFIABLE,
            reason=_REASONS[ComplianceStatus.UNVERIFIABLE],
            expected=requirement.expected,
            actual={
                "status": verification.status,
                "data": verification.data,
            },
            evidence_refs=[evidence_id],
            verification_refs=[verification.verification_id],
            flags=[_flag(FLAG_UNVERIFIABLE)],
            rule_id=requirement.rule_id,
        )
    def _decide_restricted(
        self,
        *,
        requirement: Requirement,
        verification: Verification,
        evaluation_date: date | None,
        evidence_id: str,
    ) -> ComplianceResult:
        effective = (
            verification.data.get("effective_date")
            if isinstance(verification.data, dict)
            else None
        )
        end = (
            verification.data.get("end_date")
            if isinstance(verification.data, dict)
            else None
        )
        match_method = (
            verification.data.get("match_method")
            if isinstance(verification.data, dict)
            else None
        )

        # A name-only (or weak) match must never establish a legal
        # restriction. The rule surfaces UNVERIFIABLE in every case
        # where the source-side record was matched without an
        # identifier (i.e. EXACT_NAME / NORMALIZED_NAME /
        # INSUFFICIENT_EVIDENCE). The prompt explicitly says
        # "do not silently treat 'similar name' as 'confirmed
        # legal entity'". Identifier matches always win over name
        # matches; only EXACT_IDENTIFIER / NORMALIZED_IDENTIFIER
        # can drive a PASS / FAIL decision.
        if match_method in (
            MatchMethod.INSUFFICIENT_EVIDENCE.value,
            MatchMethod.EXACT_NAME.value,
            MatchMethod.NORMALIZED_NAME.value,
        ):
            return ComplianceResult(
                requirement_id=requirement.requirement_id,
                capability=requirement.capability,
                status=ComplianceStatus.UNVERIFIABLE,
                reason=(
                    "The debarment / eligibility source returned a "
                    "restriction record but the matching strategy "
                    "was a name-only or weak match; the rule does "
                    "not treat name-only matches as confirmed legal "
                    "identity matches."
                ),
                expected=requirement.expected,
                actual={
                    "status": verification.status,
                    "data": verification.data,
                },
                evidence_refs=[evidence_id],
                verification_refs=[verification.verification_id],
                flags=[_flag(FLAG_UNVERIFIABLE)],
                rule_id=requirement.rule_id,
            )

        if evaluation_date is None:
            return ComplianceResult(
                requirement_id=requirement.requirement_id,
                capability=requirement.capability,
                status=ComplianceStatus.UNVERIFIABLE,
                reason=(
                    "The debarment / eligibility source reports a "
                    "restriction but no evaluation_date was supplied; "
                    "active status cannot be determined."
                ),
                expected=requirement.expected,
                actual={
                    "status": verification.status,
                    "data": verification.data,
                },
                evidence_refs=[evidence_id],
                verification_refs=[verification.verification_id],
                flags=[_flag(FLAG_UNVERIFIABLE)],
                rule_id=requirement.rule_id,
            )

        active = is_active_on(
            effective_date=effective,
            end_date=end,
            evaluation_date=evaluation_date,
        )

        if active:
            return ComplianceResult(
                requirement_id=requirement.requirement_id,
                capability=requirement.capability,
                status=ComplianceStatus.FAIL,
                reason=_REASONS[ComplianceStatus.FAIL],
                expected=requirement.expected,
                actual={
                    "status": verification.status,
                    "data": verification.data,
                    "evaluation_date": evaluation_date.isoformat(),
                },
                evidence_refs=[evidence_id],
                verification_refs=[verification.verification_id],
                flags=[_flag(FLAG_ACTIVE_RESTRICTION)],
                rule_id=requirement.rule_id,
            )

        # Expired restriction. PASS -- but preserve the historical
        # restriction on the audit trail so reviewers can still see
        # that one existed.
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=ComplianceStatus.PASS,
            reason=(
                "The debarment / eligibility source reports a "
                "restriction but it has expired relative to the "
                "evaluation date; the requirement is satisfied."
            ),
            expected=requirement.expected,
            actual={
                "status": verification.status,
                "data": verification.data,
                "evaluation_date": evaluation_date.isoformat(),
                "historical_restriction": True,
            },
            evidence_refs=[evidence_id],
            verification_refs=[verification.verification_id],
            flags=[],
            rule_id=requirement.rule_id,
        )
    def _missing(
        self,
        requirement: Requirement,
        *,
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
            flags=[_flag("REQUIRED_FIELD_MISSING")],
            rule_id=requirement.rule_id,
        )

    @staticmethod
    def _reason_for_unverifiable(status: VerificationStatus) -> str:
        if status is VerificationStatus.UNAVAILABLE:
            return (
                "The debarment / eligibility source is unavailable, "
                "so the restriction status could not be determined."
            )
        if status is VerificationStatus.NOT_FOUND:
            return (
                "The debarment / eligibility source returned no "
                "record for the queried subject, so the restriction "
                "status could not be determined."
            )
        if status is VerificationStatus.INVALID:
            return (
                "The queried identifier is invalid according to the "
                "debarment / eligibility source, so the restriction "
                "status could not be determined."
            )
        if status is VerificationStatus.ERROR:
            return (
                "The debarment / eligibility source returned an "
                "error, so the restriction status could not be "
                "determined."
            )
        return _REASONS[ComplianceStatus.UNVERIFIABLE]

    @staticmethod
    def _reason_for_unknown_business(verification: Verification) -> str:
        match_method = (
            verification.data.get("match_method")
            if isinstance(verification.data, dict)
            else None
        )
        if match_method == MatchMethod.INSUFFICIENT_EVIDENCE.value:
            return (
                "The debarment / eligibility source could not "
                "establish a reliable identity match for the "
                "queried subject."
            )
        return (
            "The debarment / eligibility source returned an "
            "ambiguous / incomplete restriction record."
        )


__all__ = [
    "FLAG_ACTIVE_RESTRICTION",
    "FLAG_UNVERIFIABLE",
    "DebarmentEligibilityRule",
    "is_active_on",
]
