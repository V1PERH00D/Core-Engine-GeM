"""Authoritative verification records from government or other sources."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field


class VerificationStatus(StrEnum):
    """Outcome of querying an authoritative source. Not a compliance conclusion."""

    VERIFIED = "VERIFIED"
    NOT_FOUND = "NOT_FOUND"
    INVALID = "INVALID"
    INACTIVE = "INACTIVE"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class Verification(BaseModel):
    """Payload returned by a government or other source adapter."""

    verification_id: str = Field(
        ..., description="Stable reference ID for this verification record."
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
        ..., description="Outcome of the source query (VERIFIED, NOT_FOUND, etc.)."
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
