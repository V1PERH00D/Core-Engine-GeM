"""Grounded explanation models for AI verification.

AI verification work is *explanation*, not risk. A
:class:`GroundedExplanation` answers "why was this flag true (or false)?"
with direct links to the underlying evidence, verification records,
documents, findings, and comparison traces.

Severity and risk are intentionally absent. An explanation carries the
canonical flag ID and the boolean flag state it explains, a concise and
optional detailed human-readable text, structured grounding references,
and generation metadata (including whether a deterministic fallback was
used when no generation model is available).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from compliance_engine.flags import get_flag_definition

from ai_verification.explanations.content import ExplanationContent
from ai_verification.explanations.grounding import ExplanationGrounding

EXPLANATION_SCHEMA_VERSION: int = 1


class GroundingKind(StrEnum):
    EVIDENCE = "EVIDENCE"
    VERIFICATION = "VERIFICATION"
    DOCUMENT = "DOCUMENT"
    COMPLIANCE_RESULT = "COMPLIANCE_RESULT"
    IDENTITY_FINDING = "IDENTITY_FINDING"
    VERIFICATION_FINDING = "VERIFICATION_FINDING"
    COMPARISON_TRACE = "COMPARISON_TRACE"
    FINANCIAL_RESULT = "FINANCIAL_RESULT"
    DEBARMENT_RESULT = "DEBARMENT_RESULT"
    QUALITY_ASSESSMENT = "QUALITY_ASSESSMENT"


class GroundingReference(BaseModel):
    """One real reference to a support artefact."""

    kind: GroundingKind
    ref_id: str
    note: str | None = None


class ExplanationGenerationMetadata(BaseModel):
    generator: str
    generator_version: str = "1"
    model: str | None = None
    model_version: str | None = None
    deterministic_fallback: bool = False
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str | None = None

    # Rich generator/validation metadata added by the explanation engine.
    # All optional so existing fallback/finding consumers remain valid.
    generator_type: str | None = None
    provider_name: str | None = None
    prompt_schema_version: int | None = None
    grounding_version: int | None = None
    validation_status: str | None = None
    fallback_used: bool | None = None
    input_hash: str | None = None


class GroundedExplanation(BaseModel):
    """A persisted, grounded explanation for one flag state."""

    explanation_id: str
    bidder_id: str
    flag_id: str
    flag_active: bool
    finding_refs: list[str] = Field(default_factory=list)
    concise_text: str
    detailed_text: str | None = None
    grounding: list[GroundingReference] = Field(default_factory=list)
    generation: ExplanationGenerationMetadata
    schema_version: int = EXPLANATION_SCHEMA_VERSION

    @field_validator("flag_id")
    @classmethod
    def _validate_flag_id(cls, v: str) -> str:
        return get_flag_definition(v).flag_id

    @classmethod
    def allocate_explanation_id(
        cls, bidder_id: str, flag_id: str, flag_active: bool
    ) -> str:
        """Deterministic, idempotent ID for one flag state.

        The same ``(bidder, flag, state)`` always yields the same ID so
        re-generating an explanation upserts rather than duplicates.
        """
        return f"expl:{bidder_id}:{flag_id}:{int(flag_active)}"


class ValidationStatus(StrEnum):
    """Outcome of grounding/claim validation for a generated explanation."""

    VALID = "VALID"
    GROUNDING_FAILED = "GROUNDING_FAILED"
    CLAIM_FAILED = "CLAIM_FAILED"
    FALLBACK = "FALLBACK"


class ExplanationResult(BaseModel):
    """The final, validated output of the explanation engine.

    This is the rich internal result (superset of the legacy
    :class:`GroundedExplanation`). ``flag_state`` mirrors the legacy
    ``flag_active`` boolean naming used elsewhere in the codebase.
    """

    model_config = ConfigDict(frozen=True)

    explanation_id: str
    bidder_id: str
    flag_id: str
    flag_state: bool

    content: ExplanationContent
    grounding: ExplanationGrounding
    generation: ExplanationGenerationMetadata

    validation_status: ValidationStatus = ValidationStatus.VALID
    fallback_used: bool = False
    schema_version: int = EXPLANATION_SCHEMA_VERSION

    @field_validator("flag_id")
    @classmethod
    def _validate_flag_id(cls, v: str) -> str:
        return get_flag_definition(v).flag_id

    @property
    def concise_text(self) -> str:
        return self.content.summary

    @property
    def detailed_text(self) -> str:
        return self.content.detailed_explanation

    @classmethod
    def allocate_explanation_id(
        cls, bidder_id: str, flag_id: str, flag_state: bool
    ) -> str:
        return GroundedExplanation.allocate_explanation_id(
            bidder_id, flag_id, flag_state
        )


__all__ = [
    "EXPLANATION_SCHEMA_VERSION",
    "ExplanationGenerationMetadata",
    "ExplanationResult",
    "GroundedExplanation",
    "GroundingKind",
    "GroundingReference",
    "ValidationStatus",
]