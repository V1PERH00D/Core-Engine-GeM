"""Module 2: per-document extracted fields.

Module 2 owns extraction. This module is the single place where a single
document's text is scanned ONCE with Module 2's existing extractors
(``extract_statutory_tokens`` and the Make-in-India regex fallback) to
produce the document-level extracted fields (Module 2 field names).

Outputs of Module 2 after this step:

* ``ConsolidatedBidderExtraction`` — the existing bidder-level
  consolidated output (unchanged);
* per-document ``extracted_fields`` — the document-level mapping
  persisted on the ``Document`` row so downstream modules (the
  Module 2 -> Evidence adapter, Module 3, Module 4, Module 5)
  MAP the values instead of re-extracting them.

Only fields actually found in the document are returned; nothing is
invented for absent fields.
"""

from __future__ import annotations

from typing import Any

from app.entity_extraction.llm_extractor import extract_mii_regex_fallback
from app.entity_extraction.regex_patterns import extract_statutory_tokens

# Module 2 statutory regex token keys surfaced as named per-document
# fields (values only when actually extracted in THIS document).
STATUTORY_TOKEN_KEYS: tuple[str, ...] = (
    "pan",       # PAN number
    "gstin",     # GST identification number
    "cin",       # Corporate identity number
    "udyam",     # Udyam registration number
    "udin",      # CA UDIN
    "epfo",      # EPFO code (kept for provenance)
    "esic",      # ESIC code (kept for provenance)
    "dpiit",     # DPIIT recognition (kept for provenance)
)


def extract_document_level_fields(classified_type: str | None, text: str) -> dict[str, Any]:
    """Run Module 2's existing extractors over ONE document's text.

    Returns a mapping of Module 2 field name -> extracted value. Only
    fields actually found in this document are returned; nothing is
    invented for absent fields.
    """
    if not text:
        return {}

    tokens = extract_statutory_tokens(text)
    fields: dict[str, Any] = {}
    for token_key in STATUTORY_TOKEN_KEYS:
        value = tokens.get(token_key)
        if value:
            fields[token_key] = value

    if (classified_type or "").strip().lower() == "make_in_india_local_content":
        mii = extract_mii_regex_fallback(text)
        if mii.declared_local_content_pct is not None:
            fields["declared_local_content_pct"] = mii.declared_local_content_pct
        if mii.supplier_class:
            fields["supplier_class"] = mii.supplier_class

    return fields


__all__ = ["STATUTORY_TOKEN_KEYS", "extract_document_level_fields"]
