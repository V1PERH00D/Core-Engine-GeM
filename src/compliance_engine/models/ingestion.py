"""Ingestion envelope for one upstream extraction payload.

These models preserve submission- and document-level metadata that does
not belong on field-level :class:`Evidence` records. They are the
normalized boundary artefact of the ingestion layer: field-level content
lives in ``Evidence``; document- and submission-level lineage lives here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from compliance_engine.models.evidence import Confidence, Evidence


class GroundingMetadata(BaseModel):
    """Per-document grounding metadata supplied by upstream extraction."""

    field_confidence: dict[str, Confidence] = Field(default_factory=dict)
    overall_grounding_score: Confidence | None = None
    is_reliable: bool | None = None


class NormalizedDocument(BaseModel):
    """One upstream document: document-level metadata plus its Evidence."""

    document_id: str
    doc_type: str
    doc_type_confidence: Confidence | None = None
    ocr_confidence: Confidence | None = None
    file_hash: str | None = None
    grounding: GroundingMetadata | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class NormalizedSubmission(BaseModel):
    """Normalized ingestion artefact for one upstream submission payload."""

    submission_id: str
    bidder_id: str
    documents: list[NormalizedDocument] = Field(default_factory=list)

    @property
    def evidence(self) -> list[Evidence]:
        """Flattened field-level Evidence across all documents."""

        return [item for document in self.documents for item in document.evidence]


__all__ = [
    "GroundingMetadata",
    "NormalizedDocument",
    "NormalizedSubmission",
]
