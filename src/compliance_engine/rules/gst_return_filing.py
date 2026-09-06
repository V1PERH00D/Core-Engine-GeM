"""GST return-filing validity rule.

This rule evaluates whether the GST return(s) for a given
GSTIN, financial year, and return type were filed. The
domain :class:`VerificationStatus` is consumed from the
``Verification`` produced by the GSTN return-filing
provider; the business outcome (``"FILED"`` vs
``"NOT_FILED"``) is read from the normalized data
(:attr:`Verification.data`).

The rule explicitly distinguishes:

* return successfully filed  -> PASS
* return not filed          -> FAIL
* provider unavailable/error -> UNVERIFIABLE

The rule does not call the network directly and does not invoke
any AI / detection logic. It is a pure mapping from
:class:`Verification` to :class:`ComplianceResult`, mediated by
the rule layer's own evidence-linkage enrichment.
"""

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
from compliance_engine.verification import VerificationProvider

#: The :class:`VerificationStatus` that the GSTN return-filing
#: parser emits on a successful 2xx response with a usable
#: payload. Whether the return was actually filed is determined
#: by reading the normalized ``data["filing_status"]``; the
#: transport-level :class:`VerificationStatus` is the same for
#: both filed and not-filed outcomes.
_VERIFIED_OK = VerificationStatus.VERIFIED

#: Mapping from :class:`VerificationStatus` to the
#: :class:`ComplianceStatus` the rule emits. The mapping is
#: deliberately independent of the business filing outcome; the
#: business outcome is read from the normalized ``data``.
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
        "The GST return was verified as filed by the authoritative source."
    ),
    ComplianceStatus.FAIL: (
        "The GST return was verified as NOT filed by the authoritative "
        "source."
    ),
    VerificationStatus.NOT_FOUND: (
        "The GSTIN was not found in the authoritative source, so the "
        "return-filing status could not be verified."
    ),
    VerificationStatus.INVALID: (
        "The GSTIN is invalid according to the authoritative source, so "
        "the return-filing status could not be verified."
    ),
    VerificationStatus.UNAVAILABLE: (
        "The GST return-filing source is unavailable, so the return "
        "status could not be verified."
    ),
    VerificationStatus.ERROR: (
        "The GST return-filing source returned an error, so the return "
        "status could not be verified."
    ),
}

#: Business outcome strings carried on the normalized
#: ``Verification.data["filing_status"]``.
_FILING_STATUS_FILED = "FILED"
_FILING_STATUS_NOT_FILED = "NOT_FILED"


class GSTReturnFilingRule(Rule):
    """Evaluate whether a GST return was filed for the given
    financial year and return type.

    The rule reads the following evidence fields, when present:

    * ``document_type == "GST"`` and ``field_name == "gstin"``:
      the GSTIN being verified.
    * ``document_type == "GST"`` and ``field_name ==
      "financial_year"`` (optional): the financial year the
      tender cares about. Defaults to the requirement's
      ``parameters`` value when not present in evidence.
    * ``document_type == "GST"`` and ``field_name ==
      "return_type"`` (optional): the return form the tender
      cares about. Defaults to the requirement's ``parameters``
      value when not present in evidence.

    The rule never invents a financial year or return type on
    its own. When neither the evidence nor the requirement
    supplies the filter, the rule falls back to the source's
    full filing table.
    """

    rule_id = "GST_RETURN_FILING_001"
    name = "GST return-filing validity"
    required_providers = (Capability.GST_RETURN_FILING,)

    def evaluate(
        self,
        evidence: list[Evidence],
        provider: VerificationProvider | None = None,
        requirement: Requirement | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ComplianceResult:
        """Return a compliance result for the GST return-filing
        status."""

        if provider is None:
            raise ValueError(
                "provider is required for GSTReturnFilingRule.evaluate"
            )
        if requirement is None:
            raise ValueError(
                "requirement is required for GSTReturnFilingRule.evaluate"
            )

        gstin_evidence = next(
            (
                item
                for item in evidence
                if item.document_type == "GST" and item.field_name == "gstin"
            ),
            None,
        )
        if gstin_evidence is None:
            return self._missing(
                requirement,
                reason=(
                    "GSTIN evidence is missing, so GST return-filing "
                    "status cannot be evaluated."
                ),
                evidence_refs=[],
            )
        if gstin_evidence.value is None:
            return self._missing(
                requirement,
                reason=(
                    "GSTIN evidence is present but the extracted value is "
                    "null, so GST return-filing status cannot be evaluated."
                ),
                evidence_refs=[gstin_evidence.evidence_id],
            )

        financial_year = self._filter_value(
            evidence, requirement, "financial_year"
        )
        return_type = self._filter_value(
            evidence, requirement, "return_type"
        )

        verification = provider.verify(
            gstin_evidence.bidder_id,
            str(gstin_evidence.value),
            financial_year=financial_year,
            return_type=return_type,
        )
        # Enrichment: link the verification back to the originating
        # evidence / document so the audit trail in
        # ``EngineResult.verification_records`` and any downstream AI
        # Verification consumers can correlate the verification with
        # the originating evidence without re-deriving it.
        verification = verification.model_copy(
            update={
                "evidence_id": gstin_evidence.evidence_id,
                "document_id": gstin_evidence.document_id,
            }
        )
        register = getattr(provider, "register", None)
        if callable(register):
            register(verification)

        status = self._derive_compliance_status(verification)
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=status,
            reason=self._reason(verification, status),
            expected=requirement.expected,
            actual=self._actual(verification),
            evidence_refs=[gstin_evidence.evidence_id],
            verification_refs=[verification.verification_id],
            flags=self._flags(verification, status),
            rule_id=requirement.rule_id,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_value(
        evidence: list[Evidence],
        requirement: Requirement,
        field_name: str,
    ) -> str:
        """Return the filter value (financial year / return type).

        Precedence:

        1. An evidence field whose ``document_type == "GST"`` and
           ``field_name == field_name`` (case-sensitive).
        2. The requirement's ``parameters`` mapping.
        3. ``None``, so the provider falls back to the
           ``ALL`` sentinel and the source returns the whole
           table.
        """

        for item in evidence:
            if (
                item.document_type == "GST"
                and item.field_name == field_name
                and item.value is not None
            ):
                return str(item.value)
        params = requirement.parameters or {}
        if field_name in params and params[field_name] is not None:
            return str(params[field_name])
        return "ALL"

    @staticmethod
    def _derive_compliance_status(verification: Verification) -> ComplianceStatus:
        # Provider failure modes (UNAVAILABLE / ERROR / NOT_FOUND /
        # INVALID) are mapped first; the rule never turns a
        # provider failure into PASS or FAIL.
        if verification.status is not _VERIFIED_OK:
            return _PROVIDER_TO_COMPLIANCE[verification.status]

        # The provider reported a usable payload. The business
        # outcome is read from the normalized ``data``.
        filing_status = (verification.data or {}).get("filing_status")
        if filing_status == _FILING_STATUS_FILED:
            return ComplianceStatus.PASS
        if filing_status == _FILING_STATUS_NOT_FILED:
            return ComplianceStatus.FAIL
        # The provider said VERIFIED but the payload did not
        # carry a recognizable business outcome. Treat as
        # UNVERIFIABLE so the engine does not silently PASS.
        return ComplianceStatus.UNVERIFIABLE

    @staticmethod
    def _reason(verification: Verification, status: ComplianceStatus) -> str:
        if status is ComplianceStatus.PASS:
            return _REASONS[ComplianceStatus.PASS]
        if status is ComplianceStatus.FAIL:
            return _REASONS[ComplianceStatus.FAIL]
        return _REASONS[verification.status]

    @staticmethod
    def _actual(verification: Verification) -> dict[str, Any]:
        return {
            "status": verification.status,
            "data": verification.data,
        }

    @staticmethod
    def _flags(verification: Verification, status: ComplianceStatus) -> list[str]:
        if status is ComplianceStatus.FAIL:
            return [get_flag_definition("GST_RETURN_COMPLIANCE_ISSUE").flag_id]
        if status is ComplianceStatus.UNVERIFIABLE:
            if verification.status is VerificationStatus.UNAVAILABLE:
                return [get_flag_definition("GST_VERIFICATION_UNAVAILABLE").flag_id]
            # Missing return record at the source -> treat as evidence
            # missing from the perspective of the audit trail.
            return [get_flag_definition("GST_RETURN_EVIDENCE_MISSING").flag_id]
        return []

    @staticmethod
    def _missing(
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
            flags=[],
            rule_id=requirement.rule_id,
        )


__all__ = ["GSTReturnFilingRule"]
