"""Structured audit trace for cross-bidder document similarity."""

from __future__ import annotations

from enum import StrEnum

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
    """Evidence quality used when calibrating finding confidence."""

    model_config = ConfigDict(extra="forbid")

    ocr_confidence: float = Field(ge=0.0, le=1.0)
    field_confidence: float = Field(ge=0.0, le=1.0)
    quality_score: float = Field(ge=0.0, le=1.0)


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
