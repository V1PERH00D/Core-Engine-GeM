"""HTTPS transport seam for the future GSTN verification integration.

This module defines the **typed boundary** between the GSTN
adapter and the real network. It does **not** ship a working
client: it provides

* :class:`GstHttpTransport` -- a typed HTTPS transport interface
  that is fully mockable for unit tests.
* :class:`GstHttpResponse` -- the raw response envelope that the
  parser is expected to consume.
* :class:`GstHttpClient` -- a thin HTTPS client that performs a
  real POST with explicit timeout, latency capture, and
  correlation propagation.
* :class:`StaticGstTransport` -- a deterministic in-memory
  transport used by tests to exercise every status branch without
  touching the network.

Design constraints
------------------

* No hardcoded credentials, secrets, or endpoint URLs.
* No network is opened during tests; the default in-memory
  transport is wired into :class:`GSTNAdapter` for unit tests.
* Switching to the real client requires a fully populated
  :class:`GstConfig` and is opt-in: it is never activated
  implicitly by importing the module.
* HTTPS-only: any non-HTTPS scheme is rejected with
  :class:`GstTransportError` before the request is sent.
* Transport-layer exceptions map to ``VerificationStatus``
  ``UNAVAILABLE`` / ``ERROR`` so the rule layer never sees a
  raw exception.

The exact request / response body shape used by the real GSTN
service is NOT known from documented information available to
this repository; the future production body builder is left as
a plug-in ``request_builder`` callable injected at construction
time, defaulting to a no-op that sends a minimal placeholder
payload. The real signing implementation is similarly a plug-in
``sign_request`` callable, defaulting to a no-op.
"""

from __future__ import annotations

import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol, runtime_checkable
from urllib.parse import urlparse

from pydantic import BaseModel

from compliance_engine.verification.gst_config import GstConfig, GstEndpointConfig
from compliance_engine.verification.transport import GstQuery, SourceResponseEnvelope


# ---------------------------------------------------------------------------
# Transport contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GstHttpResponse:
    """Raw response from the real GSTN service.

    This is **not** the domain :class:`Verification` -- it is the
    transport-layer artefact. The GSTN parser is responsible for
    turning it into a typed :class:`SourceResponseEnvelope` and
    then into a :class:`Verification`.
    """

    status_code: int
    body_json: Any
    latency_ms: int
    correlation_id: str | None


@runtime_checkable
class GstHttpTransport(Protocol):
    """Pluggable HTTPS transport for the GSTN service.

    The default implementation below is an in-process fake used
    in tests; the real :class:`GstHttpClient` performs a real
    HTTPS POST.

    The ``send`` method is typed against :class:`BaseModel` so the
    same transport can carry both :class:`GstQuery` (registration)
    and :class:`GstReturnQuery` (return filing) without committing
    to a universal GST query schema.
    """

    def send(self, request: BaseModel) -> GstHttpResponse:
        ...


# ---------------------------------------------------------------------------
# Static / in-process test transport
# ---------------------------------------------------------------------------


class StaticGstTransport:
    """Deterministic in-memory transport used by unit tests.

    A simple map of ``gstin -> GstHttpResponse`` is enough to
    cover every documented response shape. The transport records
    every query it received so tests can assert on the request
    side of the contract.

    The lookup key is extracted from a query by the ``query_key``
    callable (default: ``request.gstin``) so the same transport
    can serve both registration (``GstQuery``) and return-filing
    (``GstReturnQuery``) lookups.
    """

    def __init__(
        self,
        responses: Optional[dict[str, GstHttpResponse]] = None,
        *,
        default_response: Optional[GstHttpResponse] = None,
        query_key: Any = None,
    ) -> None:
        self._responses: dict[str, GstHttpResponse] = dict(responses or {})
        self._default = default_response
        self.queries: list[BaseModel] = []
        # ``query_key`` is a callable (query) -> str. The default
        # looks up ``query.gstin``; return-filing tests can supply
        # a different callable that also considers the financial
        # year and return type.
        self._query_key = query_key or (
            lambda q: getattr(q, "gstin", "")
        )

    def set(self, key: str, response: GstHttpResponse) -> None:
        self._responses[key] = response

    def send(self, request: BaseModel) -> GstHttpResponse:
        self.queries.append(request)
        key = self._query_key(request)
        envelope = self._responses.get(key)
        if envelope is not None:
            return envelope
        if self._default is not None:
            return self._default
        # No canned response: surface this as a 404 transport
        # status so the parser can map to NOT_FOUND deterministically.
        return GstHttpResponse(
            status_code=404,
            body_json=None,
            latency_ms=None,  # type: ignore[arg-type]
            correlation_id=getattr(request, "correlation_id", None),
        )


# ---------------------------------------------------------------------------
# Real HTTPS client
# ---------------------------------------------------------------------------


class GstTransportError(RuntimeError):
    """Raised when the GSTN transport layer cannot complete the request.

    The provider adapter catches this and translates it into a
    :class:`VerificationStatus.UNAVAILABLE` (or
    :class:`VerificationStatus.ERROR` for parse-time failures) so
    the rule layer never sees a transport exception.
    """


#: Signature of an optional request body builder. The real GSTN
#: request body shape is not in scope for this milestone, so the
#: default builder returns ``None`` (i.e. no body). A future
#: integration supplies a concrete builder at construction time.
#: Typed against :class:`BaseModel` so the same builder can be
#: reused for both :class:`GstQuery` and :class:`GstReturnQuery`.
GstRequestBuilder = Callable[[BaseModel], Optional[bytes]]

#: Signature of an optional request signer. A real integration
#: injects a signer that returns a new header map. The default
#: is a no-op (returns the headers unchanged).
GstSigner = Callable[[BaseModel, dict[str, str]], dict[str, str]]


def _noop_request_builder(query: BaseModel) -> Optional[bytes]:
    """Default request body builder used when none is injected.

    The exact production body shape is not in scope for this
    milestone; the default emits a deterministic placeholder so
    the HTTPS path is exercised end-to-end without inventing
    fields.
    """

    return None


def _noop_signer(query: BaseModel, headers: dict[str, str]) -> dict[str, str]:
    """Default signer used when none is injected.

    No cryptographic operation is performed; the headers are
    returned unchanged. A real integration injects a WS-Security
    / signed-payload header map here.
    """

    return dict(headers)


class _OpenerCallable(Protocol):
    def __call__(
        self,
        *,
        url: str,
        body: Optional[bytes],
        headers: dict[str, str],
        timeout: float,
    ) -> Any: ...


def _default_opener(
    *,
    url: str,
    body: Optional[bytes],
    headers: dict[str, str],
    timeout: float,
) -> Any:
    """Default HTTPS opener using the standard library.

    Uses :class:`http.client.HTTPSConnection` so we do not pull in
    a third-party HTTP client. Certificate verification is ON by
    default.
    """

    import http.client

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise GstTransportError(
            "GSTN endpoint must use HTTPS; got scheme: "
            + str(parsed.scheme)
        )
    host = parsed.hostname or ""
    port = parsed.port or 443
    path = parsed.path or "/"
    if parsed.query:
        path = path + "?" + parsed.query

    context = ssl.create_default_context()
    connection = http.client.HTTPSConnection(
        host=host, port=port, timeout=timeout, context=context
    )
    try:
        connection.request(
            method="POST",
            url=path,
            body=body,
            headers=headers,
        )
        response = connection.getresponse()
        response_body = response.read().decode("utf-8", errors="replace")
        # Parse JSON if possible, otherwise keep the raw body so
        # the parser can decide. Returned as a 2-tuple to mirror
        # the ``(body, status)`` shape used elsewhere.
        try:
            import json

            body_json: Any = json.loads(response_body) if response_body else None
        except Exception:
            body_json = response_body
        return _DefaultOpenerResult(
            body=body_json, status=int(response.status)
        )
    finally:
        connection.close()


@dataclass(frozen=True)
class _DefaultOpenerResult:
    body: Any
    status: int


class GstHttpClient:
    """Real HTTPS client for the GSTN service.

    The client is **opt-in**: the default :class:`GSTNAdapter` is
    wired against an in-memory transport for unit tests.
    Switching to the real client requires a fully populated
    :class:`GstConfig`; see :meth:`GstConfig.validate_for_real_use`.

    No credential is ever hardcoded; the only configuration this
    client needs is the endpoint URL, the timeout, and (via the
    injected signer) the headers.
    """

    def __init__(
        self,
        config: GstConfig,
        *,
        request_builder: GstRequestBuilder | None = None,
        signer: GstSigner | None = None,
        opener: _OpenerCallable | None = None,
    ) -> None:
        # The config is validated on construction only when the
        # caller explicitly opts in. We do NOT raise here so unit
        # tests can still construct the client with a partially
        # populated config; the real-mode wiring is expected to
        # call ``GstConfig.validate_for_real_use`` first.
        self._config = config
        self._endpoint: GstEndpointConfig = config.endpoint
        self._request_builder: GstRequestBuilder = (
            request_builder or _noop_request_builder
        )
        self._signer: GstSigner = signer or _noop_signer
        # ``opener`` is an indirection over the network seam so
        # tests can swap it without monkey-patching.
        self._opener: _OpenerCallable = opener or _default_opener

    def send(self, request: BaseModel) -> GstHttpResponse:
        endpoint = self._endpoint
        body = self._request_builder(request)
        headers = self._signer(
            request,
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        start = time.monotonic()
        try:
            result = self._opener(
                url=endpoint.url,
                body=body,
                headers=headers,
                timeout=endpoint.timeout_seconds,
            )
        except (TimeoutError, socket.timeout) as exc:
            raise GstTransportError(
                "GSTN service request timed out after "
                + str(endpoint.timeout_seconds)
                + "s"
            ) from exc
        except (ssl.SSLError, OSError) as exc:
            raise GstTransportError(
                "GSTN service request failed at the transport layer: "
                + str(exc)
            ) from exc
        latency_ms = int((time.monotonic() - start) * 1000)

        return GstHttpResponse(
            status_code=int(getattr(result, "status", 0)),
            body_json=getattr(result, "body", None),
            latency_ms=latency_ms,
            correlation_id=getattr(request, "correlation_id", None),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def http_response_to_envelope(response: GstHttpResponse) -> SourceResponseEnvelope:
    """Convert a :class:`GstHttpResponse` into a generic
    :class:`SourceResponseEnvelope` for the parser seam.

    The conversion preserves the transport metadata (status code,
    latency, correlation id) on the envelope. The ``raw_response``
    field carries the body as a dict when the body is itself a
    dict, or as ``None`` otherwise; the parser decides what to
    do with non-dict bodies.
    """

    raw = response.body_json
    if not isinstance(raw, dict):
        raw = None
    return SourceResponseEnvelope(
        status_code=response.status_code,
        raw_response=raw,
        latency_ms=response.latency_ms,
        correlation_id=response.correlation_id,
    )


__all__ = [
    "GstHttpClient",
    "GstHttpResponse",
    "GstHttpTransport",
    "GstRequestBuilder",
    "GstSigner",
    "GstTransportError",
    "StaticGstTransport",
    "http_response_to_envelope",
]
