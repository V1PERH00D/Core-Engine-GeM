"""Production-shaped Udyam verification adapter.

This module provides :class:`UdyamAdapter`, a
:class:`VerificationProvider` subclass that demonstrates the adapter
boundary a real Udyam integration would need, without performing any
network I/O. It mirrors the GSTN adapter's structure so the engine
can be source-agnostic.

This module contains **no** network, credentials, scraping, or
authentication code.
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


class UdyamQuery(BaseModel):
    """Typed query for a future Udyam request."""

    model_config = ConfigDict(extra="forbid")

    bidder_id: str = Field(
        ..., description="Bidder whose Udyam registration is being verified."
    )
    udyam_registration_number: str = Field(
        ..., description="The Udyam registration number being queried."
    )
    call_id: str = Field(
        default_factory=lambda: uuid4().hex,
        description=(
            "Per-call UUID4 hex. Used to produce a unique "
            "Verification.verification_id even when the same source "
            "+ identifier is queried more than once."
        ),
    )


# Source-specific response envelope. The transport seam is generic;
# the source-specific shape is in the parser.
UdyamResponseEnvelope = SourceResponseEnvelope


class NormalizedUdyamData(BaseModel):
    """The minimum data the Udyam compliance rule consumes."""

    model_config = ConfigDict(extra="forbid")

    registration_status: str = Field(
        ..., description='"ACTIVE" or "INACTIVE" as reported by Udyam.'
    )
    enterprise_name: str | None = Field(
        None, description="Enterprise name on record."
    )
    enterprise_category: str | None = Field(
        None, description='Enterprise category, e.g. "Micro", "Small", "Medium".'
    )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class UdyamResponseParser:
    """Map a :class:`SourceResponseEnvelope` to a :class:`Verification`.

    The domain :class:`VerificationStatus` is derived from the source
    PAYLOAD, not from the transport ``status_code``. The transport
    status is preserved on the returned :class:`Verification` for
    audit only.
    """

    def parse(
        self,
        envelope: SourceResponseEnvelope,
        *,
        query: UdyamQuery,
        bidder_id: str,
    ) -> Verification:
        status, data = self._derive_domain_status(envelope, query)
        raw = envelope.raw_response
        transport_status = envelope.status_code

        return Verification(
            verification_id=Verification.allocate_id(
                source=UdyamAdapter.SOURCE,
                identifier=query.udyam_registration_number,
                call_id=query.call_id,
            ),
            bidder_id=bidder_id,
            capability=Capability.UDYAM,
            source=UdyamAdapter.SOURCE,
            queried_identifier=query.udyam_registration_number,
            status=status,
            data=data,
            retrieved_at=datetime.now(UTC),
            query=query.model_dump(),
            raw_response=raw,
            latency_ms=envelope.latency_ms,
            correlation_id=envelope.correlation_id,
            transport_status_code=transport_status,
        )

    def _derive_domain_status(
        self,
        envelope: SourceResponseEnvelope,
        query: UdyamQuery,
    ) -> tuple[VerificationStatus, dict[str, Any]]:
        code = envelope.status_code
        raw = envelope.raw_response

        if 500 <= code < 600:
            return VerificationStatus.UNAVAILABLE, {}

        if 400 <= code < 500:
            if raw is None:
                return VerificationStatus.NOT_FOUND, {}
            if "registration_status" in raw:
                status = self._status_from_payload(raw)
                data = self._safe_extract_data(raw, status)
                return status, data
            return VerificationStatus.INVALID, {}

        if 200 <= code < 300:
            if raw is None:
                return VerificationStatus.ERROR, {}
            status = self._status_from_payload(raw)
            data = self._safe_extract_data(raw, status)
            return status, data

        return VerificationStatus.ERROR, {}

    @staticmethod
    def _status_from_payload(raw: dict[str, Any]) -> VerificationStatus:
        value = raw.get("registration_status")
        if value == "ACTIVE":
            return VerificationStatus.VERIFIED
        if value == "INACTIVE":
            return VerificationStatus.INACTIVE
        if value == "INVALID":
            return VerificationStatus.INVALID
        if value is None:
            return VerificationStatus.NOT_FOUND
        return VerificationStatus.ERROR

    @staticmethod
    def _safe_extract_data(
        raw: dict[str, Any], status: VerificationStatus
    ) -> dict[str, Any]:
        if status not in (
            VerificationStatus.VERIFIED,
            VerificationStatus.INACTIVE,
        ):
            return {}
        try:
            return NormalizedUdyamData(
                registration_status=raw.get("registration_status", "UNKNOWN"),
                enterprise_name=raw.get("enterprise_name"),
                enterprise_category=raw.get("enterprise_category"),
            ).model_dump()
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class UdyamAdapter(VerificationProvider):
    """A production-shaped Udyam adapter.

    Implements the existing :meth:`VerificationProvider.verify`
    contract so :class:`ComplianceEngine` and
    :class:`UdyamRegistrationRule` work unchanged. Routes through a
    transport seam and a parser seam so the network and parsing
    concerns can be replaced without touching the rule engine.
    """

    SOURCE: Final[str] = "UDYAM"

    def __init__(
        self,
        transport: VerificationTransport | None = None,
        parser: UdyamResponseParser | None = None,
    ) -> None:
        self._transport: VerificationTransport = transport or InProcessTransport()
        self._parser = parser or UdyamResponseParser()

    def verify(self, bidder_id: str, identifier: str, **kwargs: Any) -> Verification:
        query = UdyamQuery(
            bidder_id=bidder_id, udyam_registration_number=str(identifier)
        )
        try:
            envelope = self._transport.send_query(query)
        except (TransportError, NotImplementedError):
            return self._unavailable(query)
        return self._parser.parse(envelope, query=query, bidder_id=bidder_id)

    def _unavailable(self, query: UdyamQuery) -> Verification:
        return Verification(
            verification_id=Verification.allocate_id(
                source=self.SOURCE,
                identifier=query.udyam_registration_number,
                call_id=query.call_id,
            ),
            bidder_id=query.bidder_id,
            capability=Capability.UDYAM,
            source=self.SOURCE,
            queried_identifier=query.udyam_registration_number,
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
    "NormalizedUdyamData",
    "UdyamAdapter",
    "UdyamQuery",
    "UdyamResponseEnvelope",
    "UdyamResponseParser",
]
