"""Production-shaped GSTN return-filing verification adapter.

This module provides :class:`GSTNReturnsAdapter`, a
:class:`VerificationProvider` subclass that demonstrates the
adapter boundary a real GSTN return-filing integration would
need, without performing any network I/O.

The return-filing capability is intentionally **distinct** from
the GST registration capability:

* ``Capability.GST`` covers registration status (active / inactive).
* ``Capability.GST_RETURN_FILING`` covers the source-derived record
  of periodic GST returns (which returns were filed, for which
  period, on which date, with which frequency).

The two share a source family (GSTN) but they have separate
``source`` strings, separate providers, separate rules, separate
audit artefacts, and separate normalized-data contracts. A
tender that requires both can wire both providers; a tender
that requires only one is unaffected by the other.

This module contains **no** network, credentials, scraping, or
authentication code. It is a structural foundation only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final, List, Optional
from uuid import uuid4

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
    InProcessTransport,
    SourceResponseEnvelope,
    TransportError,
    VerificationTransport,
)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


#: Sentinel return-type value used by a :class:`GstReturnQuery` to
#: indicate that the caller wants the complete filing table for the
#: GSTIN, regardless of which return form (GSTR1, GSTR3B, ...) is
#: being inspected.
GST_RETURN_TYPE_ALL: Final[str] = "ALL"

#: Sentinel financial-year value used by a :class:`GstReturnQuery` to
#: indicate that the caller wants filings across every financial
#: year on record.
GST_FINANCIAL_YEAR_ALL: Final[str] = "ALL"


class GstReturnQuery(BaseModel):
    """Typed query for a future GSTN return-filing lookup.

    The query is **GST-return-specific** and intentionally does not
    grow into a universal government query. The two filter fields
    (``financial_year`` and ``return_type``) are both optional; when
    omitted (or set to the ``ALL`` sentinels) the source is expected
    to return the complete filing table for the GSTIN.

    The same three per-call identity concepts as :class:`GstQuery`
    are modelled here and are deliberately separate fields:

    * ``call_id`` — per-attempt UUID4, generated here.
    * ``verification_id`` — pre-allocated by the engine / rule
      layer when the consumer needs the audit ID known up-front.
    * ``correlation_id`` — end-to-end trace ID shared with other
      systems.
    """

    model_config = ConfigDict(extra="forbid")

    bidder_id: str = Field(
        ..., description="Bidder whose GST return filings are being verified."
    )
    gstin: str = Field(
        ..., description="The GSTIN whose return filings are being queried."
    )
    financial_year: str = Field(
        default=GST_FINANCIAL_YEAR_ALL,
        description=(
            "Financial year filter (e.g. ``\"2023-2024\"``). When "
            "omitted or set to the ``ALL`` sentinel the source "
            "returns the complete filing table."
        ),
    )
    return_type: str = Field(
        default=GST_RETURN_TYPE_ALL,
        description=(
            "Return form filter (e.g. ``\"GSTR1\"``, ``\"GSTR3B\"``). "
            "When omitted or set to the ``ALL`` sentinel the source "
            "returns filings for every form."
        ),
    )
    call_id: str = Field(
        default_factory=lambda: uuid4().hex,
        description=(
            "Per-call UUID4 hex. Used to produce a unique "
            "Verification.verification_id even when the same source "
            "+ identifier is queried more than once. Distinct from "
            "``verification_id`` and ``correlation_id``."
        ),
    )
    verification_id: str | None = Field(
        default=None,
        description=(
            "Pre-allocated verification ID. When supplied, the "
            "adapter uses it as the returned "
            "``Verification.verification_id``; otherwise one is "
            "generated from ``source:identifier:call_id``."
        ),
    )
    correlation_id: str | None = Field(
        default=None,
        description=(
            "End-to-end correlation id, propagated onto the returned "
            "``Verification.correlation_id`` and used by the "
            "transport for tracing."
        ),
    )

    def lookup_key(self) -> str:
        """Return a deterministic lookup key for test transports.

        The key combines the GSTIN, financial-year, and return-type
        filters so a deterministic test transport can register a
        canned response for a specific combination. The default
        ``StaticTransport`` is keyed by ``query.gstin`` alone; tests
        that want to exercise per-period or per-form differentiation
        supply a custom ``query_key`` callable that defers to this
        method.
        """

        return f"{self.gstin}|{self.financial_year}|{self.return_type}"


# ---------------------------------------------------------------------------
# Normalized data
# ---------------------------------------------------------------------------


#: Domain outcome string used inside ``NormalizedGstReturnFilingData``
#: when the source reports the return was filed. The exact string
#: mirrors the registration-status convention used by the GST
#: registration parser.
FILING_STATUS_FILED: Final[str] = "FILED"

#: Domain outcome string used when the source reports the return
#: was not filed for the requested period / form.
FILING_STATUS_NOT_FILED: Final[str] = "NOT_FILED"


class NormalizedGstReturnFilingData(BaseModel):
    """Narrow normalized data for a GST return-filing lookup.

    The fields here are the *only* data a return-filing
    compliance rule consumes. Anything the rule does not read
    stays on :attr:`Verification.raw_response` and is not
    interpreted. The shape is intentionally narrow: no universal
    GST schema is built here.

    Domain semantics
    ----------------

    * ``filing_status`` is the business outcome (``"FILED"`` /
      ``"NOT_FILED"``) as reported by the source. It is
      deliberately distinct from
      :class:`VerificationStatus`, which encodes the
      *transport-layer* outcome (verified / not_found / invalid /
      unavailable / error). The two coexist on the returned
      :class:`Verification`.
    * ``financial_year`` and ``return_type`` echo the query
      filters so the rule can correlate a multi-row response back
      to a specific period.
    * ``returns`` is a list of per-row filing records. For a
      single-period, single-form query the list has one entry.
      For an unfiltered query the list has one entry per
      ``(financial_year, return_type, filing_period)`` triple.
    """

    model_config = ConfigDict(extra="forbid")

    financial_year: str = Field(
        ..., description='Financial year, e.g. "2023-2024".'
    )
    return_type: str = Field(
        ...,
        description=(
            'Return form, e.g. "GSTR1", "GSTR3B", or the '
            "``ALL`` sentinel when the query was unfiltered."
        ),
    )
    filing_period: str | None = Field(
        None,
        description=(
            "Filing period label (e.g. ``\"April 2024\"`` or "
            "``\"Q1\"``). ``None`` when the source does not report "
            "a sub-year period."
        ),
    )
    filing_status: str = Field(
        ...,
        description=(
            "Business outcome: ``\"FILED\"`` or ``\"NOT_FILED\"``. "
            "Distinct from ``Verification.status``, which encodes "
            "the transport-layer outcome."
        ),
    )
    filing_date: str | None = Field(
        None,
        description=(
            "Date of filing as reported by the source. Preserved as "
            "a string to avoid timezone ambiguity; downstream "
            "consumers that need a date should parse this."
        ),
    )
    filing_frequency: str | None = Field(
        None,
        description=(
            "Applicable filing frequency as reported by the source "
            "(e.g. ``MONTHLY``, ``QUARTERLY``, ``ANNUAL``)."
        ),
    )
    returns: List[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Full per-row filing table for the query. For a "
            "single-period / single-form query the list has one "
            "entry; for an unfiltered query it has one entry per "
            "``(financial_year, return_type, filing_period)`` triple."
        ),
    )


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------


class GstReturnResponseParser:
    """Map a :class:`SourceResponseEnvelope` to a :class:`Verification`.

    The domain :class:`VerificationStatus` is derived from the
    transport status, which is distinct from the *business* filing
    outcome (``filing_status`` on the normalized data).

    Mapping rules
    -------------

    * 5xx (or transport exception) → ``UNAVAILABLE``.
    * 4xx with no usable payload → ``NOT_FOUND`` for the GSTIN.
    * 4xx with a payload that names the GSTIN but the source
      explicitly signals the identifier is malformed → ``INVALID``.
    * 2xx with a payload that lacks a ``filing_status`` field →
      ``ERROR`` (malformed payload).
    * 2xx with a usable payload → ``VERIFIED``, and the
      ``data`` carries the normalized filing record(s).
    """

    def parse(
        self,
        envelope: SourceResponseEnvelope,
        *,
        query: GstReturnQuery,
        bidder_id: str,
    ) -> Verification:
        status, data = self._derive_domain_status(envelope)
        raw = envelope.raw_response
        transport_status = envelope.status_code

        if raw is not None and not isinstance(raw, dict):
            raw = None
            if status is VerificationStatus.VERIFIED:
                status = VerificationStatus.ERROR
                data = {}

        verification_id = (
            query.verification_id
            if query.verification_id
            else Verification.allocate_id(
                source=GSTNReturnsAdapter.SOURCE,
                identifier=query.gstin,
                call_id=query.call_id,
            )
        )

        correlation_id = (
            envelope.correlation_id
            if envelope.correlation_id is not None
            else query.correlation_id
        )

        return Verification(
            verification_id=verification_id,
            bidder_id=bidder_id,
            capability=Capability.GST_RETURN_FILING,
            source=GSTNReturnsAdapter.SOURCE,
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

    @staticmethod
    def _derive_domain_status(
        envelope: SourceResponseEnvelope,
    ) -> tuple[VerificationStatus, dict[str, Any]]:
        code = envelope.status_code
        raw = envelope.raw_response

        if 500 <= code < 600:
            return VerificationStatus.UNAVAILABLE, {}

        if 400 <= code < 500:
            if raw is None:
                return VerificationStatus.NOT_FOUND, {}
            # If the payload explicitly signals a malformed
            # identifier, surface it as INVALID; otherwise the
            # source has a record for the identifier but the
            # caller asked for something the source cannot
            # resolve, which is the standard NOT_FOUND shape.
            if raw.get("identifier_status") == "INVALID":
                return VerificationStatus.INVALID, {}
            if "filing_status" in raw:
                status, data = GstReturnResponseParser._status_from_payload(raw)
                return status, data
            return VerificationStatus.NOT_FOUND, {}

        if 200 <= code < 300:
            if raw is None:
                return VerificationStatus.ERROR, {}
            if "filing_status" not in raw:
                return VerificationStatus.ERROR, {}
            status, data = GstReturnResponseParser._status_from_payload(raw)
            return status, data

        # Anything else (1xx, 3xx, non-standard codes like 999):
        # treat as a transport-level error.
        return VerificationStatus.ERROR, {}

    @staticmethod
    def _status_from_payload(
        raw: dict[str, Any],
    ) -> tuple[VerificationStatus, dict[str, Any]]:
        value = raw.get("filing_status")
        if value == FILING_STATUS_FILED:
            return VerificationStatus.VERIFIED, GstReturnResponseParser._safe_extract_data(raw)
        if value == FILING_STATUS_NOT_FILED:
            # A confirmed "not filed" answer is a verified negative
            # — the source successfully reported the result. It is
            # NOT mapped to INVALID; that mapping is reserved for
            # identifiers the source refuses to recognize.
            return VerificationStatus.VERIFIED, GstReturnResponseParser._safe_extract_data(raw)
        return VerificationStatus.ERROR, {}

    @staticmethod
    def _safe_extract_data(raw: dict[str, Any]) -> dict[str, Any]:
        try:
            # The normalized model enforces ``extra="forbid"``; any
            # unrecognised keys are dropped. The full list of
            # filing rows is preserved in ``returns`` for callers
            # that want the unfiltered view.
            return NormalizedGstReturnFilingData(
                financial_year=raw.get(
                    "financial_year", GST_FINANCIAL_YEAR_ALL
                ),
                return_type=raw.get("return_type", GST_RETURN_TYPE_ALL),
                filing_period=raw.get("filing_period"),
                filing_status=raw.get(
                    "filing_status", FILING_STATUS_NOT_FILED
                ),
                filing_date=raw.get("filing_date"),
                filing_frequency=raw.get("filing_frequency"),
                returns=list(raw.get("returns", [])),
            ).model_dump()
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class GSTNReturnsAdapter(VerificationProvider):
    """A production-shaped GSTN return-filing adapter.

    Implements the existing
    :meth:`VerificationProvider.verify` contract so the
    :class:`ComplianceEngine` and the new return-filing rule
    work unchanged. Routes through a transport seam and a parser
    seam so the network and parsing concerns can be replaced
    without touching the rule engine.

    Two execution paths are supported:

    * The **legacy** path uses the generic
      :class:`VerificationTransport` abstraction
      (``StaticTransport`` / ``InProcessTransport``) and a
      payload-dict :class:`GstReturnResponseParser`.
    * The **real-provider** path is used when the adapter is
      constructed with an :class:`GstHttpTransport`. It goes
      through the HTTPS boundary (``gst_http_transport``).

    Both paths produce the same :class:`Verification` shape, so
    the Compliance Engine and AI Verification do not need to know
    which one fired.
    """

    SOURCE: Final[str] = "GSTN_RETURNS"

    def __init__(
        self,
        transport: VerificationTransport | None = None,
        parser: GstReturnResponseParser | None = None,
        *,
        http_transport: GstHttpTransport | None = None,
    ) -> None:
        self._transport: VerificationTransport = (
            transport or InProcessTransport()
        )
        self._parser = parser or GstReturnResponseParser()
        # The real-HTTP-transport path is opt-in. When ``None``,
        # the adapter uses the generic ``VerificationTransport``
        # path. When supplied, the adapter prefers the HTTP
        # transport when both are configured.
        self._http_transport: Optional[GstHttpTransport] = http_transport

    def verify(
        self, bidder_id: str, identifier: str, **kwargs: Any
    ) -> Verification:
        """Query the GSTN return-filing transport and return a
        :class:`Verification`.

        ``identifier`` is the GSTIN. ``kwargs`` may carry the
        following optional filters / overrides:

        * ``financial_year`` — financial-year filter, default
          ``"ALL"`` (whole history).
        * ``return_type`` — return-form filter, default
          ``"ALL"`` (every form).
        * ``verification_id`` — pre-allocated verification ID.
        * ``correlation_id`` — end-to-end trace ID.

        Unrecognised kwargs are ignored for forward-compatibility.
        """

        query = GstReturnQuery(
            bidder_id=bidder_id,
            gstin=str(identifier),
            financial_year=kwargs.get(
                "financial_year", GST_FINANCIAL_YEAR_ALL
            ),
            return_type=kwargs.get("return_type", GST_RETURN_TYPE_ALL),
            verification_id=kwargs.get("verification_id"),
            correlation_id=kwargs.get("correlation_id"),
        )
        if self._http_transport is not None:
            return self._verify_with_http_transport(query, bidder_id)
        return self._verify_with_legacy_transport(query, bidder_id)

    def _verify_with_legacy_transport(
        self, query: GstReturnQuery, bidder_id: str
    ) -> Verification:
        try:
            envelope = self._transport.send_query(query)
        except (TransportError, NotImplementedError):
            return self._unavailable(query)
        return self._parser.parse(envelope, query=query, bidder_id=bidder_id)

    def _verify_with_http_transport(
        self, query: GstReturnQuery, bidder_id: str
    ) -> Verification:
        assert self._http_transport is not None
        try:
            response = self._http_transport.send(query)
        except GstTransportError:
            return self._unavailable(query)
        envelope = http_response_to_envelope(response)
        return self._parser.parse(envelope, query=query, bidder_id=bidder_id)

    def _unavailable(self, query: GstReturnQuery) -> Verification:
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
            capability=Capability.GST_RETURN_FILING,
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
    "FILING_STATUS_FILED",
    "FILING_STATUS_NOT_FILED",
    "GSTNReturnsAdapter",
    "GST_FINANCIAL_YEAR_ALL",
    "GST_RETURN_TYPE_ALL",
    "GstReturnQuery",
    "GstReturnResponseParser",
    "NormalizedGstReturnFilingData",
]
