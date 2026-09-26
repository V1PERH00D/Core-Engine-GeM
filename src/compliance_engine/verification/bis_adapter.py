"""Production-shaped BIS (Bureau of Indian Standards) verification adapter.

Mirrors the GSTN / Udyam / PAN / MCA adapter seam: a typed query, a typed
normalized payload, a parser that derives the *domain* ``VerificationStatus``
from the source payload (never the transport status code alone), and an
adapter that routes through the generic ``VerificationTransport``.

This module contains no network, credentials, scraping, or authentication
code and does not fabricate an official BIS endpoint or response contract.
Production integration still requires an authoritative BIS data source and
its authentication details, which are out of scope here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from compliance_engine.models import Capability, Verification, VerificationStatus
from compliance_engine.verification.base import VerificationProvider
from compliance_engine.verification.transport import (
    InProcessTransport,
    SourceResponseEnvelope,
    TransportError,
    VerificationTransport,
)


# ---------------------------------------------------------------------------
# Query / normalized data
# ---------------------------------------------------------------------------


class BisQuery(BaseModel):
    """Typed query for a future BIS certificate lookup."""

    model_config = ConfigDict(extra="forbid")

    bidder_id: str = Field(..., description="Bidder whose BIS certificate is queried.")
    certificate_number: str = Field(..., description="BIS license/certificate number.")
    call_id: str = Field(
        default_factory=lambda: uuid4().hex,
        description="Per-call UUID4 hex for a unique Verification.verification_id.",
    )


BisResponseEnvelope = SourceResponseEnvelope


class NormalizedBisData(BaseModel):
    """Minimum data the BIS compliance rule consumes."""

    model_config = ConfigDict(extra="forbid")

    licence_status: str | None = Field(
        None, description="BIS licence status, e.g. ACTIVE, SUSPENDED, REVOKED."
    )
    certificate_number: str | None = Field(None, description="BIS certificate number.")
    product_description: str | None = Field(
        None, description="Product(s) covered by the certification."
    )
    scope_of_certification: list[str] | None = Field(
        None, description="Explicit list of covered products, when available."
    )
    manufacturing_location: str | None = Field(
        None, description="Certified manufacturing facility location."
    )
    quality_grade: str | None = Field(None, description="Quality grade, when reported.")
    manufacturer: str | None = Field(None, description="Certified manufacturer name.")
    standard: str | None = Field(None, description="Standard / IS number, when reported.")
    valid_from: str | None = Field(None, description="Start of validity (ISO date).")
    valid_until: str | None = Field(None, description="End of validity (ISO date).")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class BisResponseParser:
    """Map a :class:`SourceResponseEnvelope` to a :class:`Verification`."""

    def parse(
        self,
        envelope: SourceResponseEnvelope,
        *,
        query: BisQuery,
        bidder_id: str,
    ) -> Verification:
        status, data = self._derive_domain_status(envelope)
        return Verification(
            verification_id=Verification.allocate_id(
                source=BisAdapter.SOURCE,
                identifier=query.certificate_number,
                call_id=query.call_id,
            ),
            bidder_id=bidder_id,
            capability=Capability.BIS,
            source=BisAdapter.SOURCE,
            queried_identifier=query.certificate_number,
            status=status,
            data=data,
            retrieved_at=datetime.now(UTC),
            query=query.model_dump(),
            raw_response=envelope.raw_response,
            latency_ms=envelope.latency_ms,
            correlation_id=envelope.correlation_id,
            transport_status_code=envelope.status_code,
        )

    @staticmethod
    def _derive_domain_status(
        envelope: SourceResponseEnvelope,
    ) -> tuple[VerificationStatus, dict[str, Any]]:
        raw = envelope.raw_response
        if not isinstance(raw, dict) or not raw:
            return VerificationStatus.NOT_FOUND, {}
        status = raw.get("licence_status")
        if status in ("ACTIVE", "VALID", "SUSPENDED", "REVOKED", "EXPIRED"):
            return VerificationStatus.VERIFIED, NormalizedBisData(
                licence_status=status,
                certificate_number=raw.get("certificate_number"),
                product_description=raw.get("product_description"),
                scope_of_certification=_as_str_list(raw.get("scope_of_certification")),
                manufacturing_location=raw.get("manufacturing_location"),
                quality_grade=raw.get("quality_grade"),
                manufacturer=raw.get("manufacturer"),
                standard=raw.get("standard"),
                valid_from=raw.get("valid_from"),
                valid_until=raw.get("valid_until"),
            ).model_dump()
        if status == "INVALID" or raw.get("certificate_status") == "INVALID":
            return VerificationStatus.INVALID, {}
        return VerificationStatus.ERROR, {}


def _as_str_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    if isinstance(value, str):
        return [value]
    return None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class BisAdapter(VerificationProvider):
    """Production-shaped BIS certificate adapter over the transport seam."""

    SOURCE: Final[str] = "BIS"

    def __init__(
        self,
        transport: VerificationTransport | None = None,
        parser: BisResponseParser | None = None,
    ) -> None:
        self._transport: VerificationTransport = transport or InProcessTransport()
        self._parser = parser or BisResponseParser()

    def verify(self, bidder_id: str, identifier: str, **kwargs: Any) -> Verification:
        query = BisQuery(bidder_id=bidder_id, certificate_number=str(identifier))
        try:
            envelope = self._transport.send_query(query)
        except (TransportError, NotImplementedError):
            return self._unavailable(query)
        return self._parser.parse(envelope, query=query, bidder_id=bidder_id)

    def _unavailable(self, query: BisQuery) -> Verification:
        return Verification(
            verification_id=Verification.allocate_id(
                source=self.SOURCE,
                identifier=query.certificate_number,
                call_id=query.call_id,
            ),
            bidder_id=query.bidder_id,
            capability=Capability.BIS,
            source=self.SOURCE,
            queried_identifier=query.certificate_number,
            status=VerificationStatus.UNAVAILABLE,
            data={},
            retrieved_at=datetime.now(UTC),
            query=query.model_dump(),
            raw_response=None,
            latency_ms=None,
            correlation_id=None,
            transport_status_code=None,
        )


__all__ = [
    "BisAdapter",
    "BisQuery",
    "BisResponseEnvelope",
    "BisResponseParser",
    "NormalizedBisData",
]