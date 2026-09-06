"""Production-shaped GSTN verification adapter.

This module provides :class:`GSTNAdapter`, a :class:`VerificationProvider`
subclass that demonstrates the **adapter boundary** a real GSTN
integration would need, without performing any network I/O.

Architecture
------------

    ComplianceEngine / GSTRegistrationRule
        |
        v
    GSTNAdapter.verify(bidder_id, identifier, **kwargs)
        |
        +--> builds a typed :class:`GstQuery`
        |
        v
    VerificationTransport.send_query(query)        <-- network seam
        |
        v
    GstResponseEnvelope { status_code, raw_response, latency_ms, correlation_id }
        |
        v
    GstResponseParser.parse(envelope)              <-- parsing seam
        |
        v
    NormalizedGstData { registration_status, legal_name }
        |
        v
    Verification (data=NormalizedGstData.model_dump(), query=...,
                  raw_response=..., latency_ms=..., correlation_id=...)

Extension points (deliberately unimplemented)
--------------------------------------------

* Authentication - a real GSTN endpoint will require client
  credentials and request signing. A future adapter will inject an
  authenticated :class:`VerificationTransport` that adds the right
  headers.
* Network / HTTP - :class:`InProcessTransport` raises
  :class:`NotImplementedError` by default; a real transport is
  injected at construction time.
* Raw response storage - ``raw_response`` is preserved verbatim on
  the returned :class:`Verification` for downstream audit pipelines.
* Normalization - :class:`GstResponseParser` is a separate class so
  the mapping from raw payload to ``NormalizedGstData`` is unit
  testable without instantiating a transport.

This module contains **no** network, credentials, scraping, or
authentication code. It is a structural foundation only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final, Optional

from pydantic import BaseModel, ConfigDict, Field

from compliance_engine.models import Capability, Verification, VerificationStatus
from compliance_engine.verification.base import VerificationProvider
from compliance_engine.verification.gst_http_transport import (
    GstHttpTransport,
    GstTransportError,
    StaticGstTransport,
    http_response_to_envelope,
)
from compliance_engine.verification.transport import (
    GstQuery,
    GstResponseEnvelope,
    InProcessTransport,
    SourceResponseEnvelope,
    TransportError,
    VerificationTransport,
)


# ---------------------------------------------------------------------------
# Normalized data contract
# ---------------------------------------------------------------------------


class NormalizedGstData(BaseModel):
    """The minimum data the GST compliance rule consumes.

    These are the *only* fields a real GSTN adapter needs to expose
    through :attr:`Verification.data`. The parser is responsible for
    flattening whatever shape the real GSTN payload has into this
    pydantic model. Anything the rule does not read is left in
    :attr:`Verification.raw_response` and ignored.
    """

    model_config = ConfigDict(extra="forbid")

    registration_status: str = Field(
        ..., description='"ACTIVE" or "INACTIVE" as reported by GSTN.'
    )
    legal_name: str | None = Field(
        None, description="Legal name on record for the GSTIN, if available."
    )


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------


class GstResponseParser:
    """Map a :class:`GstResponseEnvelope` to a :class:`Verification`.

    The domain :class:`VerificationStatus` is derived from the source
    PAYLOAD, not from the transport ``status_code``. The transport
    status is preserved on the returned :class:`Verification` for
    audit only.

    Mapping rules
    -------------

    * Transport 5xx (or transport exception caught at the adapter
      boundary) → ``UNAVAILABLE``.
    * 4xx with a payload that names a missing identifier record
      (no useful ``registration_status``) → ``NOT_FOUND``.
    * 4xx with a payload that signals a malformed identifier
      (``registration_status`` absent or ``"INVALID"``) →
      ``INVALID``.
    * 2xx with a payload whose ``registration_status`` is
      ``"ACTIVE"`` → ``VERIFIED``; ``"INACTIVE"`` → ``INACTIVE``.
    * 2xx with a payload that does not match the expected shape →
      ``ERROR``.
    """

    def parse(
        self,
        envelope: GstResponseEnvelope,
        *,
        query: GstQuery,
        bidder_id: str,
    ) -> Verification:
        status, data = self._derive_domain_status(envelope, query)
        raw = envelope.raw_response
        transport_status = envelope.status_code

        # The transport status is metadata only. The domain
        # ``status`` above is derived from the source payload.
        # A non-dict ``raw_response`` (e.g. an HTML error page or a
        # stringified body) is treated as a malformed payload and
        # coerced to ``None`` so the audit trail does not carry an
        # unparseable blob in the ``raw_response`` field.
        if raw is not None and not isinstance(raw, dict):
            raw = None
            if status is VerificationStatus.VERIFIED:
                # A non-dict body cannot back a verified claim.
                status = VerificationStatus.ERROR
                data = {}

        # ``verification_id`` is pre-allocated by the engine / rule
        # layer when supplied on the query; otherwise we generate
        # the canonical ``source:identifier:call_id`` form.
        verification_id = (
            query.verification_id
            if query.verification_id
            else Verification.allocate_id(
                source=GSTNAdapter.SOURCE,
                identifier=query.gstin,
                call_id=query.call_id,
            )
        )

        # ``correlation_id`` prefers the envelope's value (set by the
        # transport); if the transport did not propagate one, the
        # query-level ``correlation_id`` is used as a fallback. The
        # two are never collapsed.
        correlation_id = (
            envelope.correlation_id
            if envelope.correlation_id is not None
            else query.correlation_id
        )

        return Verification(
            verification_id=verification_id,
            bidder_id=bidder_id,
            capability=Capability.GST,
            source=GSTNAdapter.SOURCE,
            queried_identifier=query.gstin,
            status=status,
            data=data,
            retrieved_at=datetime.now(UTC),
            query=query.model_dump(),
            raw_response=raw,
            latency_ms=envelope.latency_ms,
            correlation_id=correlation_id,
            transport_status_code=transport_status,
        )

    def _derive_domain_status(
        self,
        envelope: GstResponseEnvelope,
        query: GstQuery,
    ) -> tuple[VerificationStatus, dict[str, Any]]:
        code = envelope.status_code
        raw = envelope.raw_response

        # Transport-level outage: the source could not be reached.
        if 500 <= code < 600:
            return VerificationStatus.UNAVAILABLE, {}

        # Standard client-error codes (400, 404, 422, etc.).
        if 400 <= code < 500:
            if raw is None:
                # 4xx with no payload is unambiguous: the source
                # could not return a usable record for the given
                # identifier.
                return VerificationStatus.NOT_FOUND, {}
            # If the payload has a recognizable domain field,
            # trust it. Otherwise the source rejected the
            # identifier (e.g. malformed GSTIN).
            if "registration_status" in raw:
                status = self._status_from_payload(raw)
                data = self._safe_extract_data(raw, status)
                return status, data
            return VerificationStatus.INVALID, {}

        if 200 <= code < 300:
            if raw is None:
                return VerificationStatus.ERROR, {}
            # A 2xx response that lacks the expected domain field
            # is a *malformed* payload, not a domain "not found":
            # the source claims success but returned garbage.
            if "registration_status" not in raw:
                return VerificationStatus.ERROR, {}
            status = self._status_from_payload(raw)
            data = self._safe_extract_data(raw, status)
            return status, data

        # Anything else (1xx, 3xx, non-standard codes like 999):
        # treat as a transport-level error.
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
            return NormalizedGstData(
                registration_status=raw.get("registration_status", "UNKNOWN"),
                legal_name=raw.get("legal_name"),
            ).model_dump()
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class GSTNAdapter(VerificationProvider):
    """A production-shaped GSTN adapter.

    This adapter implements the existing
    :meth:`VerificationProvider.verify` contract so the
    :class:`ComplianceEngine` and :class:`GSTRegistrationRule` work
    unchanged. Internally it routes through a transport seam and a
    parser seam, so the network and parsing concerns can be replaced
    without touching the rule engine.

    Two execution paths are supported:

    * The **legacy** path uses the generic
      :class:`VerificationTransport` abstraction
      (``StaticTransport`` / ``InProcessTransport``) and a
      payload-dict :class:`GstResponseParser`. It is what existing
      tests and the Compliance Engine rely on, and remains the
      default when the adapter is constructed without an
      :class:`GstHttpTransport`.
    * The **real-provider** path is used when the adapter is
      constructed with an :class:`GstHttpTransport`. It goes
      through the HTTPS boundary (``gst_http_transport``) and
      derives the domain :class:`VerificationStatus` from the
      parsed HTTP response.

    Both paths produce the same :class:`Verification` shape, so
    the Compliance Engine and AI Verification do not need to know
    which one fired. ``verify_refs`` / ``verification_id``
    uniqueness is preserved on both paths.
    """

    SOURCE: Final[str] = "GSTN"

    def __init__(
        self,
        transport: VerificationTransport | None = None,
        parser: GstResponseParser | None = None,
        *,
        http_transport: GstHttpTransport | None = None,
    ) -> None:
        self._transport: VerificationTransport = transport or InProcessTransport()
        self._parser = parser or GstResponseParser()
        # The real-HTTP-transport path is opt-in. When ``None``, the
        # adapter uses the generic ``VerificationTransport`` path.
        # When supplied, the adapter prefers the HTTP transport
        # when both are configured.
        self._http_transport: Optional[GstHttpTransport] = http_transport

    def verify(self, bidder_id: str, identifier: str, **kwargs: Any) -> Verification:
        """Query the GSTN transport and return a :class:`Verification`.

        ``identifier`` is the GSTIN. ``kwargs`` are accepted for
        contract compatibility but currently ignored by the adapter
        itself; a real adapter would route them into the request
        envelope (e.g. headers, correlation id override).
        """

        query = GstQuery(
            bidder_id=bidder_id,
            gstin=str(identifier),
            verification_id=kwargs.get("verification_id"),
            correlation_id=kwargs.get("correlation_id"),
        )
        if self._http_transport is not None:
            return self._verify_with_http_transport(query, bidder_id)
        return self._verify_with_legacy_transport(query, bidder_id)

    def _verify_with_legacy_transport(
        self, query: GstQuery, bidder_id: str
    ) -> Verification:
        try:
            envelope = self._transport.send_query(query)
        except (TransportError, NotImplementedError):
            # Transport-level failure or no real transport wired in:
            # surface as UNAVAILABLE so the rule layer does not treat
            # it as a verified negative.
            return self._unavailable(query)
        return self._parser.parse(envelope, query=query, bidder_id=bidder_id)

    def _verify_with_http_transport(
        self, query: GstQuery, bidder_id: str
    ) -> Verification:
        assert self._http_transport is not None
        try:
            response = self._http_transport.send(query)
        except GstTransportError:
            return self._unavailable(query)
        envelope = http_response_to_envelope(response)
        return self._parser.parse(envelope, query=query, bidder_id=bidder_id)

    def _unavailable(self, query: GstQuery) -> Verification:
        verification_id = (
            query.verification_id
            if query.verification_id
            else Verification.allocate_id(
                source=self.SOURCE,
                identifier=query.gstin,
                call_id=query.call_id,
            )
        )
        return Verification(
            verification_id=verification_id,
            bidder_id=query.bidder_id,
            capability=Capability.GST,
            source=self.SOURCE,
            queried_identifier=query.gstin,
            status=VerificationStatus.UNAVAILABLE,
            data={},
            retrieved_at=datetime.now(UTC),
            query=query.model_dump(),
            raw_response=None,
            latency_ms=None,
            correlation_id=query.correlation_id,
            transport_status_code=None,
        )


__all__ = [
    "GSTNAdapter",
    "GstResponseParser",
    "NormalizedGstData",
]
