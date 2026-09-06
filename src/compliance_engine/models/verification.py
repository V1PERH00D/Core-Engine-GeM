"""Authoritative verification records from government or other sources."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, ClassVar, Optional

from pydantic import BaseModel, ConfigDict, Field


class VerificationStatus(StrEnum):
    """Outcome of querying an authoritative source. Not a compliance conclusion."""

    VERIFIED = "VERIFIED"
    NOT_FOUND = "NOT_FOUND"
    INVALID = "INVALID"
    INACTIVE = "INACTIVE"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class Verification(BaseModel):
    """Payload returned by a government or other source adapter.

    The model is **frozen**: every adapter, rule, and engine call must
    treat a ``Verification`` as an immutable audit artefact. New
    variants of a record (e.g. evidence/document linkage enrichment
    from a rule) are produced via :meth:`model_copy`.
    """

    model_config = ConfigDict(frozen=True)

    verification_id: str = Field(
        ...,
        description=(
            "Unique reference ID for this verification event. Two "
            "verification calls for the same source + identifier must "
            "produce distinct IDs."
        ),
    )
    bidder_id: str = Field(
        ..., description="Identifier of the bidder this verification applies to."
    )
    capability: str = Field(
        ..., description="Canonical capability ID (e.g. GST, PAN, UDYAM)."
    )
    source: str = Field(
        ..., description="Identifier of the verification source (e.g. GSTN_MOCK, PAN_MOCK)."
    )
    queried_identifier: str | None = Field(
        None, description="The identifier that was queried against the source."
    )
    status: VerificationStatus = Field(
        ...,
        description=(
            "DOMAIN outcome of the source query (VERIFIED, NOT_FOUND, "
            "etc.). Determined from the source payload, never from the "
            "raw transport status code alone."
        ),
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form payload returned by the source adapter.",
    )
    retrieved_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Wall-clock time at which the verification was retrieved.",
    )

    # --- NEW optional audit fields (all backward-compatible, default None) ---

    evidence_id: str | None = Field(
        None,
        description="Links this verification to the Evidence item that triggered the query.",
    )
    document_id: str | None = Field(
        None,
        description="Links this verification to the DocumentMeta item, if applicable.",
    )
    query: dict[str, Any] | None = Field(
        None,
        description="Full query parameters sent to the source, for auditability.",
    )
    raw_response: dict[str, Any] | str | None = Field(
        None,
        description="Raw response from the source, before parsing into `data`.",
    )
    latency_ms: int | None = Field(
        None,
        description="Round-trip latency of the source query, in milliseconds.",
    )
    correlation_id: str | None = Field(
        None,
        description="End-to-end trace ID correlating this query with other system events.",
    )
    transport_status_code: int | None = Field(
        None,
        description=(
            "Advisory transport-layer status code. Stored for audit only. "
            "MUST NOT be used as the sole determinant of `status`."
        ),
    )

    # ------------------------------------------------------------------
    # Canonical id generator
    # ------------------------------------------------------------------

    #: Separator used inside canonical verification IDs.
    ID_SEPARATOR: ClassVar[str] = ":"

    @classmethod
    def allocate_id(
        cls, source: str, identifier: str, call_id: str
    ) -> str:
        """Return a unique verification ID for one verification event.

        The format is ``"{source}:{identifier}:{call_id}"``. Every
        adapter calls this exactly once per :meth:`verify` call so two
        consecutive calls for the same ``(source, identifier)`` produce
        distinct IDs (the ``call_id`` differs).
        """
        if not source or not identifier or not call_id:
            raise ValueError(
                "Verification.allocate_id requires non-empty "
                "source, identifier, and call_id."
            )
        return f"{source}{cls.ID_SEPARATOR}{identifier}{cls.ID_SEPARATOR}{call_id}"
