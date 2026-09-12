"""Typed structured facts supplied to the explanation engine.

A :class:`StructuredFact` is a *grounding* input, not an inference. The
explainer and its validator only ever reference facts the caller supplied;
they never scrape documents or re-derive values. Every fact carries an
explicit ``fact_id`` so the model's ``observed_facts`` can point back to a
real supplied fact instead of introducing free-form numbers.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FactKind(StrEnum):
    """Kinds of structured facts an explanation may cite."""

    ACTUAL_VALUE = "ACTUAL_VALUE"
    """An observed / actual value (e.g. a turnover number)."""

    EXPECTED_VALUE = "EXPECTED_VALUE"
    """An expected value from a requirement."""

    THRESHOLD = "THRESHOLD"
    """A numeric threshold that a value is compared against."""

    OPERATOR = "OPERATOR"
    """A comparison operator (>=, <=, ==, etc.)."""

    UNIT = "UNIT"
    """A unit of measure for a neighbouring numeric fact."""

    FINANCIAL_YEAR = "FINANCIAL_YEAR"
    """A financial year label (e.g. 2023-24)."""

    VERIFICATION_STATUS = "VERIFICATION_STATUS"
    """An authoritative source status (VERIFIED, NOT_FOUND, ...)."""

    QUALITY_STATE = "QUALITY_STATE"
    """Evidence quality state (GOOD / DEGRADED / UNKNOWN)."""

    COMPARISON_OUTCOME = "COMPARISON_OUTCOME"
    """A comparison outcome (MATCH / MISMATCH / ...)."""

    SIMILARITY_SCORE = "SIMILARITY_SCORE"
    """A similarity score in [0, 1]."""

    SIMILARITY_THRESHOLD = "SIMILARITY_THRESHOLD"
    """The threshold a similarity score was compared against."""

    IDENTIFIER = "IDENTIFIER"
    """An identifier value (GSTIN, PAN, ...)."""

    NORMALIZED_VALUE = "NORMALIZED_VALUE"
    """A deterministic normalization of an observed value."""

    DOCUMENT_NAME = "DOCUMENT_NAME"
    """A document reference/name."""

    DATE = "DATE"
    """A date value."""


class StructuredFact(BaseModel):
    """One structured, sourced fact available to the explanation engine.

    Only the fields that are actually present are populated; missing
    values are ``None`` and must not be manufactured by any consumer.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str = Field(..., description="Stable reference for this fact.")
    kind: FactKind = Field(..., description="What kind of fact this is.")

    value: Any = Field(default=None, description="Primary value of the fact.")
    field_name: str | None = Field(default=None)

    # Grounding pointers. Every claim must resolve to one of these.
    source_ref: str | None = Field(default=None)
    document_ref: str | None = Field(default=None)
    verification_ref: str | None = Field(default=None)

    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    normalized_value: str | None = Field(default=None)
    expected_value: Any = Field(default=None)
    actual_value: Any = Field(default=None)
    operator: str | None = Field(default=None)
    unit: str | None = Field(default=None)
    financial_year: str | None = Field(default=None)
    comparison_outcome: str | None = Field(default=None)
    similarity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    similarity_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_state: str | None = Field(default=None)

    def display_value(self) -> str:
        """A stable, plain-text rendering of the fact for fallback text."""

        if self.value is not None:
            unit = f" {self.unit}" if self.unit else ""
            return f"{self.value}{unit}"
        if self.normalized_value is not None:
            return self.normalized_value
        if self.actual_value is not None:
            return str(self.actual_value)
        if self.comparison_outcome is not None:
            return self.comparison_outcome
        if self.quality_state is not None:
            return self.quality_state
        return ""


__all__ = ["FactKind", "StructuredFact"]