"""Explicit Module 1/2 -> Core (Module 4) canonical mapping.

Two mappings live here and ONLY here:

``DOC_TYPE_MAP``
    Module 1 classifier labels (``Document.classified_type``) to the
    canonical ``Evidence.document_type`` values understood by Core's
    ``FIELD_CLASSIFICATION`` table. Module 2 labels that have no
    corresponding Core classification map to themselves; Core treats
    those as NOT_QUERIED (never compared, never a false conflict).

``FIELD_RENAME_MAP``
    Module 2 extractor field names to Core canonical evidence field
    names. ONLY renames are listed; a field whose name is already
    canonical (and meaningful to Core's cross-document rules) passes
    through unchanged:

    Module 2 name                  ->  Core canonical name
    ----------------------------------------------------------
    pan                            ->  pan_number
    udyam                          ->  udyam_registration_number
    udin                           ->  ca_udin
    taxpayer_name                  ->  name_on_pan
    declared_local_content_pct     ->  local_content_percentage

    Pass-through (identity) fields that Core's cross-document engine
    recognizes: gstin, cin, registered_address, filing_date,
    assessment_year, financial_year, manufacturer, product_description,
    supplier_class, local_content_percentage.

Rules:
  * No field values are ever invented. If Module 2 does not extract a
    field, no Evidence is created for it (Core treats absence as
    MISSING and never converts absence into a conflict).
  * No field is silently dropped: fields not renamed pass through with
    their original Module 2 name; Core simply does not compare
    unrecognized (document_type, field_name) pairs.
"""

from __future__ import annotations

# Module 1 classifier label (app/services/classification.py) -> Core
# Evidence.document_type consumed by ai_verification.cross_document.
DOC_TYPE_MAP: dict[str, str] = {
    "gst_certificate": "GST",
    "pan_card": "PAN",
    "udyam_certificate": "UDYAM",
    "itr_acknowledgment": "ITR",
    "financial_statement": "BS",
    "make_in_india_local_content": "MAKE_IN_INDIA",
    "oem_authorization": "OEM_AUTHORIZATION",
    # The remaining Module 1 document kinds have no Core cross-document
    # field classification; they are kept verbatim for provenance and are
    # never compared by Core (NOT_QUERIED).
    "epfo_certificate": "EPFO",
    "esic_certificate": "ESIC",
    "startup_india_certificate": "STARTUP_INDIA",
    "nsic_certificate": "NSIC",
    "digilocker_document": "DIGILOCKER",
    "board_resolution_poa": "BOARD_RESOLUTION",
    "self_declaration": "SELF_DECLARATION",
    "blacklisting_debarment": "NON_BLACKLISTING",
    "unclassified": "UNKNOWN",
}

# 1 Module 2 extractor field name -> Core canonical field name.
# Identity mappings are intentionally NOT listed.
FIELD_RENAME_MAP: dict[str, str] = {
    # Module 2 regex token ``pan`` -> Core PAN identifier field.
    "pan": "pan_number",
    # Module 2 regex token ``udyam`` -> Core Udyam identifier field.
    "udyam": "udyam_registration_number",
    # Module 2 regex token ``udin`` -> Core CA UDIN identifier field.
    "udin": "ca_udin",
    # Module 2 PANITRExtraction.taxpayer_name -> Core canonical name field.
    "taxpayer_name": "name_on_pan",
    # Module 2 MakeInIndiaExtraction.declared_local_content_pct -> Core.
    "declared_local_content_pct": "local_content_percentage",
}


def map_document_type(module2_classification: str | None) -> str:
    """Translate a Module 1 classification label to a Core document_type."""
    return DOC_TYPE_MAP.get(module2_classification or "unclassified", "UNKNOWN")


def map_field_name(module2_field_name: str) -> str:
    """Translate a Module 2 extracted-field name to the Core canonical name."""
    return FIELD_RENAME_MAP.get(module2_field_name, module2_field_name)


__all__ = ["DOC_TYPE_MAP", "FIELD_RENAME_MAP", "map_document_type", "map_field_name"]
