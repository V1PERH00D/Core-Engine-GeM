"""Structured audit trace for cross-bidder document similarity."""

from __future__ import annotations

from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SimilarityLayer(StrEnum):
    UNKNOWN = "UNKNOWN"
    """Similarity layer that produced the strongest finding."""

    EXACT = "EXACT"
    NORMALIZED = "NORMALIZED"
    LEXICAL = "LEXICAL"
    SEMANTIC = "SEMANTIC"


class CorroborationSignals(BaseModel):
    """Metadata signals supporting or weakening a similarity finding."""

    model_config = ConfigDict(extra="forbid")

    same_issuer: bool | None = None
    same_authorization_number: bool | None = None
    same_issue_date: bool | None = None
    validity_overlap: bool | None = None


class QualitySignals(BaseModel):
    """Evidence quality used when calibrating finding confidence.

    Three *legacy* scalar fields are kept for backward compatibility
    with existing tests and serialized traces:

    * ``ocr_confidence`` -- mean OCR confidence across the pair.
    * ``field_confidence`` -- mean field-confidence across the pair.
    * ``quality_score`` -- the overall quality score in ``[0.0, 1.0]``.

    The *new* fields populated by the evidence-quality engine are:

    * ``quality_state`` -- ``GOOD`` / ``DEGRADED`` / ``UNKNOWN``.
    * ``quality_reasons`` -- deterministic typed reason codes.
    * ``completeness`` -- per-pair completeness score in ``[0.0, 1.0]``.
    * ``ocr_quality`` -- per-pair OCR component score.
    * ``field_quality`` -- per-pair field component score.
    * ``metadata_reliability`` -- per-pair metadata component score.

    All new fields default to ``None`` (or empty list for the reason
    codes) so existing test fixtures that only construct the three
    legacy scalars keep working unchanged.
    """

    model_config = ConfigDict(extra="forbid")

    # Legacy fields: always populated. The detector continues to
    # compute them from the per-document metadata so existing
    # tests keep observing the same numeric values.
    ocr_confidence: float = Field(ge=0.0, le=1.0)
    field_confidence: float = Field(ge=0.0, le=1.0)
    quality_score: float = Field(ge=0.0, le=1.0)

    # New typed evidence-quality fields. Optional so existing
    # tests / serialized payloads remain valid. The detector
    # populates them whenever an :class:`EvidenceQualityEvaluator`
    # is wired in.
    quality_state: Optional[str] = Field(default=None)
    quality_reasons: list[str] = Field(default_factory=list)
    completeness: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    ocr_quality: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    field_quality: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    metadata_reliability: Optional[float] = Field(
        default=None, ge=0.0, le=1.0
    )


class TemplateGateStatus(StrEnum):
    """Relationship between unique document identifiers."""

    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


class TemplateGate(BaseModel):
    """Structured evidence for the legitimate-template gate."""

    model_config = ConfigDict(extra="forbid")

    status: TemplateGateStatus
    score: float = Field(ge=0.0, le=1.0)
    matched_fields: list[str] = Field(default_factory=list)
    mismatched_fields: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)


class SimilarityTrace(BaseModel):
    """Reproducible trace for a cross-bidder similarity finding."""

    model_config = ConfigDict(extra="forbid")

    layer: SimilarityLayer

    left_document_id: str
    right_document_id: str
    left_bidder_id: str
    right_bidder_id: str

    doc_type: str

    left_file_hash: str | None = None
    right_file_hash: str | None = None

    left_norm_text_hash: str | None = None
    right_norm_text_hash: str | None = None

    normalization_version: str

    similarity_score: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(ge=0.0, le=1.0)

    corroboration: CorroborationSignals
    quality: QualitySignals
    template_gate: TemplateGate

    confidence: float = Field(ge=0.0, le=1.0)

    embedding_model: str | None = None


__all__ = [
    "CorroborationSignals",
    "QualitySignals",
    "SimilarityLayer",
    "SimilarityTrace",
    "TemplateGate",
    "TemplateGateStatus",
]
