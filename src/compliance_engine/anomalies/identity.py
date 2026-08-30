"""Deterministic cross-document bidder identity verification."""

from __future__ import annotations

import re
from typing import Any

from compliance_engine.flags import get_flag_definition
from compliance_engine.models import Evidence, IdentityFinding

CROSS_DOCUMENT_IDENTITY_MISMATCH = get_flag_definition(
    "CROSS_DOCUMENT_IDENTITY_MISMATCH"
).flag_id

_IDENTITY_FIELD_ALIASES = {
    "GST": {"legal_name"},
    "GSTN": {"legal_name"},
    "PAN": {"name_on_pan"},
    "UDYAM": {"enterprise_name"},
    "MCA21": {"company_name"},
    "EPFO": {"establishment_name"},
    "ESIC": {"employer_name"},
    "STARTUP_INDIA": {"startup_name"},
    "DPIIT": {"startup_name"},
    "OEM": {"authorized_bidder"},
    "BIDDER_IDENTITY": {"legal_name"},
}

_IDENTITY_FIELDS = {
    field_name
    for names in _IDENTITY_FIELD_ALIASES.values()
    for field_name in names
}


def _strip_missing(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized or normalized.upper() == "NOT_PRESENT":
            return None
    return value


def normalize_identity_name(value: str | None) -> str | None:
    """Normalize a legal name to a deterministic canonical form."""

    if value is None:
        return None

    cleaned = str(value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.upper()
    cleaned = cleaned.replace("&", " AND ")
    cleaned = cleaned.replace("-", " ")
    cleaned = cleaned.replace(".", " ")
    cleaned = re.sub(r"[,/()]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    replacements = {
        " PRIVATE LIMITED": " PRIVATE LIMITED",
        " PVT LTD": " PRIVATE LIMITED",
        " PVT. LTD.": " PRIVATE LIMITED",
        " PVT LTD.": " PRIVATE LIMITED",
        " PRIVATE LTD": " PRIVATE LIMITED",
        " LIMITED": " LIMITED",
        " LTD": " LIMITED",
        " LTD.": " LIMITED",
        " LLP": " LLP",
        " LIMITED.": " LIMITED",
        " PVT": " PRIVATE",
    }

    for old, new in replacements.items():
        cleaned = re.sub(rf"\s+{re.escape(old.strip())}\b", new, cleaned)

    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.replace("  ", " ")
    return cleaned.lower()


def _identity_fields_for_document(document_type: str) -> set[str]:
    key = document_type.upper().replace(" ", "_")
    if key in {"GST", "GSTN"}:
        return _IDENTITY_FIELD_ALIASES["GST"]
    if key in {"PAN"}:
        return _IDENTITY_FIELD_ALIASES["PAN"]
    if key in {"UDYAM"}:
        return _IDENTITY_FIELD_ALIASES["UDYAM"]
    if key in {"MCA21", "MCA_21"}:
        return _IDENTITY_FIELD_ALIASES["MCA21"]
    if key in {"EPFO"}:
        return _IDENTITY_FIELD_ALIASES["EPFO"]
    if key in {"ESIC"}:
        return _IDENTITY_FIELD_ALIASES["ESIC"]
    if key in {"STARTUP", "STARTUP_INDIA", "DPIIT"}:
        return _IDENTITY_FIELD_ALIASES["STARTUP_INDIA"]
    if key in {"OEM", "OEM_AUTHORIZATION", "OEM_AUTHORIZATION_DOCUMENT"}:
        return _IDENTITY_FIELD_ALIASES["OEM"]
    if key in {"BIDDER_IDENTITY"}:
        return _IDENTITY_FIELD_ALIASES["BIDDER_IDENTITY"]
    return set()


def _candidate_pair(left: Evidence, right: Evidence) -> bool:
    if left.document_id == right.document_id and left.field_name == right.field_name:
        return False
    if left.bidder_id != right.bidder_id:
        return False
    return True


def verify_cross_document_identity(evidence: list[Evidence]) -> list[IdentityFinding]:
    """Compare identity-bearing evidence fields across documents.

    Missing, null, and NOT_PRESENT values are ignored. If only one identity-bearing value exists,
    no mismatch is raised. When multiple identity-bearing values disagree, the algorithm produces
    one deterministic mismatch using the dominant group and the first conflicting value.
    """

    identity_records: list[Evidence] = []
    for item in evidence:
        if item.value is None:
            continue
        value = item.value
        if isinstance(value, str):
            value = value.strip()
            if not value or value.upper() == "NOT_PRESENT":
                continue
        if item.field_name in _IDENTITY_FIELDS:
            identity_records.append(item)

    if len(identity_records) < 2:
        return []

    normalized_groups: dict[str, list[Evidence]] = {}
    order_index: dict[str, int] = {}
    for idx, record in enumerate(identity_records):
        order_index[record.evidence_id] = idx
        value = _strip_missing(record.value)
        if value is None or not isinstance(value, str):
            continue
        normalized = normalize_identity_name(value)
        if normalized is None:
            continue
        normalized_groups.setdefault(normalized, []).append(record)

    if len(normalized_groups) < 2:
        return []

    dominant_key, dominant_records = max(
        normalized_groups.items(),
        key=lambda item: (len(item[1]), -min(order_index[record.evidence_id] for record in item[1])),
    )
    dominant_record = min(dominant_records, key=lambda record: order_index[record.evidence_id])

    for candidate_key, candidate_records in normalized_groups.items():
        if candidate_key == dominant_key:
            continue
        conflicting_record = min(candidate_records, key=lambda record: order_index[record.evidence_id])
        left = dominant_record
        right = conflicting_record

        left_value = _strip_missing(left.value)
        right_value = _strip_missing(right.value)
        if left_value is None or right_value is None:
            continue
        if not isinstance(left_value, str) or not isinstance(right_value, str):
            continue

        left_normalized = normalize_identity_name(left_value)
        right_normalized = normalize_identity_name(right_value)
        if left_normalized is None or right_normalized is None:
            continue

        if left_normalized == right_normalized:
            continue

        canonical_flag_id = get_flag_definition("CROSS_DOCUMENT_IDENTITY_MISMATCH").flag_id
        return [
            IdentityFinding(
                flag_id=canonical_flag_id,
                capability="Bidder Identity",
                message=(
                    f"Identity-bearing fields differ after normalization: "
                    f"{left.document_type}:{left.field_name}={left_value!r} vs "
                    f"{right.document_type}:{right.field_name}={right_value!r}."
                ),
                evidence_refs=[left.evidence_id, right.evidence_id],
                compared_values=[left_value, right_value],
                normalized_values=[left_normalized, right_normalized],
                left_document_id=left.document_id,
                right_document_id=right.document_id,
            )
        ]

    return []
