"""Explanation strategy registry.

A strategy is the deterministic, testable unit that decides *how* one flag
is phrased (true vs false, absent vs unavailable) and which procurement-officer
review actions apply. Selection is driven by the flag's canonical
``capability`` and explicit flag-ID overrides — never scattered ``if
flag_id == ...`` logic across the repository.
"""

from __future__ import annotations

from typing import Protocol

from compliance_engine.flags import FlagDefinition

from ai_verification.explanations.facts import StructuredFact


class ExplanationStrategy(Protocol):
    name: str

    def applies(self, flag_id: str, capability: str) -> bool: ...

    def review_actions(
        self, *, flag_state: bool, facts: list[StructuredFact]
    ) -> list[str]: ...

    def uncertainty_note(self, *, flag_state: bool) -> str | None:
        return None


class _BaseStrategy:
    """Capability-driven strategy with optional explicit flag overrides."""

    name: str = "generic"
    capabilities: frozenset[str] = frozenset()
    flag_ids: frozenset[str] = frozenset()

    def applies(self, flag_id: str, capability: str) -> bool:
        if flag_id in self.flag_ids:
            return True
        return capability in self.capabilities

    def review_actions(
        self, *, flag_state: bool, facts: list[StructuredFact]
    ) -> list[str]:
        return ["Review the cited evidence and verification records."]

    def uncertainty_note(self, *, flag_state: bool) -> str | None:
        return None


class ComplianceFailureStrategy(_BaseStrategy):
    name = "compliance_failure"
    capabilities = frozenset({"Overall Bid-Level Assessment"})
    flag_ids = frozenset(
        {
            "TENDER_REQUIREMENT_THRESHOLD_NOT_MET",
            "TENDER_REQUIREMENT_EVIDENCE_INVALID",
            "BID_LEVEL_NON_COMPLIANT",
        }
    )

    def review_actions(self, *, flag_state, facts):
        return ["Review the cited requirement and its evidence before acting."]


class CompliancePassStrategy(_BaseStrategy):
    name = "compliance_pass"
    flag_ids = frozenset({"BID_LEVEL_COMPLIANT", "RECOMMENDATION_AUTOMATIC_ACCEPT"})

    def review_actions(self, *, flag_state, facts):
        if flag_state:
            return ["Confirm the cited positive evidence is current."]
        return ["Review why the pass condition is not established."]


class MissingEvidenceStrategy(_BaseStrategy):
    name = "missing_evidence"
    capabilities = frozenset({"Missing / Completeness Checks"})
    flag_ids = frozenset(
        {
            "REQUIRED_EVIDENCE_MISSING",
            "REQUIRED_FIELD_MISSING",
            "TURNOVER_DATA_MISSING",
            "ITR_MISSING",
            "GST_RETURN_EVIDENCE_MISSING",
            "GSTIN_MISSING",
            "GSTIN_NOT_FOUND",
        }
    )

    def review_actions(self, *, flag_state, facts):
        return ["Request the cited missing evidence from the bidder."]


class UnavailableVerificationStrategy(_BaseStrategy):
    name = "unavailable_verification"
    capabilities = frozenset({"Verification Infrastructure Checks"})

    def applies(self, flag_id, capability):
        if flag_id.endswith("_VERIFICATION_UNAVAILABLE") or flag_id in (
            "VERIFICATION_PROVIDER_UNAVAILABLE",
            "VERIFICATION_PROVIDER_TIMEOUT",
            "VERIFICATION_PROVIDER_ERROR",
            "CRITICAL_SOURCE_UNAVAILABLE",
        ):
            return True
        return capability in self.capabilities

    def review_actions(self, *, flag_state, facts):
        return [
            "Confirm the source verification result before taking action.",
            "Re-run the verification against the authoritative source.",
        ]

    def uncertainty_note(self, *, flag_state):
        return "The authoritative source did not return a usable result."
class IdentityMismatchStrategy(_BaseStrategy):
    name = "identity_mismatch"
    capabilities = frozenset({"Bidder Identity"})
    flag_ids = frozenset(
        {
            "CROSS_SOURCE_IDENTITY_MISMATCH",
            "GST_IDENTITY_MISMATCH",
            "PAN_IDENTITY_MISMATCH",
            "UDYAM_IDENTITY_MISMATCH",
            "COMPANY_IDENTITY_MISMATCH",
            "CA_IDENTITY_MISMATCH",
            "STARTUP_IDENTITY_MISMATCH",
        }
    )

    def review_actions(self, *, flag_state, facts):
        return [
            "Verify the conflicting registration names against the "
            "authoritative source."
        ]


class CrossDocumentMismatchStrategy(_BaseStrategy):
    name = "cross_document_mismatch"
    capabilities = frozenset({"Cross-Document Verification"})

    def review_actions(self, *, flag_state, facts):
        return [
            "Inspect the two cited documents and the fields that disagree."
        ]


class CrossBidderReuseStrategy(_BaseStrategy):
    name = "cross_bidder_reuse"
    flag_ids = frozenset(
        {"CROSS_BIDDER_DOCUMENT_REUSED", "EXACT_DUPLICATE_BIDDER_DETECTED"}
    )

    def review_actions(self, *, flag_state, facts):
        return [
            "Inspect the two cited documents and their similarity trace."
        ]


class SemanticNearDuplicateStrategy(_BaseStrategy):
    name = "semantic_near_duplicate"
    flag_ids = frozenset(
        {"CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE", "NEAR_DUPLICATE_BIDDER_DETECTED"}
    )

    def review_actions(self, *, flag_state, facts):
        return [
            "Inspect the two cited documents and their similarity trace."
        ]


class EvidenceQualityStrategy(_BaseStrategy):
    name = "evidence_quality"
    capabilities = frozenset({"Evidence Quality Checks"})

    def review_actions(self, *, flag_state, facts):
        return ["Review the affected document's scan and field quality."]


class DebarmentStrategy(_BaseStrategy):
    name = "debarment"
    capabilities = frozenset({"Blacklisting / Debarment"})

    def review_actions(self, *, flag_state, facts):
        return [
            "Confirm the restriction status against the authoritative source "
            "before taking action."
        ]


class FinancialThresholdStrategy(_BaseStrategy):
    name = "financial_threshold"
    flag_ids = frozenset(
        {
            "TURNOVER_BELOW_THRESHOLD",
            "SOLVENCY_THRESHOLD_NOT_MET",
            "SOLVENCY_REQUIREMENT_FAILED",
            "NET_WORTH_BELOW_THRESHOLD",
            "COVERED_EMPLOYEE_COUNT_BELOW_THRESHOLD",
            "EMPLOYEE_COUNT_BELOW_THRESHOLD",
        }
    )

    def review_actions(self, *, flag_state, facts):
        return [
            "Review the cited financial statements for the required "
            "financial years."
        ]


class FinancialInconsistencyStrategy(_BaseStrategy):
    name = "financial_inconsistency"
    flag_ids = frozenset(
        {
            "FINANCIAL_DATA_INCONSISTENCY",
            "ITR_DATA_INCONSISTENCY",
            "TAX_DATA_MISMATCH",
            "FINANCIAL_YEAR_MISMATCH",
            "CROSS_DOCUMENT_FINANCIAL_YEAR_MISMATCH",
            "TURNOVER_TREND_ANOMALY",
            "TURNOVER_PERIOD_MISMATCH",
        }
    )

    def review_actions(self, *, flag_state, facts):
        return [
            "Compare the cited figures across the financial years in the "
            "supporting statements."
        ]


class ReturnFilingStrategy(_BaseStrategy):
    name = "return_filing"
    flag_ids = frozenset(
        {
            "GST_RETURN_COMPLIANCE_ISSUE",
            "ITR_NOT_FILED",
            "ITR_OUTDATED",
            "EPFO_CONTRIBUTION_DEFAULT",
            "ESIC_CONTRIBUTION_DEFAULT",
        }
    )

    def applies(self, flag_id, capability):
        return flag_id in self.flag_ids

    def review_actions(self, *, flag_state, facts):
        return [
            "Confirm the return-filing status with the authoritative "
            "portal before acting."
        ]


class GenericStrategy(_BaseStrategy):
    name = "generic"

    def applies(self, flag_id, capability):
        return True

    def review_actions(self, *, flag_state, facts):
        return ["Review the cited evidence and verification records."]


_DEFAULT_ORDER: tuple[type[ExplanationStrategy], ...] = (
    DebarmentStrategy,
    FinancialThresholdStrategy,
    FinancialInconsistencyStrategy,
    SemanticNearDuplicateStrategy,
    CrossBidderReuseStrategy,
    ReturnFilingStrategy,
    CompliancePassStrategy,
    ComplianceFailureStrategy,
    MissingEvidenceStrategy,
    UnavailableVerificationStrategy,
    IdentityMismatchStrategy,
    CrossDocumentMismatchStrategy,
    EvidenceQualityStrategy,
    GenericStrategy,
)


class StrategyRegistry:
    """Inspectable, ordered mapping from flag/capability to a strategy."""

    def __init__(self) -> None:
        self._strategies: list[ExplanationStrategy] = [
            cls() for cls in _DEFAULT_ORDER  # type: ignore[abstract]
        ]

    def strategies(self) -> list[ExplanationStrategy]:
        return list(self._strategies)

    def select(self, definition: FlagDefinition) -> ExplanationStrategy:
        for strategy in self._strategies:
            if strategy.applies(definition.flag_id, definition.capability):
                return strategy
        return GenericStrategy()

    def register(self, strategy: ExplanationStrategy) -> None:
        """Prepend a custom strategy (extensibility seam)."""

        self._strategies.insert(0, strategy)


#: Shared default registry.
default_registry = StrategyRegistry()


__all__ = [
    "ExplanationStrategy",
    "StrategyRegistry",
    "default_registry",
]