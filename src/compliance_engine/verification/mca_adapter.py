"""Production-shaped MCA / company-registration verification adapter.

This module provides :class:`McaAdapter`, a
:class:`VerificationProvider` subclass that demonstrates the adapter
boundary a real MCA (Ministry of Corporate Affairs) integration would
need, without performing any network I/O.

Capability / source naming
--------------------------

The codebase already references ``MCA21`` in the cross-document
identity-verification alias table (``anomalies/identity.py``) and in the
canonical :class:`compliance_engine.models.Capability` enum
(``Capability.MCA21``). This adapter uses ``source="MCA21"`` and
``capability="MCA21"`` (the canonical enum member's value) and is consumed
by :class:`compliance_engine.rules.mca.McaRegistrationRule`
(``MCA21_REGISTRATION_001``).

This module contains **no** network, credentials, scraping, or
authentication code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from compliance_engine.models import Verification, VerificationStatus
from compliance_engine.verification.base import VerificationProvider
from compliance_engine.verification.transport import (
    InProcessTransport,
    SourceResponseEnvelope,
    TransportError,
    VerificationTransport,
)

# Free-form capability / source identifier. Kept as a constant so all
# references within this module are consistent and so a future
# promotion to a canonical Capability enum value is a one-line change.
_MCA_SOURCE: Final[str] = "MCA21"
_MCA_CAPABILITY: Final[str] = "MCA21"


# ---------------------------------------------------------------------------
# Query / normalized data
# ---------------------------------------------------------------------------


class McaQuery(BaseModel):
    """Typed query for a future MCA request."""

    model_config = ConfigDict(extra="forbid")

    bidder_id: str = Field(
        ..., description="Bidder whose MCA record is being verified."
    )
    cin: str = Field(
        ...,
        description=(
            "The Corporate Identification Number (CIN) being queried."
        ),
    )
    call_id: str = Field(
        default_factory=lambda: uuid4().hex,
        description=(
            "Per-call UUID4 hex. Used to produce a unique "
            "Verification.verification_id even when the same source "
            "+ identifier is queried more than once."
        ),
    )


# Source-specific response envelope alias.
McaResponseEnvelope = SourceResponseEnvelope


class NormalizedMcaData(BaseModel):
    """The minimum data a future MCA-related rule would consume.

    Today, no compliance rule reads MCA data. The minimal field set
    here is informed by the existing cross-document identity alias
    ``{"MCA21": {"company_name"}}``: an MCA adapter that supplies
    ``company_name`` lets the identity anomaly detector correlate a
    company's MCA record against its GST/PAN/Udyam records.
    """

    model_config = ConfigDict(extra="forbid")

    company_status: str = Field(
        ...,
        description='"ACTIVE" or "INACTIVE" as reported by MCA.',
    )
    company_name: str | None = Field(
        None, description="Company name on record."
    )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class McaResponseParser:
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
        query: McaQuery,
        bidder_id: str,
    ) -> Verification:
        status, data = self._derive_domain_status(envelope, query)
        raw = envelope.raw_response
        transport_status = envelope.status_code

        return Verification(
            verification_id=Verification.allocate_id(
                source=_MCA_SOURCE,
                identifier=query.cin,
                call_id=query.call_id,
            ),
            bidder_id=bidder_id,
            capability=_MCA_CAPABILITY,
            source=_MCA_SOURCE,
            queried_identifier=query.cin,
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
        query: McaQuery,
    ) -> tuple[VerificationStatus, dict[str, Any]]:
        code = envelope.status_code
        raw = envelope.raw_response

        if 500 <= code < 600:
            return VerificationStatus.UNAVAILABLE, {}

        if 400 <= code < 500:
            if raw is None:
                return VerificationStatus.NOT_FOUND, {}
            if "company_status" in raw:
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
        value = raw.get("company_status")
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
            return NormalizedMcaData(
                company_status=raw.get("company_status", "UNKNOWN"),
                company_name=raw.get("company_name"),
            ).model_dump()
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class McaAdapter(VerificationProvider):
    """A production-shaped MCA adapter.

    Implements the existing :meth:`VerificationProvider.verify`
    contract. The engine does not need an MCA rule to consume this
    adapter; if no rule requires the MCA capability, the adapter is
    simply unused by the engine.
    """

    SOURCE: Final[str] = _MCA_SOURCE

    def __init__(
        self,
        transport: VerificationTransport | None = None,
        parser: McaResponseParser | None = None,
    ) -> None:
        self._transport: VerificationTransport = transport or InProcessTransport()
        self._parser = parser or McaResponseParser()

    def verify(self, bidder_id: str, identifier: str, **kwargs: Any) -> Verification:
        query = McaQuery(bidder_id=bidder_id, cin=str(identifier))
        try:
            envelope = self._transport.send_query(query)
        except (TransportError, NotImplementedError):
            return self._unavailable(query)
        return self._parser.parse(envelope, query=query, bidder_id=bidder_id)

    def _unavailable(self, query: McaQuery) -> Verification:
        return Verification(
            verification_id=Verification.allocate_id(
                source=self.SOURCE,
                identifier=query.cin,
                call_id=query.call_id,
            ),
            bidder_id=query.bidder_id,
            capability=_MCA_CAPABILITY,
            source=self.SOURCE,
            queried_identifier=query.cin,
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
    "McaAdapter",
    "McaQuery",
    "McaResponseEnvelope",
    "McaResponseParser",
    "NormalizedMcaData",
]
