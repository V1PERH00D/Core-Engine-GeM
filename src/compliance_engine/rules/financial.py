"""Financial capacity eligibility rule.

This rule implements the tender-specific checks described in Section 7 of the
capability matrix using the current normalized evidence model. It does not
perform external or government verification; that remains the job of a future
real provider adapter.
"""

from __future__ import annotations

from math import isclose
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
    VerificationStatus.INACTIVE: "FINANCIAL_VERIFICATION_UNAVAILABLE",
    VerificationStatus.INVALID: "FINANCIAL_DATA_INCONSISTENCY",
    VerificationStatus.NOT_FOUND: "FINANCIAL_CAPACITY_MISSING",
    VerificationStatus.UNAVAILABLE: "FINANCIAL_VERIFICATION_UNAVAILABLE",
    VerificationStatus.ERROR: "FINANCIAL_VERIFICATION_UNAVAILABLE",
}

_REASONS = {
    VerificationStatus.VERIFIED: (
        "Financial capacity was verified and meets the required thresholds."
    ),
    VerificationStatus.INACTIVE: (
        "Financial data is stale or outdated according to the verification source."
    ),
    VerificationStatus.INVALID: (
        "Financial data is inconsistent or invalid according to the verification source."
    ),
    VerificationStatus.NOT_FOUND: (
        "Financial data was not found in the authoritative source, so financial capacity could not be verified."
    ),
    VerificationStatus.UNAVAILABLE: (
        "The financial verification source is unavailable, so financial capacity could not be verified."
    ),
    VerificationStatus.ERROR: (
        "The financial verification source returned an error, so financial capacity could not be verified."
    ),
}


class FinancialCapacityRule(Rule):
    """Evaluate whether a bidder meets tender-specific financial-capacity conditions."""

    rule_id = "FINANCIAL_CAPACITY_001"
    name = "Financial capacity eligibility"
    required_providers = (Capability.FINANCIAL,)

    def evaluate(
        self,
        evidence: list[Evidence],
        provider: VerificationProvider | None = None,
        requirement: Requirement | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> ComplianceResult:
        """Return a compliance result for financial capacity eligibility."""

        if provider is None:
            raise ValueError("provider is required for FinancialCapacityRule.evaluate")
        if requirement is None:
            raise ValueError(
                "requirement is required for FinancialCapacityRule.evaluate"
            )

        required_years = self._assessment_years(requirement)
        year_evidence = self._financial_year_entries(evidence)
        annual_records = self._group_by_year(evidence)

        if not year_evidence:
            return self._missing(
                requirement,
                reason="Financial year is missing, so financial capacity cannot be evaluated.",
                evidence_refs=[],
                flags=[get_flag_definition("FINANCIAL_YEAR_MISSING").flag_id],
            )

        if required_years > 1:
            if len(year_evidence) < required_years:
                return self._missing(
                    requirement,
                    reason=(
                        f"Financial evidence for {required_years} assessment years is required; "
                        f"only {len(year_evidence)} year entries were found."
                    ),
                    evidence_refs=[item.evidence_id for item in year_evidence],
                    flags=[get_flag_definition("FINANCIAL_YEAR_MISSING").flag_id],
                )

        turnover_value = self._field_value(evidence, "turnover")
        if turnover_value is None:
            return self._missing(
                requirement,
                reason="Financial evidence is missing the turnover value required to assess capacity.",
                evidence_refs=[item.evidence_id for item in evidence if item.field_name == "turnover"],
                flags=[get_flag_definition("FINANCIAL_CAPACITY_MISSING").flag_id],
            )

        verifier = provider.verify(
            self._bidder_id(evidence),
            str(turnover_value),
            requirement_expected=requirement.expected,
        )
        status = _PROVIDER_TO_COMPLIANCE.get(verifier.status, ComplianceStatus.UNVERIFIABLE)
        flags: list[str] = []

        if verification_flag := _FLAG_BY_STATUS.get(verifier.status):
            flags.append(get_flag_definition(verification_flag).flag_id)

        if verifier.status in (VerificationStatus.NOT_FOUND, VerificationStatus.UNAVAILABLE, VerificationStatus.ERROR):
            return self._result(
                requirement=requirement,
                status=status,
                reason=self._reason(verifier.status),
                evidence_refs=[item.evidence_id for item in evidence if item.field_name == "turnover"],
                verification_refs=[verifier.verification_id],
                flags=flags,
                actual=self._actual(verifier),
            )

        if verifier.status in (VerificationStatus.INVALID, VerificationStatus.INACTIVE):
            return self._result(
                requirement=requirement,
                status=status,
                reason=self._reason(verifier.status),
                evidence_refs=[item.evidence_id for item in evidence if item.field_name == "turnover"],
                verification_refs=[verifier.verification_id],
                flags=flags,
                actual=self._actual(verifier),
            )

        threshold_result = self._threshold_evaluation(
            evidence,
            requirement,
            turnover_value,
            annual_records,
        )
        if threshold_result is not None:
            return threshold_result

        return self._result(
            requirement=requirement,
            status=ComplianceStatus.PASS,
            reason="Financial capacity was verified and meets the tender-specific thresholds and consistency checks.",
            evidence_refs=[item.evidence_id for item in evidence if item.field_name in {"turnover", "net_worth", "audited_status", "solvency_indicator"}],
            verification_refs=[verifier.verification_id],
            flags=flags,
            actual={
                "status": verifier.status,
                "turnover": turnover_value,
                "net_worth": self._field_value(evidence, "net_worth"),
                "audited_status": self._field_value(evidence, "audited_status"),
                "solvency_indicator": self._field_value(evidence, "solvency_indicator"),
            },
        )

    def _threshold_evaluation(
        self,
        evidence: list[Evidence],
        requirement: Requirement,
        turnover_value: Any,
        annual_records: dict[int, dict[str, Any]],
    ) -> ComplianceResult | None:
        """Return a FAIL/MISSING result when the tender-specific thresholds are not met."""
        req = requirement.expected if isinstance(requirement.expected, dict) else {}
        params = requirement.parameters if isinstance(requirement.parameters, dict) else {}
        thresholds = {
            "turnover_threshold": req.get("turnover_threshold", params.get("turnover_threshold", 0)),
            "net_worth_threshold": req.get("net_worth_threshold", params.get("net_worth_threshold", 0)),
            "solvency_threshold": req.get("solvency_threshold", params.get("solvency_threshold", 0)),
            "audited_required": req.get("audited_required", params.get("audited_required", False)),
            "assessment_period_years": req.get("assessment_period_years", params.get("assessment_period_years", 1)),
        }

        if self._is_number(turnover_value) and turnover_value < thresholds["turnover_threshold"]:
            return self._result(
                requirement=requirement,
                status=ComplianceStatus.FAIL,
                reason=(
                    f"Turnover {turnover_value} is below the tender threshold of "
                    f"{thresholds['turnover_threshold']}."
                ),
                evidence_refs=[item.evidence_id for item in evidence if item.field_name == "turnover"],
                verification_refs=[],
                flags=[get_flag_definition("TURNOVER_BELOW_THRESHOLD").flag_id],
                actual={"turnover": turnover_value, "required": thresholds["turnover_threshold"]},
            )

        net_worth = self._field_value(evidence, "net_worth")
        if self._is_number(net_worth) and net_worth < thresholds["net_worth_threshold"]:
            return self._result(
                requirement=requirement,
                status=ComplianceStatus.FAIL,
                reason=(
                    f"Net worth {net_worth} is below the tender threshold of "
                    f"{thresholds['net_worth_threshold']}."
                ),
                evidence_refs=[item.evidence_id for item in evidence if item.field_name == "net_worth"],
                verification_refs=[],
                flags=[get_flag_definition("NET_WORTH_BELOW_THRESHOLD").flag_id],
                actual={"net_worth": net_worth, "required": thresholds["net_worth_threshold"]},
            )

        audited_status = self._field_value(evidence, "audited_status")
        if thresholds["audited_required"] and not self._valid_audited_status(audited_status):
            return self._result(
                requirement=requirement,
                status=ComplianceStatus.FAIL,
                reason="Audited status is required by the tender but is missing or invalid.",
                evidence_refs=[item.evidence_id for item in evidence if item.field_name == "audited_status"],
                verification_refs=[],
                flags=[get_flag_definition("AUDITED_STATUS_MISSING").flag_id],
                actual={"audited_status": audited_status},
            )

        solvency_indicator = self._field_value(evidence, "solvency_indicator")
        if self._is_number(solvency_indicator) and thresholds["solvency_threshold"] > 0:
            if solvency_indicator < thresholds["solvency_threshold"]:
                return self._result(
                    requirement=requirement,
                    status=ComplianceStatus.FAIL,
                    reason=(
                        f"Solvency indicator {solvency_indicator} is below the required threshold of "
                        f"{thresholds['solvency_threshold']}."
                    ),
                    evidence_refs=[item.evidence_id for item in evidence if item.field_name == "solvency_indicator"],
                    verification_refs=[],
                    flags=[get_flag_definition("SOLVENCY_THRESHOLD_NOT_MET").flag_id],
                    actual={"solvency_indicator": solvency_indicator, "required": thresholds["solvency_threshold"]},
                )

        if not self._financial_metrics_are_consistent(evidence):
            return self._result(
                requirement=requirement,
                status=ComplianceStatus.FAIL,
                reason="Financial data is inconsistent across the submitted evidence.",
                evidence_refs=[item.evidence_id for item in evidence if item.field_name in {"net_worth", "total_assets", "total_liabilities", "current_assets", "current_liabilities"}],
                verification_refs=[],
                flags=[get_flag_definition("FINANCIAL_DATA_INCONSISTENCY").flag_id],
                actual={"records": annual_records},
            )

        return None

    def _financial_year_entries(self, evidence: list[Evidence]) -> list[Evidence]:
        return [item for item in evidence if item.field_name == "financial_year"]

    def _group_by_year(self, evidence: list[Evidence]) -> dict[int, dict[str, Any]]:
        records: dict[int, dict[str, Any]] = {}
        for item in evidence:
            field = item.field_name
            if field == "financial_year":
                year = self._coerce_number(item.value)
                if year is not None:
                    records[int(year)] = {"year": int(year)}
            elif item.field_name in {"turnover", "net_worth", "audited_status", "solvency_indicator", "total_assets", "total_liabilities", "current_assets", "current_liabilities", "profit_after_tax"}:
                year = self._most_recent_year(evidence)
                if year is not None:
                    records.setdefault(int(year), {})[field] = item.value
        return records

    def _most_recent_year(self, evidence: list[Evidence]) -> int | None:
        years = [self._coerce_number(item.value) for item in evidence if item.field_name == "financial_year"]
        numbers = [int(year) for year in years if year is not None]
        return max(numbers) if numbers else None

    def _field_value(self, evidence: list[Evidence], field_name: str) -> Any:
        for item in evidence:
            if item.field_name == field_name:
                if item.value is None:
                    return None
                return item.value
        return None

    def _financial_metrics_are_consistent(self, evidence: list[Evidence]) -> bool:
        total_assets = self._field_value(evidence, "total_assets")
        total_liabilities = self._field_value(evidence, "total_liabilities")
        net_worth = self._field_value(evidence, "net_worth")
        current_assets = self._field_value(evidence, "current_assets")
        current_liabilities = self._field_value(evidence, "current_liabilities")

        if self._is_number(total_assets) and self._is_number(total_liabilities) and self._is_number(net_worth):
            expected_net_worth = total_assets - total_liabilities
            if not isclose(float(expected_net_worth), float(net_worth), rel_tol=0.01, abs_tol=1.0):
                return False
        if self._is_number(current_assets) and self._is_number(current_liabilities):
            ratio = float(current_assets) / float(current_liabilities) if float(current_liabilities) else 0.0
            if current_liabilities != 0 and ratio <= 0:
                return False
        return True

    def _valid_audited_status(self, value: Any) -> bool:
        return value is not None and str(value).strip().upper() in {"AUDITED", "AUDIT_COMPLETE"}

    def _assessment_years(self, requirement: Requirement) -> int:
        expected = requirement.expected if isinstance(requirement.expected, dict) else {}
        params = requirement.parameters if isinstance(requirement.parameters, dict) else {}
        return int(expected.get("assessment_period_years", params.get("assessment_period_years", 1)))

    def _is_number(self, value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _coerce_number(self, value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    def _bidder_id(self, evidence: list[Evidence]) -> str:
        for item in evidence:
            if item.bidder_id:
                return item.bidder_id
        return "unknown"

    def _missing(
        self,
        requirement: Requirement,
        reason: str,
        evidence_refs: list[str],
        flags: list[str],
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
            flags=flags,
            rule_id=requirement.rule_id,
        )

    def _result(
        self,
        *,
        requirement: Requirement,
        status: ComplianceStatus,
        reason: str,
        evidence_refs: list[str],
        verification_refs: list[str],
        flags: list[str],
        actual: Any,
    ) -> ComplianceResult:
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status=status,
            reason=reason,
            expected=requirement.expected,
            actual=actual,
            evidence_refs=evidence_refs,
            verification_refs=verification_refs,
            flags=flags,
            rule_id=requirement.rule_id,
        )

    def _reason(self, verification_status: VerificationStatus) -> str:
        return _REASONS[verification_status]

    def _actual(self, verification: Verification) -> dict[str, Any]:
        return {
            "status": verification.status,
            "data": verification.data,
        }
