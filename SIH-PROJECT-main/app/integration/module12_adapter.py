"""Adapter: Module 1/2 extraction output -> Core (Module 4) Evidence.

The adapter is the ONLY place that translates between the two systems:

  * The PRIMARY path maps the per-document fields Module 2 already
    extracted (``Document.extracted_fields``, produced once during
    Module 2's entity-extraction job). The adapter never re-extracts.
  * A legacy fallback (documents processed before per-document fields
    existed, or plain-text fixtures) delegates to Module 2's OWN
    :func:`app.entity_extraction.document_fields
    .extract_document_level_fields` — Module 2 stays the single owner
    of extraction; bidder-level concatenated text is NEVER used, so
    document provenance is preserved.
  * Field names pass through :func:`map_field_name` (explicit mapping).
  * The resulting payload is validated by the integration contract models
    and handed to Core's own ``normalize_upstream`` — the canonical,
    deterministic Evidence builder. Evidence IDs follow Core's scheme
    ``<document_id>:<field_name>``.
  * confidence / page / bbox are only populated when the upstream
    extraction actually provides them. Module 2's regex extraction does
    not, so they stay ``None`` — never fabricated.
"""

from __future__ import annotations

from typing import Any, Iterable

from compliance_engine.ingestion.upstream import normalize_upstream
from compliance_engine.models import Evidence

from ai_verification.document_scoring import DocumentInput

# Module 2 owns extraction; the adapter only delegates to it for the
# legacy no-stored-fields path. No extractor logic lives here.
from app.entity_extraction.document_fields import (
    extract_document_level_fields as _module2_extract_document_fields,
)

from .contracts import ExtractedField, UpstreamDocument, UpstreamExtractionPayload
from .field_mapping import map_document_type, map_field_name


def _doc_attr(doc: Any, name: str) -> Any:
    if isinstance(doc, dict):
        return doc.get(name)
    return getattr(doc, name, None)


def _doc_text(doc: Any) -> str:
    return _doc_attr(doc, "extracted_text") or _doc_attr(doc, "raw_text") or ""


def _document_id_of(doc: Any) -> str:
    return str(_doc_attr(doc, "id") or _doc_attr(doc, "document_id"))


def _classified_type_of(doc: Any) -> str | None:
    return (
        _doc_attr(doc, "classified_type")
        or _doc_attr(doc, "classification_type")
        or _doc_attr(doc, "doc_type")
    )


def extract_document_fields(classified_type: str | None, text: str) -> dict[str, Any]:
    """Delegate ONE document's extraction to Module 2, then apply the
    explicit field-name mapping.

    Returns a mapping of Core-canonical field name -> extracted value.
    Only fields actually found in this document are returned; nothing is
    invented for absent fields.
    """
    module2_fields = _module2_extract_document_fields(classified_type, text)
    return {
        map_field_name(name): value
        for name, value in module2_fields.items()
        if value is not None
    }


def document_to_payload_document(doc: Any) -> UpstreamDocument:
    """Build one contract-validated upstream document from a Module 1/2
    document record (ORM ``Document`` row or dict with the same fields)."""
    document_id = _document_id_of(doc)
    classified_type = _classified_type_of(doc)
    raw_fields: dict[str, Any] | None = _doc_attr(doc, "extracted_fields")

    if raw_fields is not None:
        # Document-level extracted fields supplied directly (e.g. an
        # upgraded Module 2 extractor or an integration fixture). Names are
        # Module 2 style and go through the same explicit rename mapping.
        fields = {
            map_field_name(name): value
            for name, value in raw_fields.items()
            if value is not None
        }
    else:
        fields = extract_document_fields(classified_type, _doc_text(doc))

    return UpstreamDocument(
        document_id=document_id,
        doc_type=map_document_type(classified_type),
        extracted_fields={name: ExtractedField(value=value) for name, value in fields.items()},
    )


def build_upstream_payload(
    bidder_id: str,
    documents: Iterable[Any],
    *,
    submission_id: str | None = None,
) -> dict[str, Any]:
    """Build the validated document-level payload for one bidder."""
    payload = UpstreamExtractionPayload(
        submission_id=submission_id or str(bidder_id),
        bidder_id=str(bidder_id),
        documents=[document_to_payload_document(d) for d in documents],
    )
    return payload.model_dump()


def build_bidder_evidence(
    bidder_id: str,
    documents: Iterable[Any],
    *,
    submission_id: str | None = None,
) -> list[Evidence]:
    """Convert one bidder's processed documents into canonical Core Evidence.

    Every Evidence record keeps ``document_id`` / ``document_type`` /
    ``field_name`` / ``value`` and the deterministic evidence id
    ``<document_id>:<field_name>`` assigned by Core.
    """
    payload = build_upstream_payload(bidder_id, documents, submission_id=submission_id)
    return normalize_upstream(payload)


def build_document_inputs(documents: Iterable[Any]) -> list[DocumentInput]:
    """Build Core ``DocumentInput`` metadata for the SAME documents.

    The ``document_type`` is the exact Core-canonical type the Evidence
    adapter produces (``map_document_type``), so the existing
    ``DocumentScoringEngine`` scores the same document identities that
    Module 4 verified. Documents that produced no extractable fields are
    still included — the scoring engine applies its own ``NO_EVIDENCE``
    policy to them.
    """
    return [
        DocumentInput(
            document_id=_document_id_of(doc),
            document_type=map_document_type(_classified_type_of(doc)),
        )
        for doc in documents
    ]


__all__ = [
    "build_bidder_evidence",
    "build_document_inputs",
    "build_upstream_payload",
    "document_to_payload_document",
    "extract_document_fields",
]
