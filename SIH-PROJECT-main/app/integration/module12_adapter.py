"""Adapter: Module 1/2 extraction output -> Core (Module 4) Evidence.

The adapter is the ONLY place that translates between the two systems:

  * Per-document text is re-scanned with Module 2's EXISTING extractors
    (:func:`extract_statutory_tokens` and the Make-in-India regex
    fallback). Bidder-level concatenated text is NEVER used here —
    document provenance would be destroyed (Phase 5 of the spec).
  * Field names pass through :func:`map_field_name` (explicit mapping).
  * The resulting payload is validated by the integration contract models
    and handed to Core's own ``normalize_upstream`` — the canonical,
    deterministic Evidence builder. Evidence IDs follow Core's scheme
    ``<document_id>:<field_name>`` (Phase 7 of the spec).
  * confidence / page / bbox are only populated when the upstream
    extraction actually provides them. Module 2's regex extraction does
    not, so they stay ``None`` — never fabricated.
"""

from __future__ import annotations

from typing import Any, Iterable

from compliance_engine.ingestion.upstream import normalize_upstream
from compliance_engine.models import Evidence

from app.entity_extraction.llm_extractor import extract_mii_regex_fallback
from app.entity_extraction.regex_patterns import extract_statutory_tokens

from .contracts import ExtractedField, UpstreamDocument, UpstreamExtractionPayload
from .field_mapping import map_document_type, map_field_name

# Module 2 statutory regex token keys that are surfaced as named
# per-document Evidence fields (values only when actually extracted).
_STATUTORY_TOKEN_KEYS: tuple[str, ...] = (
    "pan",       # -> pan_number
    "gstin",     # -> gstin
    "cin",       # -> cin
    "udyam",     # -> udyam_registration_number
    "udin",      # -> ca_udin
    "epfo",      # -> epfo (not compared by Core; kept for provenance)
    "esic",      # -> esic (not compared by Core; kept for provenance)
    "dpiit",     # -> dpiit (not compared by Core; kept for provenance)
)


def _doc_attr(doc: Any, name: str) -> Any:
    if isinstance(doc, dict):
        return doc.get(name)
    return getattr(doc, name, None)


def _doc_text(doc: Any) -> str:
    return _doc_attr(doc, "extracted_text") or _doc_attr(doc, "raw_text") or ""


def extract_document_fields(classified_type: str | None, text: str) -> dict[str, Any]:
    """Run Module 2's existing extractors over ONE document's text.

    Returns a mapping of Core-canonical field name -> extracted value.
    Only fields actually found in this document are returned; nothing is
    invented for absent fields.
    """
    if not text:
        return {}

    tokens = extract_statutory_tokens(text)
    fields: dict[str, Any] = {}
    for token_key in _STATUTORY_TOKEN_KEYS:
        value = tokens.get(token_key)
        if value:
            fields[map_field_name(token_key)] = value

    if map_document_type(classified_type) == "MAKE_IN_INDIA":
        mii = extract_mii_regex_fallback(text)
        if mii.declared_local_content_pct is not None:
            fields[map_field_name("declared_local_content_pct")] = (
                mii.declared_local_content_pct
            )
        if mii.supplier_class:
            fields["supplier_class"] = mii.supplier_class

    return fields


def document_to_payload_document(doc: Any) -> UpstreamDocument:
    """Build one contract-validated upstream document from a Module 1/2
    document record (ORM ``Document`` row or dict with the same fields)."""
    document_id = str(_doc_attr(doc, "id") or _doc_attr(doc, "document_id"))
    classified_type = (
        _doc_attr(doc, "classified_type")
        or _doc_attr(doc, "classification_type")
        or _doc_attr(doc, "doc_type")
    )
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


__all__ = [
    "build_bidder_evidence",
    "build_upstream_payload",
    "document_to_payload_document",
    "extract_document_fields",
]
