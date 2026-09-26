"""Contract models for the Module 1/2 -> Module 4 boundary.

These pydantic models describe the document-level extraction payload the
adapter hands to Core's ``compliance_engine.ingestion.upstream
.normalize_upstream``. They deliberately mirror the *relevant* shape of
Core-Engine-GeM ``schemas/module1_input.schema.json`` (submission_id,
bidder_id, documents[].document_id / doc_type / extracted_fields) — with
one honest difference: ``doc_type_confidence`` / ``ocr_confidence`` /
``confidence`` / ``page`` / ``bbox`` are OPTIONAL here, because Module 1/2
does not always produce them, and they must remain ``None`` rather than
being fabricated (see the integration spec, "do not fake provenance or
confidence").

Neither Module 2 schemas nor Core models are reused directly: this module
is the explicit translation boundary.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExtractedField(BaseModel):
    """One extracted field on one document.

    ``confidence`` / ``page`` / ``bbox`` stay ``None`` unless the upstream
    extraction actually produced them.
    """

    model_config = ConfigDict(extra="forbid")

    value: Any = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    page: int | None = None
    bbox: list[float] | None = None


class UpstreamDocument(BaseModel):
    """One processed document of one bidder."""

    model_config = ConfigDict(extra="allow")

    document_id: str
    doc_type: str
    extracted_fields: dict[str, ExtractedField] = Field(default_factory=dict)


class UpstreamExtractionPayload(BaseModel):
    """The document-level payload handed to ``normalize_upstream``."""

    model_config = ConfigDict(extra="forbid")

    submission_id: str
    bidder_id: str
    documents: list[UpstreamDocument] = Field(min_length=1)


__all__ = ["ExtractedField", "UpstreamDocument", "UpstreamExtractionPayload"]
