"""Structured explanation content (the strict model output shape).

An LLM (or the deterministic fallback) must produce an
:class:`ExplanationContent`, never a free-form JSON blob. The ``observed_facts``
are required to point back at supplied fact IDs via ``fact_ref`` so the
grounding validator can check every structured claim against real, supplied
facts. Unsupported/invented values are rejected rather than silently
"repaired".
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StatementType(StrEnum):
    """The statement type of one observed fact claim."""

    ACTUAL_VALUE = "ACTUAL_VALUE"
    EXPECTED_VALUE = "EXPECTED_VALUE"
    THRESHOLD = "THRESHOLD"
    FINANCIAL_YEAR = "FINANCIAL_YEAR"
    VERIFICATION_STATUS = "VERIFICATION_STATUS"
    QUALITY_STATE = "QUALITY_STATE"
    COMPARISON_OUTCOME = "COMPARISON_OUTCOME"
    SIMILARITY_SCORE = "SIMILARITY_SCORE"
    SIMILARITY_THRESHOLD = "SIMILARITY_THRESHOLD"
    IDENTIFIER = "IDENTIFIER"
    NORMALIZED_VALUE = "NORMALIZED_VALUE"
    DOCUMENT_NAME = "DOCUMENT_NAME"
    DATE = "DATE"


class ObservedFact(BaseModel):
    """One structured claim that must resolve to a supplied fact.

    ``fact_ref`` is the supplied :class:`StructuredFact.fact_id`;
    ``source_ref`` backwards-points to the evidence/verification artefact
    the fact itself was sourced from (best-effort, must still be valid if
    supplied).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_ref: str = Field(..., description="Supplied fact ID this claim cites.")
    statement_type: StatementType = Field(
        ..., description="What kind of statement this claim makes."
    )
    source_ref: str | None = Field(default=None)

    @field_validator("fact_ref", "source_ref")
    @classmethod
    def _non_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("Reference must be non-empty.")
        return v


class ExplanationContent(BaseModel):
    """The strict, typed output of an explanation generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(..., min_length=1)
    detailed_explanation: str = Field(..., min_length=1)

    observed_facts: list[ObservedFact] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)

    evidence_refs: list[str] = Field(default_factory=list)
    verification_refs: list[str] = Field(default_factory=list)
    finding_refs: list[str] = Field(default_factory=list)

    recommended_review_actions: list[str] = Field(default_factory=list)

    @field_validator(
        "uncertainties",
        "evidence_refs",
        "verification_refs",
        "finding_refs",
        "recommended_review_actions",
    )
    @classmethod
    def _dedupe_strings(cls, v: list[str]) -> list[str]:
        if isinstance(v, list):
            seen: set[str] = set()
            ordered: list[str] = []
            for item in v:
                if item in seen or not isinstance(item, str):
                    continue
                seen.add(item)
                ordered.append(item)
            return ordered
        return v


__all__ = ["ExplanationContent", "ObservedFact", "StatementType"]