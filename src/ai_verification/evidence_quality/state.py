"""Quality state and reason enums for the evidence-quality engine.

This is split into its own module to avoid an import cycle: every
other evidence-quality module imports these enums, but they need
no other evidence-quality code.
"""

from __future__ import annotations

from enum import StrEnum


class QualityReason(StrEnum):
    """Deterministic reason codes explaining why a quality assessment
    is not perfect.

    The codes are intentionally coarse: they identify *what* the
    evidence pipeline was unable to establish, not *why* a particular
    document was scanned. They are stable strings; downstream code
    should switch on them rather than parse them.
    """

    OCR_LOW = "OCR_LOW"
    """OCR engine reported low per-character / per-token confidence."""

    OCR_MISSING = "OCR_MISSING"
    """OCR engine did not report any confidence value at all."""

    FIELD_CONFIDENCE_LOW = "FIELD_CONFIDENCE_LOW"
    """Field extraction pipeline reported low confidence for one or
    more of the fields the engine needed."""

    FIELD_CONFIDENCE_MISSING = "FIELD_CONFIDENCE_MISSING"
    """Field extraction pipeline did not report any confidence."""

    DOCUMENT_TEXT_MISSING = "DOCUMENT_TEXT_MISSING"
    """Document text could not be retrieved from the artifact store."""

    REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
    """One or more fields the engine requires for cross-bidder
    comparison were absent from the document metadata."""

    DOCUMENT_TYPE_CONFIDENCE_LOW = "DOCUMENT_TYPE_CONFIDENCE_LOW"
    """The document-type confidence is below the policy threshold."""

    METADATA_INCOMPLETE = "METADATA_INCOMPLETE"
    """No metadata is present for the document at all."""


class QualityState(StrEnum):
    """Overall health classification of an evidence bundle."""

    GOOD = "GOOD"
    """Quality signals are present and meet the policy thresholds."""

    DEGRADED = "DEGRADED"
    """Quality signals are present but degraded. The finding may be
    emitted with a conservative confidence."""

    UNKNOWN = "UNKNOWN"
    """One or more critical signals are missing. The engine cannot
    establish reliability and may need to suppress the finding
    depending on the gating policy."""


__all__ = ["QualityReason", "QualityState"]
