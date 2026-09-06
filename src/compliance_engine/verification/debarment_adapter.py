"""Production-shaped procurement-eligibility / debarment adapter.

This module provides :class:`DebarmentAdapter`, a
:class:`VerificationProvider` subclass that demonstrates the
adapter boundary a real procurement-blacklist / debarment
integration would need, without performing any network I/O.

Capability / source naming
--------------------------

The capability / source identifier is the free-form string
``PROCUREMENT_ELIGIBILITY`` / ``DEBARMENT_REGISTRY``. A future
milestone that introduces a dedicated ``Capability`` enum entry
can promote ``PROCUREMENT_ELIGIBILITY`` to a canonical
:class:`Capability` value.

Architecture
------------

    ComplianceEngine / DebarmentEligibilityRule
        |
        v
    DebarmentAdapter.verify(bidder_id, identifier, **kwargs)
        |
        +--> builds a typed :class:`DebarmentQuery`
        |
        v
    VerificationTransport.send_query(query)         <-- network seam
        |
        v
    SourceResponseEnvelope { status_code, raw_response, latency_ms, correlation_id }
        |
        v
    DebarmentResponseParser.parse(envelope)        <-- parsing seam
        |
        v
    NormalizedDebarmentData { restriction_status, restriction_type, ... }
        |
        v
    Verification (data=NormalizedDebarmentData.model_dump(), query=...,
                  raw_response=..., latency_ms=..., correlation_id=...)

Transport seam
--------------

The HTTP-shape transport (``DebarmentHttpTransport``) is a
production-shaped protocol that enforces:

* HTTPS-only ``url``,
* an explicit ``timeout_seconds``,
* no hardcoded credentials,
* no hardcoded fake endpoint.

The default behaviour is ``InProcessTransport`` which raises
``NotImplementedError`` so the adapter cannot accidentally execute
against the network in this milestone. Tests inject
``StaticDebarmentTransport`` to provide canned responses.

This module contains NO network, credentials, scraping, or
authentication code. It is a structural foundation only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final, Protocol as TypingProtocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from compliance_engine.models import Verification, VerificationStatus
from compliance_engine.verification.base import VerificationProvider
from compliance_engine.verification.debarment_models import (
    DEBARMENT_CAPABILITY,
    DEBARMENT_SOURCE,
    DebarmentQuery,
    DebarmentRestrictionStatus,
    DebarmentRestrictionType,
    MatchMethod,
    NormalizedDebarmentData,
    SubjectType,
    normalize_identifier,
)
from compliance_engine.verification.transport import (
    InProcessTransport,
    SourceResponseEnvelope,
    TransportError,
    VerificationTransport,
)


# ---------------------------------------------------------------------------
# Source-specific response envelope alias
# ---------------------------------------------------------------------------


#: Source-specific envelope. The transport seam is generic; the
#: source-specific shape is in the parser.
DebarmentResponseEnvelope = SourceResponseEnvelope


# ---------------------------------------------------------------------------
# HTTP transport protocol (real-shape only)
# ---------------------------------------------------------------------------


class DebarmentHttpTransportError(RuntimeError):
    """Raised when the debarment HTTP transport cannot complete it."""
    pass


class DebarmentHttpRequest(BaseModel):
    """Minimal HTTP request envelope for the debarment source.

    The request carries only the fields the future real source will
    need; nothing more. No credentials are included here -- the
    transport is expected to attach them out-of-band from
    :class:`DebarmentConfig`.
    """

    model_config = ConfigDict(extra="forbid")

    method: str = Field(default="POST", description="HTTP method.")
    url: str = Field(
        ...,
        description=(
            "HTTPS URL the transport will call. Validated by the "
            "client to be HTTPS; the transport refuses plain HTTP."
        ),
    )
    body: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON-serialisable request body.",
    )
    timeout_seconds: float = Field(
        default=10.0,
        ge=0.1,
        description="Total request timeout, in seconds.",
    )
    request_id: str = Field(
        default_factory=lambda: uuid4().hex,
        description=(
            "Per-call UUID4 hex used inside the request body and "
            "echoed back on the response for de-duplication."
        ),
    )


class DebarmentHttpResponse(BaseModel):
    """Minimal HTTP response envelope for the debarment source."""

    model_config = ConfigDict(extra="forbid")

    status_code: int = Field(
        ..., description="HTTP-style transport status code."
    )
    body_json: dict[str, Any] | None = Field(
        default=None,
        description="Decoded JSON body, or None when empty / malformed.",
    )
    latency_ms: int | None = Field(
        default=None,
        description="Round-trip latency, in milliseconds.",
    )
    correlation_id: str | None = Field(
        default=None,
        description="End-to-end correlation id, if available.",
    )


@runtime_checkable
class DebarmentHttpTransport(TypingProtocol):
    """Pluggable HTTP transport for the debarment source.

    The transport is the only place where future HTTPS, credential
    injection, and signing concerns live. The default
    :class:`DebarmentDefaultHttpTransport` rejects every request
    with :class:`DebarmentHttpTransportError` so a real adapter
    cannot accidentally execute against the network in this
    milestone. Tests inject :class:`StaticDebarmentHttpTransport`.
    """

    def send(self, request: DebarmentHttpRequest) -> DebarmentHttpResponse:
        ...


class DebarmentDefaultHttpTransport:
    """Default HTTP transport that fails fast and loud."""

    def send(self, request: DebarmentHttpRequest) -> DebarmentHttpResponse:
        raise DebarmentHttpTransportError(
            "DebarmentAdapter has no real HTTP transport wired in. "
            "Inject a DebarmentHttpTransport (e.g. "
            "StaticDebarmentHttpTransport) for tests, or wire a "
            "real HTTPS client in a future milestone."
        )


class StaticDebarmentHttpTransport:
    """Deterministic in-memory HTTP transport for tests.

    Maps a request ``url`` / ``body`` key to a fixed
    :class:`DebarmentHttpResponse`. The lookup key is computed
    by ``request_key`` (default: the query ``identifier`` field of
    the body). The transport records every request so tests can
    assert on the request side of the contract.
    """

    def __init__(
        self,
        responses: dict[str, DebarmentHttpResponse] | None = None,
        *,
        default_response: DebarmentHttpResponse | None = None,
        request_key: Any = None,
    ) -> None:
        self._responses: dict[str, DebarmentHttpResponse] = dict(
            responses or {}
        )
        self._default = default_response
        self.requests: list[DebarmentHttpRequest] = []
        # ``request_key`` is a callable (request) -> str. The default
        # looks up ``request.body["identifier"]``; tests for
        # name-only or composite keys can supply a different callable.
        self._request_key = request_key or (
            lambda r: (r.body or {}).get("identifier", "")
        )

    def set(
        self, key: str, response: DebarmentHttpResponse
    ) -> None:
        self._responses[key] = response

    def send(self, request: DebarmentHttpRequest) -> DebarmentHttpResponse:
        # Refuse plain HTTP at the transport boundary -- not just at
        # config-validation time. A real adapter must always go over
        # HTTPS; the transport is the enforcement point.
        if not request.url.lower().startswith("https://"):
            raise DebarmentHttpTransportError(
                "Debarment transport refuses non-HTTPS URLs. "
                "Configure an HTTPS endpoint."
            )
        self.requests.append(request)
        key = self._request_key(request)
        response = self._responses.get(key)
        if response is not None:
            return response
        if self._default is not None:
            return self._default
        # No canned response: surface as 404 so the parser can
        # map to NOT_FOUND deterministically.
        return DebarmentHttpResponse(
            status_code=404,
            body_json=None,
            latency_ms=None,
            correlation_id=None,
        )


# ---------------------------------------------------------------------------
# Helper: static transport for the legacy ``VerificationTransport`` seam
# ---------------------------------------------------------------------------


class StaticDebarmentTransport:
    """Deterministic in-memory transport for the legacy seam.

    Maps an identifier (key) to a fixed
    :class:`SourceResponseEnvelope`. The lookup key is extracted
    from a query by the ``query_key`` callable (default:
    ``query.identifier``). The transport records every query so
    tests can assert on the request side of the contract.
    """

    def __init__(
        self,
        responses: dict[str, SourceResponseEnvelope] | None = None,
        *,
        default_response: SourceResponseEnvelope | None = None,
        query_key: Any = None,
    ) -> None:
        self._responses: dict[str, SourceResponseEnvelope] = dict(
            responses or {}
        )
        self._default = default_response
        self.queries: list[Any] = []
        self._query_key = query_key or (lambda q: q.identifier)

    def set(
        self, key: str, envelope: SourceResponseEnvelope
    ) -> None:
        self._responses[key] = envelope

    def send_query(self, query: Any) -> SourceResponseEnvelope:
        self.queries.append(query)
        key = self._query_key(query)
        envelope = self._responses.get(key)
        if envelope is not None:
            return envelope
        if self._default is not None:
            return self._default
        return SourceResponseEnvelope(
            status_code=404,
            raw_response=None,
            latency_ms=None,
            correlation_id=None,
        )


def http_response_to_envelope(
    response: DebarmentHttpResponse,
) -> SourceResponseEnvelope:
    """Convert an :class:`DebarmentHttpResponse` to a transport envelope.

    Kept separate so the parsing seam stays unit-testable without
    instantiating a transport.
    """

    return SourceResponseEnvelope(
        status_code=response.status_code,
        raw_response=response.body_json,
        latency_ms=response.latency_ms,
        correlation_id=response.correlation_id,
    )


# ---------------------------------------------------------------------------
# Matching helper
# ---------------------------------------------------------------------------


def derive_match_method(
    *,
    queried_identifier: str,
    queried_subject_name: str | None,
    source_identifier: str | None,
    source_name_original: str | None,
) -> MatchMethod:
    """Return the deterministic :class:`MatchMethod` for a source match.

    Precedence:

    1. Exact identifier match -> ``EXACT_IDENTIFIER``.
    2. Normalized identifier match -> ``NORMALIZED_IDENTIFIER``.
    3. Exact name match -> ``EXACT_NAME``.
    4. Normalized name match -> ``NORMALIZED_NAME``.
    5. Otherwise -> ``INSUFFICIENT_EVIDENCE``.

    Identifier matches always win over name matches. Name-only
    matches that are merely "similar" are reported as
    :attr:`MatchMethod.INSUFFICIENT_EVIDENCE` -- they never become
    a legal compliance match.
    """

    qid_norm = normalize_identifier(queried_identifier)
    sid_norm = normalize_identifier(source_identifier)
    if qid_norm is not None and sid_norm is not None:
        if queried_identifier == source_identifier:
            return MatchMethod.EXACT_IDENTIFIER
        if qid_norm == sid_norm:
            return MatchMethod.NORMALIZED_IDENTIFIER

    qname = (queried_subject_name or "").strip() or None
    sname = (source_name_original or "").strip() or None
    if qname is not None and sname is not None:
        if qname == sname:
            return MatchMethod.EXACT_NAME
        # Conservative normalization: uppercase + collapse whitespace.
        # Identity normalizer is reused for the source side via the
        # caller; here we only need a deterministic, narrow check.
        qname_norm = " ".join(qname.split()).upper()
        sname_norm = " ".join(sname.split()).upper()
        if qname_norm == sname_norm:
            return MatchMethod.NORMALIZED_NAME

    return MatchMethod.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class DebarmentResponseParser:
    """Map a :class:`SourceResponseEnvelope` to a :class:`Verification`.

    Mapping rules
    -------------

    The domain :class:`VerificationStatus` is derived from the
    transport status, **NOT** from the business restriction status
    inside the payload. The two coexist on the returned
    :class:`Verification` and the rule consumes both.

    * 5xx (or transport exception) -> ``UNAVAILABLE``.
    * 4xx with no usable payload -> ``NOT_FOUND`` (no record on the
      queried subject).
    * 4xx with payload that explicitly signals a malformed
      identifier -> ``INVALID``.
    * 2xx with payload that lacks a ``restriction_status`` field
      -> ``ERROR`` (malformed payload).
    * 2xx with a usable payload -> ``VERIFIED``, with the business
      restriction status preserved on ``data["restriction_status"]``.

    Important
    ---------

    4xx does **NOT** automatically mean CLEAR. The adapter reports
    the transport status as ``NOT_FOUND``; the *rule* layer
    translates ``NOT_FOUND`` into ``UNVERIFIABLE``. The rule never
    converts a transport-layer "no record" outcome into a positive
    eligibility conclusion.
    """

    def parse(
        self,
        envelope: SourceResponseEnvelope,
        *,
        query: DebarmentQuery,
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
                source=DebarmentAdapter.SOURCE,
                identifier=query.identifier,
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
            capability=DEBARMENT_CAPABILITY,
            source=DebarmentAdapter.SOURCE,
            queried_identifier=query.identifier,
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
            # identifier, surface it as INVALID.
            if raw.get("identifier_status") == "INVALID":
                return VerificationStatus.INVALID, {}
            # If the payload carries a recognisable business
            # status, normalise it through the parser.
            if "restriction_status" in raw:
                status, data = (
                    DebarmentResponseParser._status_from_payload(raw)
                )
                return status, data
            # Otherwise treat as no record.
            return VerificationStatus.NOT_FOUND, {}

        if 200 <= code < 300:
            if raw is None:
                return VerificationStatus.ERROR, {}
            return DebarmentResponseParser._status_from_payload(raw)

        return VerificationStatus.ERROR, {}
    @staticmethod
    def _status_from_payload(
        raw: dict[str, Any],
    ) -> tuple[VerificationStatus, dict[str, Any]]:
        # The business restriction status is the payload's
        # ``restriction_status`` value; we map it to the domain
        # ``VerificationStatus`` and store both on ``data`` so the
        # rule can read the business status verbatim.
        restriction = raw.get("restriction_status")
        if restriction == DebarmentRestrictionStatus.CLEAR.value:
            return (
                VerificationStatus.VERIFIED,
                DebarmentResponseParser._build_data(raw),
            )
        if restriction == DebarmentRestrictionStatus.RESTRICTED.value:
            return (
                VerificationStatus.VERIFIED,
                DebarmentResponseParser._build_data(raw),
            )
        if restriction == DebarmentRestrictionStatus.UNKNOWN.value:
            # ``UNKNOWN`` business status -> ``ERROR`` at the
            # transport layer; the rule translates this to
            # ``UNVERIFIABLE``.
            return VerificationStatus.ERROR, DebarmentResponseParser._build_data(raw)
        # Unknown / missing business status -> malformed.
        return VerificationStatus.ERROR, {}

    @staticmethod
    def _build_data(raw: dict[str, Any]) -> dict[str, Any]:
        """Build the normalized data dict from a raw payload.

        Unrecognised restriction_type values are coerced to
        ``OTHER`` to preserve strict enum semantics. Unknown
        subject_type values are coerced to ``UNKNOWN``.
        """

        kwargs: dict[str, Any] = {}
        restriction_status = raw.get("restriction_status")
        if restriction_status is not None:
            try:
                kwargs["restriction_status"] = (
                    DebarmentRestrictionStatus(restriction_status)
                )
            except ValueError:
                kwargs["restriction_status"] = (
                    DebarmentRestrictionStatus.UNKNOWN
                )
        restriction_type = raw.get("restriction_type")
        if restriction_type is not None:
            try:
                kwargs["restriction_type"] = (
                    DebarmentRestrictionType(restriction_type)
                )
            except ValueError:
                kwargs["restriction_type"] = (
                    DebarmentRestrictionType.OTHER
                )
        if "effective_date" in raw:
            kwargs["effective_date"] = raw.get("effective_date")
        if "end_date" in raw:
            kwargs["end_date"] = raw.get("end_date")
        if "issuing_authority" in raw:
            kwargs["issuing_authority"] = raw.get("issuing_authority")
        if "reference_number" in raw:
            kwargs["reference_number"] = raw.get("reference_number")
        if "source_reference" in raw:
            kwargs["source_reference"] = raw.get("source_reference")
        subject_type = raw.get("subject_type")
        if subject_type is not None:
            try:
                kwargs["subject_type"] = SubjectType(subject_type)
            except ValueError:
                kwargs["subject_type"] = SubjectType.UNKNOWN
        if "subject_identifier" in raw:
            kwargs["subject_identifier"] = raw.get("subject_identifier")
        if "subject_name_original" in raw:
            kwargs["subject_name_original"] = (
                raw.get("subject_name_original")
            )
        # Compute normalized subject name via the helper if a
        # subject name is present so the rule can consume it
        # without re-normalizing.
        if kwargs.get("subject_name_original"):
            try:
                from ai_verification.identity.normalization import (
                    normalize_legal_name,
                )
                kwargs["subject_name_normalized"] = (
                    normalize_legal_name(
                        kwargs["subject_name_original"]
                    )
                )
            except Exception:
                # The identity normalizer is a stable function; if
                # anything goes wrong here it must NOT corrupt the
                # audit record.
                kwargs["subject_name_normalized"] = None
        match_method = raw.get("match_method")
        if match_method is not None:
            try:
                kwargs["match_method"] = MatchMethod(match_method)
            except ValueError:
                kwargs["match_method"] = (
                    MatchMethod.INSUFFICIENT_EVIDENCE
                )
        try:
            return NormalizedDebarmentData(**kwargs).model_dump()
        except Exception:
            # Fall back to a minimal CLEAR payload if the data
            # cannot be normalised -- never raise into the rule.
            return NormalizedDebarmentData(
                restriction_status=DebarmentRestrictionStatus.UNKNOWN
            ).model_dump()


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class DebarmentAdapter(VerificationProvider):
    """A production-shaped procurement-eligibility adapter.

    Implements the existing :meth:`VerificationProvider.verify`
    contract so :class:`ComplianceEngine` and
    :class:`DebarmentEligibilityRule` work unchanged. Two execution
    paths are supported:

    * The legacy path uses the generic
      :class:`VerificationTransport` abstraction. It is the default
      when the adapter is constructed without an HTTP transport.
    * The real-provider path is used when the adapter is
      constructed with an :class:`DebarmentHttpTransport` and goes
      through the :class:`DebarmentDefaultHttpTransport` /
      :class:`StaticDebarmentHttpTransport` seam.

    Both paths produce the same :class:`Verification` shape, so
    the Compliance Engine and AI Verification do not need to know
    which one fired.
    """

    SOURCE: Final[str] = DEBARMENT_SOURCE

    def __init__(
        self,
        transport: VerificationTransport | None = None,
        parser: "DebarmentResponseParser | None" = None,
        *,
        http_transport: "DebarmentHttpTransport | None" = None,
    ) -> None:
        self._transport: VerificationTransport = (
            transport or InProcessTransport()
        )
        self._parser = parser or DebarmentResponseParser()
        self._http_transport: Any = http_transport

    def verify(
        self, bidder_id: str, identifier: str, **kwargs: Any
    ) -> Verification:
        """Query the debarment transport and return a
        :class:`Verification`.

        ``identifier`` is the primary identifier being looked up
        (GSTIN / PAN / CIN / DIN / LLPIN / name). ``kwargs`` may
        carry:

        * ``subject_name`` -- optional name to forward into the
          audit trail.
        * ``evaluation_date`` -- caller-supplied date for the
          active-restriction window.
        * ``verification_id`` -- pre-allocated verification ID.
        * ``correlation_id`` -- end-to-end trace ID.

        Unrecognised kwargs are ignored for forward-compatibility.
        """

        query = DebarmentQuery(
            bidder_id=bidder_id,
            identifier=str(identifier),
            subject_name=kwargs.get("subject_name"),
            evaluation_date=kwargs.get("evaluation_date"),
            verification_id=kwargs.get("verification_id"),
            correlation_id=kwargs.get("correlation_id"),
        )
        if self._http_transport is not None:
            return self._verify_with_http_transport(query, bidder_id)
        return self._verify_with_legacy_transport(query, bidder_id)

    def _verify_with_legacy_transport(
        self, query: DebarmentQuery, bidder_id: str
    ) -> Verification:
        try:
            envelope = self._transport.send_query(query)
        except (TransportError, NotImplementedError):
            return self._unavailable(query)
        return self._parser.parse(
            envelope, query=query, bidder_id=bidder_id
        )

    def _verify_with_http_transport(
        self, query: DebarmentQuery, bidder_id: str
    ) -> Verification:
        assert self._http_transport is not None
        request = DebarmentHttpRequest(
            method="POST",
            url="https://example.invalid/debarment/query",
            body=query.model_dump(),
            timeout_seconds=10.0,
        )
        try:
            response = self._http_transport.send(request)
        except DebarmentHttpTransportError:
            return self._unavailable(query)
        envelope = http_response_to_envelope(response)
        return self._parser.parse(
            envelope, query=query, bidder_id=bidder_id
        )

    def _unavailable(self, query: DebarmentQuery) -> Verification:
        verification_id = (
            query.verification_id
            if query.verification_id
            else Verification.allocate_id(
                source=self.SOURCE,
                identifier=query.identifier,
                call_id=query.call_id,
            )
        )
        return Verification(
            verification_id=verification_id,
            bidder_id=query.bidder_id,
            capability=DEBARMENT_CAPABILITY,
            source=self.SOURCE,
            queried_identifier=query.identifier,
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
    "DEBARMENT_CAPABILITY",
    "DEBARMENT_SOURCE",
    "DebarmentAdapter",
    "DebarmentDefaultHttpTransport",
    "DebarmentHttpRequest",
    "DebarmentHttpResponse",
    "DebarmentHttpTransport",
    "DebarmentHttpTransportError",
    "DebarmentResponseEnvelope",
    "DebarmentResponseParser",
    "StaticDebarmentHttpTransport",
    "StaticDebarmentTransport",
    "derive_match_method",
    "http_response_to_envelope",
]
