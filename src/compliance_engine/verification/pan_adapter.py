"""Production-shaped PAN / Income Tax verification adapter.

This module provides :class:`PanAdapter`, a
:class:`VerificationProvider` subclass that implements the boundary
a real Income Tax PAN integration needs, without performing any
network I/O by default. It mirrors the GSTN / Udyam adapter
structure so the engine can be source-agnostic.

Two execution paths are supported:

* The **legacy** path uses the generic :class:`VerificationTransport`
  abstraction (``StaticTransport`` / ``InProcessTransport``) and a
  payload-dict :class:`PanResponseParser`. It is what existing tests
  and the Compliance Engine rely on, and remains the default when the
  adapter is constructed without a :class:`PanConfig`.
* The **real-provider** path is used when the adapter is constructed
  with a :class:`PanConfig` and an :class:`PanHttpTransport`. It goes
  through the SOAP/XML boundary (``pan_soap``) and derives the domain
  :class:`VerificationStatus` from the parsed SOAP response.

Both paths produce the same :class:`Verification` shape, so the
Compliance Engine and AI Verification do not need to know which one
fired. ``verify_refs`` / ``verification_id`` uniqueness is preserved
on both paths.

This module contains **no** hardcoded credentials, no scraping, and
no authentication bypass code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from compliance_engine.models import Capability, Verification, VerificationStatus
from compliance_engine.verification.base import VerificationProvider
from compliance_engine.verification.pan_config import PanConfig
from compliance_engine.verification.pan_http_transport import (
    PanHttpResponse,
    PanHttpTransport,
    PanTransportError,
)
from compliance_engine.verification.pan_soap import (
    PanSoapParseError,
    PanSoapRequestBuilder,
    PanSoapResponseParser,
)
from compliance_engine.verification.transport import (
    InProcessTransport,
    SourceResponseEnvelope,
    TransportError,
    VerificationTransport,
)


# ---------------------------------------------------------------------------
# Query / normalized data
# ---------------------------------------------------------------------------


class PanQuery(BaseModel):
    """Typed query for a future PAN / Income Tax request.

    Only ``bidder_id``, ``pan`` and ``call_id`` are required. The
    other fields mirror the official PAN Verification Web Service
    request shape: name components, DOB, and gender are optional
    and the rule layer today does not pass them. They are present so
    the SOAP boundary can build a faithful envelope when a rule does
    supply identity evidence.
    """

    model_config = ConfigDict(extra="forbid")

    bidder_id: str = Field(
        ..., description="Bidder whose PAN is being verified."
    )
    pan: str = Field(
        ..., description="The PAN (10-character alphanumeric) being queried."
    )
    call_id: str = Field(
        default_factory=lambda: uuid4().hex,
        description=(
            "Per-call UUID4 hex. Used to produce a unique "
            "Verification.verification_id even when the same source "
            "+ identifier is queried more than once."
        ),
    )
    full_name: str | None = Field(
        default=None,
        description=(
            "Full name as held by the bidder, if available. Sent as "
            "``FullName`` in the SOAP envelope."
        ),
    )
    first_name: str | None = Field(
        default=None,
        description="First name component, if available.",
    )
    middle_name: str | None = Field(
        default=None,
        description="Middle name component, if available.",
    )
    last_name: str | None = Field(
        default=None,
        description="Last name component, if available.",
    )
    date_of_birth: str | None = Field(
        default=None,
        description=(
            "Date of birth in ``dd/mm/yyyy`` form, the format the "
            "official service expects."
        ),
    )
    gender: str | None = Field(
        default=None,
        description=(
            "Gender code (``M`` / ``F`` / ``T``). Optional in the "
            "official service."
        ),
    )


# Source-specific response envelope alias.
PanResponseEnvelope = SourceResponseEnvelope


class NormalizedPanData(BaseModel):
    """The minimum data the PAN compliance rule consumes."""

    model_config = ConfigDict(extra="forbid")

    pan_status: str = Field(
        ..., description='"ACTIVE" or "INACTIVE" as reported by the source.'
    )
    name_on_pan: str | None = Field(
        None, description="Name on record for the PAN."
    )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class PanResponseParser:
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
        query: PanQuery,
        bidder_id: str,
    ) -> Verification:
        status, data = self._derive_domain_status(envelope, query)
        raw = envelope.raw_response
        transport_status = envelope.status_code

        return Verification(
            verification_id=Verification.allocate_id(
                source=PanAdapter.SOURCE,
                identifier=query.pan,
                call_id=query.call_id,
            ),
            bidder_id=bidder_id,
            capability=Capability.PAN_INCOME_TAX,
            source=PanAdapter.SOURCE,
            queried_identifier=query.pan,
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
        query: PanQuery,
    ) -> tuple[VerificationStatus, dict[str, Any]]:
        code = envelope.status_code
        raw = envelope.raw_response

        if 500 <= code < 600:
            return VerificationStatus.UNAVAILABLE, {}

        if 400 <= code < 500:
            if raw is None:
                return VerificationStatus.NOT_FOUND, {}
            if "pan_status" in raw:
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
        value = raw.get("pan_status")
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
            return NormalizedPanData(
                pan_status=raw.get("pan_status", "UNKNOWN"),
                name_on_pan=raw.get("name_on_pan"),
            ).model_dump()
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class PanAdapter(VerificationProvider):
    """A production-shaped PAN / Income Tax adapter.

    Implements the existing :meth:`VerificationProvider.verify`
    contract so :class:`ComplianceEngine` and
    :class:`PANValidationRule` work unchanged.

    Construction
    ------------

    * ``transport`` + ``parser`` -- the legacy, payload-dict path.
    * ``config`` + ``http_transport`` -- the SOAP/XML, real-provider
      path. The :class:`PanConfig` is used to build the SOAP envelope;
      the :class:`PanHttpTransport` ships it.
    * With neither -- defaults to the in-process transport (legacy).

    The two paths are mutually exclusive: if ``config`` is supplied
    without a ``transport`` and without an ``http_transport`` the
    adapter raises at construction time so misconfigurations are
    caught immediately.
    """

    SOURCE: Final[str] = "PAN"

    def __init__(
        self,
        transport: VerificationTransport | None = None,
        parser: PanResponseParser | None = None,
        *,
        config: PanConfig | None = None,
        http_transport: PanHttpTransport | None = None,
        soap_request_builder: PanSoapRequestBuilder | None = None,
        soap_response_parser: PanSoapResponseParser | None = None,
    ) -> None:
        if config is not None or http_transport is not None:
            if config is None:
                raise ValueError(
                    "PanAdapter real-provider path requires a PanConfig."
                )
            if http_transport is None:
                raise ValueError(
                    "PanAdapter real-provider path requires a PanHttpTransport."
                )
            self._config: PanConfig | None = config
            self._http_transport: PanHttpTransport = http_transport
            self._soap_builder: PanSoapRequestBuilder = (
                soap_request_builder or PanSoapRequestBuilder(config)
            )
            self._soap_parser: PanSoapResponseParser = (
                soap_response_parser or PanSoapResponseParser()
            )
            self._transport = None
            self._parser = None
        else:
            self._config = None
            self._http_transport = None
            self._soap_builder = None
            self._soap_parser = None
            self._transport: VerificationTransport = transport or InProcessTransport()
            self._parser = parser or PanResponseParser()

    def verify(self, bidder_id: str, identifier: str, **kwargs: Any) -> Verification:
        query = self._build_query(bidder_id, identifier, kwargs)
        if self._config is not None and self._http_transport is not None:
            return self._verify_real(query, bidder_id)
        assert self._transport is not None
        assert self._parser is not None
        try:
            envelope = self._transport.send_query(query)
        except (TransportError, NotImplementedError):
            return self._unavailable(query)
        return self._parser.parse(envelope, query=query, bidder_id=bidder_id)

    def _build_query(
        self, bidder_id: str, identifier: str, kwargs: dict[str, Any]
    ) -> PanQuery:
        # Pull the documented identity-evidence fields out of the
        # ``verify`` kwargs without changing the existing
        # ``VerificationProvider.verify`` signature.
        query_payload: dict[str, Any] = {
            "bidder_id": bidder_id,
            "pan": str(identifier),
        }
        for kw_name, field_name in (
            ("full_name", "full_name"),
            ("first_name", "first_name"),
            ("middle_name", "middle_name"),
            ("last_name", "last_name"),
            ("date_of_birth", "date_of_birth"),
            ("dob", "date_of_birth"),
            ("gender", "gender"),
        ):
            if kw_name in kwargs and kwargs[kw_name] is not None:
                query_payload[field_name] = kwargs[kw_name]
        return PanQuery(**query_payload)

    def _verify_real(
        self, query: PanQuery, bidder_id: str
    ) -> Verification:
        assert self._soap_builder is not None
        assert self._soap_parser is not None
        assert self._http_transport is not None
        request = self._soap_builder.build(query)
        try:
            response: PanHttpResponse = self._http_transport.send(request)
        except PanTransportError:
            return self._unavailable(query)

        if not response.body_xml:
            return self._malformed(query, response)

        try:
            return self._soap_parser.parse(
                response.body_xml,
                query=query,
                bidder_id=bidder_id,
                transport_status_code=response.status_code,
                latency_ms=response.latency_ms,
                correlation_id=response.correlation_id or request.request_id,
            )
        except PanSoapParseError:
            return self._malformed(query, response)

    def _malformed(
        self, query: PanQuery, response: PanHttpResponse | None = None
    ) -> Verification:
        transport_status = response.status_code if response is not None else None
        latency = response.latency_ms if response is not None else None
        correlation = response.correlation_id if response is not None else None
        return Verification(
            verification_id=Verification.allocate_id(
                source=self.SOURCE,
                identifier=query.pan,
                call_id=query.call_id,
            ),
            bidder_id=query.bidder_id,
            capability=Capability.PAN_INCOME_TAX,
            source=self.SOURCE,
            queried_identifier=query.pan,
            status=VerificationStatus.ERROR,
            data={},
            retrieved_at=datetime.now(UTC),
            query=query.model_dump(),
            raw_response=(
                {"soap_xml": response.body_xml} if response is not None else None
            ),
            latency_ms=latency,
            correlation_id=correlation,
            transport_status_code=transport_status,
        )

    def _unavailable(self, query: PanQuery) -> Verification:
        return Verification(
            verification_id=Verification.allocate_id(
                source=self.SOURCE,
                identifier=query.pan,
                call_id=query.call_id,
            ),
            bidder_id=query.bidder_id,
            capability=Capability.PAN_INCOME_TAX,
            source=self.SOURCE,
            queried_identifier=query.pan,
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
    "NormalizedPanData",
    "PanAdapter",
    "PanQuery",
    "PanResponseEnvelope",
    "PanResponseParser",
]
