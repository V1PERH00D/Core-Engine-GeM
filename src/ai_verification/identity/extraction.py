"""Extract :class:`IdentityObservation` objects from Verification records.

The extractor is intentionally a thin mapping layer:

* It only reads ``Verification`` records that belong to one of the
  capabilities handled by the engine (GST, PAN, UDYAM, MCA).
* It only reads identity-bearing fields that already exist in the
  ``Verification.data`` payload produced by the upstream adapter.
* It never modifies the source ``Verification`` objects.
* It never opens the network.

The mapping of ``Verification.capability`` to source label is kept
in :data:`CAPABILITY_TO_SOURCE` so the mapping can be reviewed in
one place.
"""

from __future__ import annotations

from typing import Iterable, List

from compliance_engine.models.verification import (
    Verification,
    VerificationStatus,
)

from .models import IdentityObservation, SourceAvailability
from .normalization import NAME_NORMALIZATION_VERSION, normalize_legal_name


# ---------------------------------------------------------------------------
# Capability / source mapping
# ---------------------------------------------------------------------------


#: Map from the canonical Compliance Engine capability ID to the
#: identity-reconciliation source label.
CAPABILITY_TO_SOURCE: dict[str, str] = {
    "GST": "GST",
    "GSTN": "GST",
    "PAN": "PAN",
    "PAN_INCOME_TAX": "PAN",
    "UDYAM": "UDYAM",
    "MCA": "MCA",
    "MCA21": "MCA",
}

#: Map from source label to the identity-bearing field name in the
#: ``Verification.data`` payload produced by the upstream adapter.
SOURCE_IDENTITY_FIELD: dict[str, str] = {
    "GST": "legal_name",
    "PAN": "name_on_pan",
    "UDYAM": "enterprise_name",
    "MCA": "company_name",
}


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _classify(verification: Verification) -> SourceAvailability:
    """Collapse the upstream VerificationStatus into our taxonomy."""

    status = verification.status
    if status == VerificationStatus.VERIFIED:
        return SourceAvailability.VERIFIED
    if status == VerificationStatus.NOT_FOUND:
        return SourceAvailability.NOT_FOUND
    if status == VerificationStatus.INACTIVE:
        return SourceAvailability.INACTIVE
    if status in (
        VerificationStatus.UNAVAILABLE,
        VerificationStatus.ERROR,
        VerificationStatus.INVALID,
    ):
        return SourceAvailability.UNAVAILABLE
    return SourceAvailability.UNAVAILABLE


def extract_observations(
    verifications: Iterable[Verification],
    *,
    bidder_id: str | None = None,
) -> List[IdentityObservation]:
    """Return :class:`IdentityObservation` for every relevant verification.

    Parameters
    ----------
    verifications:
        The Verification records to consume. Records whose capability
        is not in :data:`CAPABILITY_TO_SOURCE` are silently skipped.
    bidder_id:
        Optional override; when supplied, the returned observations
        carry this bidder ID instead of the one on the record. When
        ``None`` (the default), each record's own ``bidder_id`` is
        used. This makes the extractor safe to use both for the
        "primary bidder" and for cross-bidder corpus.
    """

    observations: List[IdentityObservation] = []
    for record in verifications:
        source = CAPABILITY_TO_SOURCE.get(record.capability)
        if source is None:
            continue
        if bidder_id is not None and record.bidder_id != bidder_id:
            # Cross-bidder leak guard. If the caller restricts to a
            # bidder, we ignore records belonging to anyone else.
            continue

        availability = _classify(record)
        # If the upstream says VERIFIED but the identity field is
        # missing / null / empty, downgrade to VERIFIED_WITHOUT_NAME
        # so the comparison layer can tell the two apart.
        raw_value = _read_identity_field(record, source)
        normalized_value = normalize_legal_name(raw_value)

        if (
            availability == SourceAvailability.VERIFIED
            and (raw_value is None or normalized_value is None)
        ):
            availability = SourceAvailability.VERIFIED_WITHOUT_NAME

        observations.append(
            IdentityObservation(
                source=source,
                bidder_id=bidder_id or record.bidder_id,
                verification_id=record.verification_id,
                original_name=raw_value,
                normalized_name=normalized_value,
                source_status=availability,
                queried_identifier=record.queried_identifier,
                evidence_ref=record.evidence_id,
                document_ref=record.document_id,
                normalization_version=NAME_NORMALIZATION_VERSION,
            )
        )

    return observations


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_identity_field(
    record: Verification, source: str
) -> str | None:
    """Return the identity-bearing value, or ``None`` if missing/empty."""

    field_name = SOURCE_IDENTITY_FIELD.get(source)
    if field_name is None:  # pragma: no cover -- guarded by caller
        return None
    value = record.data.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        # We only accept string identities; non-string payloads are
        # treated as "no name" rather than crashing.
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned


__all__ = [
    "CAPABILITY_TO_SOURCE",
    "SOURCE_IDENTITY_FIELD",
    "extract_observations",
]