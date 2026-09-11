"""Grounding and claim validation for generated explanations.

Every claim in a generated :class:`ExplanationContent` must resolve to an
artefact the caller actually supplied. This module performs the checks the
milestone requires: reference grounding, structured-claim resolution, and a
conservative textual guard that rejects invented numbers, years, dates and
identifiers. When validation fails the engine falls back to the
deterministic generator; invented content is never silently repaired.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ai_verification.explanations.content import (
    ExplanationContent,
    StatementType,
)
from ai_verification.explanations.facts import FactKind, StructuredFact
from ai_verification.explanations.grounding import (
    ExplanationGrounding,
    GroundingRefKind,
)
from ai_verification.explanations.models import ValidationStatus


class ValidationIssueCode(StrEnum):
    UNKNOWN_EVIDENCE_REF = "UNKNOWN_EVIDENCE_REF"
    UNKNOWN_VERIFICATION_REF = "UNKNOWN_VERIFICATION_REF"
    UNKNOWN_FINDING_REF = "UNKNOWN_FINDING_REF"
    UNKNOWN_SOURCE_REF = "UNKNOWN_SOURCE_REF"
    UNKNOWN_FACT_REF = "UNKNOWN_FACT_REF"
    STATEMENT_KIND_MISMATCH = "STATEMENT_KIND_MISMATCH"
    UNSUPPORTED_NUMBER = "UNSUPPORTED_NUMBER"
    UNSUPPORTED_FINANCIAL_YEAR = "UNSUPPORTED_FINANCIAL_YEAR"
    UNSUPPORTED_DATE = "UNSUPPORTED_DATE"
    UNSUPPORTED_IDENTIFIER = "UNSUPPORTED_IDENTIFIER"
    FORBIDDEN_CONCLUSION = "FORBIDDEN_CONCLUSION"
    STATE_MISREPRESENTED = "STATE_MISREPRESENTED"


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ValidationIssueCode
    detail: str


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ValidationStatus
    issues: tuple[ValidationIssue, ...]

    @property
    def is_valid(self) -> bool:
        return self.status is ValidationStatus.VALID

# Phrases an explanation may never utter because they assert an unsupported
# legal/intent conclusion or model-first framing.
_FORBIDDEN_PHRASES = (
    "fraud",
    "fraudulent",
    "collusion",
    "colluded",
    "forgery",
    "forged",
    "fabricat",
    "falsif",
    "manipulation",
    "illegal",
    "illegally",
    "criminal",
    "guilty",
    "deceptive",
    "deliberate",
    "the ai thinks",
    "the model thinks",
    "i believe",
    "i think",
)

_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
_FINANCIAL_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}-\d{2}\b")
_ISO_DATE_RE = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b")
_GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9][Z][A-Z0-9]\b")


def _numeric_token(value: str) -> float | None:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


_STATEMENT_ALLOWED_KINDS: dict[StatementType, frozenset[FactKind]] = {
    StatementType.ACTUAL_VALUE: frozenset({FactKind.ACTUAL_VALUE, FactKind.IDENTIFIER}),
    StatementType.EXPECTED_VALUE: frozenset({FactKind.EXPECTED_VALUE, FactKind.THRESHOLD}),
    StatementType.THRESHOLD: frozenset({FactKind.THRESHOLD, FactKind.EXPECTED_VALUE}),
    StatementType.FINANCIAL_YEAR: frozenset({FactKind.FINANCIAL_YEAR}),
    StatementType.VERIFICATION_STATUS: frozenset({FactKind.VERIFICATION_STATUS}),
    StatementType.QUALITY_STATE: frozenset({FactKind.QUALITY_STATE}),
    StatementType.COMPARISON_OUTCOME: frozenset({FactKind.COMPARISON_OUTCOME}),
    StatementType.SIMILARITY_SCORE: frozenset({FactKind.SIMILARITY_SCORE}),
    StatementType.SIMILARITY_THRESHOLD: frozenset({FactKind.SIMILARITY_THRESHOLD}),
    StatementType.IDENTIFIER: frozenset({FactKind.IDENTIFIER}),
    StatementType.NORMALIZED_VALUE: frozenset({FactKind.NORMALIZED_VALUE, FactKind.IDENTIFIER}),
    StatementType.DOCUMENT_NAME: frozenset({FactKind.DOCUMENT_NAME}),
    StatementType.DATE: frozenset({FactKind.DATE}),
}


def _statement_matches_fact(
    statement_type: StatementType, fact_kind: FactKind
) -> bool:
    return fact_kind in _STATEMENT_ALLOWED_KINDS.get(statement_type, frozenset())


def _claims_flag_true(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered for token in ("is true", "flag is active", "satisfied")
    )


def _claims_absence(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "not",
            "absent",
            "does not",
            "do not",
            "no evidence",
            "not found",
            "unavailable",
            "not established",
            "insufficient",
        )
    )


class GroundingValidator:
    """Validate generated content against the supplied grounding + facts."""

    def validate(
        self,
        *,
        content: ExplanationContent,
        grounding: ExplanationGrounding,
        facts: list[StructuredFact],
        flag_state: bool,
    ) -> ValidationReport:
        issues: list[ValidationIssue] = []

        issues.extend(self._check_reference_grounding(content, grounding))
        issues.extend(self._check_observed_facts(content, facts, grounding))
        issues.extend(
            self._check_textual_claims(
                f"{content.summary}\n{content.detailed_explanation}",
                facts,
                flag_state,
            )
        )

        claim_codes = {
            ValidationIssueCode.UNSUPPORTED_NUMBER,
            ValidationIssueCode.UNSUPPORTED_FINANCIAL_YEAR,
            ValidationIssueCode.UNSUPPORTED_DATE,
            ValidationIssueCode.UNSUPPORTED_IDENTIFIER,
            ValidationIssueCode.FORBIDDEN_CONCLUSION,
            ValidationIssueCode.STATEMENT_KIND_MISMATCH,
            ValidationIssueCode.UNKNOWN_FACT_REF,
            ValidationIssueCode.UNKNOWN_SOURCE_REF,
            ValidationIssueCode.STATE_MISREPRESENTED,
        }
        seen = {i.code for i in issues}
        if not seen:
            status = ValidationStatus.VALID
        elif seen & claim_codes:
            status = ValidationStatus.CLAIM_FAILED
        else:
            status = ValidationStatus.GROUNDING_FAILED
        return ValidationReport(status=status, issues=tuple(issues))

    def _check_reference_grounding(
        self,
        content: ExplanationContent,
        grounding: ExplanationGrounding,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        checks = (
            (
                GroundingRefKind.EVIDENCE,
                content.evidence_refs,
                ValidationIssueCode.UNKNOWN_EVIDENCE_REF,
            ),
            (
                GroundingRefKind.VERIFICATION,
                content.verification_refs,
                ValidationIssueCode.UNKNOWN_VERIFICATION_REF,
            ),
            (
                GroundingRefKind.FINDING,
                content.finding_refs,
                ValidationIssueCode.UNKNOWN_FINDING_REF,
            ),
        )
        for kind, refs, code in checks:
            known = grounding.known_ids(kind)
            for ref in refs:
                if ref not in known:
                    issues.append(
                        ValidationIssue(
                            code=code,
                            detail=(
                                f"Reference {ref!r} is not in the supplied "
                                "grounding."
                            ),
                        )
                    )
        return issues

    def _check_observed_facts(
        self,
        content: ExplanationContent,
        facts: list[StructuredFact],
        grounding: ExplanationGrounding,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        by_id = {f.fact_id: f for f in facts}
        all_grounding_ids = self._all_grounding_ids(grounding)

        for claim in content.observed_facts:
            fact = by_id.get(claim.fact_ref)
            if fact is None:
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.UNKNOWN_FACT_REF,
                        detail=f"Claim cites un-supplied fact {claim.fact_ref!r}.",
                    )
                )
                continue
            if not _statement_matches_fact(claim.statement_type, fact.kind):
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.STATEMENT_KIND_MISMATCH,
                        detail=(
                            f"Claim on {claim.fact_ref!r} has statement "
                            f"{claim.statement_type} but fact kind is {fact.kind}."
                        ),
                    )
                )
            if (
                claim.source_ref is not None
                and claim.source_ref not in all_grounding_ids
            ):
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.UNKNOWN_SOURCE_REF,
                        detail=f"Claim source {claim.source_ref!r} is not grounded.",
                    )
                )
        return issues

    @staticmethod
    def _all_grounding_ids(grounding: ExplanationGrounding) -> frozenset[str]:
        out: set[str] = set()
        for kind in GroundingRefKind:
            out |= set(grounding.known_ids(kind))
        return frozenset(out)

    # ------------------------------------------------------------------
    # Conservative textual guard against invented content
    # ------------------------------------------------------------------

    def _check_textual_claims(
        self,
        text: str,
        facts: list[StructuredFact],
        flag_state: bool,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        lowered = text.lower()
        for phrase in _FORBIDDEN_PHRASES:
            if phrase in lowered:
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.FORBIDDEN_CONCLUSION,
                        detail=f"Forbidden phrase {phrase!r} present.",
                    )
                )

        supported_numbers = self._supported_numbers(facts)
        masked_text = self._mask_years_dates_identifiers(text)
        for token in _NUMBER_RE.findall(masked_text):
            value = _numeric_token(token)
            if value is None:
                continue
            if not any(abs(value - s) < 1e-6 for s in supported_numbers):
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.UNSUPPORTED_NUMBER,
                        detail=f"Number {token!r} is not a supplied fact value.",
                    )
                )

        supported_years = self._supported_years(facts)
        for year in sorted(set(_FINANCIAL_YEAR_RE.findall(text))):
            if year not in supported_years:
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.UNSUPPORTED_FINANCIAL_YEAR,
                        detail=f"Financial year {year!r} is not a supplied fact.",
                    )
                )

        supported_dates = self._supported_dates(facts)
        for date in sorted(set(_ISO_DATE_RE.findall(text))):
            if date not in supported_dates:
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.UNSUPPORTED_DATE,
                        detail=f"Date {date!r} is not a supplied fact.",
                    )
                )

        supported_ids = self._supported_identifiers(facts)
        for identifier in sorted(set(_GSTIN_RE.findall(text))):
            if identifier not in supported_ids:
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.UNSUPPORTED_IDENTIFIER,
                        detail=f"Identifier {identifier!r} is not a supplied fact.",
                    )
                )

        if (
            not flag_state
            and _claims_flag_true(text)
            and not _claims_absence(text)
        ):
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.STATE_MISREPRESENTED,
                    detail="False flag explained as if the condition were present.",
                )
            )
        return issues

    @staticmethod
    def _supported_numbers(facts: list[StructuredFact]) -> list[float]:
        out: list[float] = []
        for fact in facts:
            for attr in (
                "value",
                "actual_value",
                "expected_value",
                "similarity_score",
                "similarity_threshold",
            ):
                raw = getattr(fact, attr)
                num = _numeric_token(str(raw)) if raw is not None else None
                if num is not None:
                    out.append(num)
        return out

    @staticmethod
    def _mask_years_dates_identifiers(text: str) -> str:
        """Replace year/date/identifier spans so their digits are not read
        as generic numbers during the numeric-invention guard."""
        spans = []
        for pattern in (_FINANCIAL_YEAR_RE, _ISO_DATE_RE, _GSTIN_RE):
            for match in pattern.finditer(text):
                spans.append((match.start(), match.end()))
        masked = text
        for start, end in sorted(spans, reverse=True):
            masked = masked[:start] + " " + masked[end:]
        return masked

    @staticmethod
    def _supported_years(facts: list[StructuredFact]) -> set[str]:
        out: set[str] = set()
        for fact in facts:
            for candidate in (fact.financial_year, fact.value, fact.normalized_value):
                if candidate is None:
                    continue
                out.update(_FINANCIAL_YEAR_RE.findall(str(candidate)))
        return out

    @staticmethod
    def _supported_dates(facts: list[StructuredFact]) -> set[str]:
        out: set[str] = set()
        for fact in facts:
            for candidate in (fact.value, fact.normalized_value):
                if candidate is None:
                    continue
                out.update(_ISO_DATE_RE.findall(str(candidate)))
        return out

    @staticmethod
    def _supported_identifiers(facts: list[StructuredFact]) -> set[str]:
        out: set[str] = set()
        for fact in facts:
            for candidate in (fact.value, fact.normalized_value):
                if candidate is None:
                    continue
                match = _GSTIN_RE.match(str(candidate))
                if match:
                    out.add(match.group(0))
        return out


__all__ = [
    "GroundingValidator",
    "ValidationIssue",
    "ValidationIssueCode",
    "ValidationReport",
]