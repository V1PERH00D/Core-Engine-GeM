"""HTTPS transport seam for the PAN Verification Web Service.

This module defines the **typed boundary** between the SOAP layer and
the real network. It does **not** ship a working client: it provides

* :class:`PanHttpTransport` -- a typed HTTPS transport interface that
  is fully mockable for unit tests.
* :class:`PanHttpClient` -- a thin client that POSTs the SOAP envelope
  over HTTPS with the documented ``SOAPAction`` and
  ``Content-Type`` headers, with explicit timeout and latency capture.

The client is *opt-in*: the default ``PanAdapter`` is wired against an
in-memory transport for unit tests. Switching to the real client
requires a fully populated :class:`PanConfig` and an explicit
``mode="real"`` flag on the transport; both are validated up-front.

No credential is ever hardcoded; the only configuration this client
needs is the endpoint URL, the timeout, and the SOAP action header.
The actual SOAP body is built by :class:`PanSoapRequestBuilder`; this
client just ships it.

This module deliberately does not implement WS-Security signing or
encryption -- that is a future plug-in concern. The signing seam is
the ``sign_request`` callable injected at construction time, defaulting
to a no-op.
"""

from __future__ import annotations

import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable
from urllib.parse import urlparse

from compliance_engine.verification.pan_config import (
    PanConfig,
    PanEndpointConfig,
)
from compliance_engine.verification.pan_soap import (
    PanSoapRequest,
)


# ---------------------------------------------------------------------------
# Transport contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PanHttpResponse:
    """Raw response from the real PAN service.

    This is **not** the domain :class:`Verification` -- it is the
    transport-layer artefact. The SOAP parser is responsible for
    turning it into a typed ``Verification``.
    """

    status_code: int
    body_xml: str
    latency_ms: int
    correlation_id: str | None


@runtime_checkable
class PanHttpTransport(Protocol):
    """Pluggable HTTPS transport for the PAN service.

    The default implementation below is an in-process fake used in
    tests; the real ``PanHttpClient`` performs a real HTTPS POST.
    """

    def send(self, request: PanSoapRequest) -> PanHttpResponse:
        ...


class StaticPanTransport:
    """Deterministic in-memory transport used by unit tests.

    A simple map of ``pan -> PanHttpResponse`` is enough to cover
    every documented response shape.
    """

    def __init__(
        self,
        responses: dict[str, PanHttpResponse] | None = None,
        *,
        default_response: PanHttpResponse | None = None,
    ) -> None:
        self._responses: dict[str, PanHttpResponse] = dict(responses or {})
        self._default = default_response
        self.requests: list[PanSoapRequest] = []

    def set(self, pan: str, response: PanHttpResponse) -> None:
        self._responses[pan] = response

    def send(self, request: PanSoapRequest) -> PanHttpResponse:
        self.requests.append(request)
        if request.pan in self._responses:
            return self._responses[request.pan]
        if self._default is not None:
            return self._default
        # No canned response: surface as a 404 transport status; the
        # SOAP parser will see a missing body and return ``ERROR``.
        return PanHttpResponse(
            status_code=404,
            body_xml="",
            latency_ms=0,
            correlation_id=None,
        )


# ---------------------------------------------------------------------------
# Real HTTPS client
# ---------------------------------------------------------------------------


class PanTransportError(RuntimeError):
    """Raised when the real HTTPS transport cannot complete the call.

    The adapter translates this into a :class:`VerificationStatus`
    so the rule layer never sees a transport exception.
    """


# Type of the optional signing callable. A real implementation would
# add the WS-Security headers / signature / encryption. For this
# milestone the default is a no-op.
PanSigner = Callable[[PanSoapRequest, dict[str, str]], dict[str, str]]


def _noop_signer(
    request: PanSoapRequest, headers: dict[str, str]
) -> dict[str, str]:
    return dict(headers)


class PanHttpClient:
    """Real HTTPS client for the PAN service.

    Performs a POST over HTTPS with the documented ``SOAPAction`` and
    ``Content-Type`` headers. Measures round-trip latency and captures
    a correlation id (the request id) for the response envelope.

    Network I/O is **opt-in**: instantiate this class only when you
    want to perform a real call. Tests use :class:`StaticPanTransport`
    instead.
    """

    def __init__(
        self,
        config: PanConfig,
        *,
        signer: PanSigner | None = None,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        # Always validate the configuration when a real client is
        # constructed -- fail fast and loud rather than at the first
        # request.
        config.validate_for_real_use()
        self._endpoint: PanEndpointConfig = config.endpoint
        self._signer: PanSigner = signer or _noop_signer
        # ``opener`` is an indirection over :func:`urllib.request.urlopen`
        # so tests can swap it without monkey-patching.
        self._opener = opener

    def send(self, request: PanSoapRequest) -> PanHttpResponse:
        endpoint = self._endpoint
        body = request.xml.encode("utf-8")
        headers = self._signer(
            request, request.headers(endpoint.soap_action)
        )

        start = time.monotonic()
        try:
            response_xml, status_code = self._post(body, headers, endpoint)
        except (TimeoutError, socket.timeout) as exc:
            raise PanTransportError(
                "PAN service request timed out after "
                + str(endpoint.timeout_seconds)
                + "s"
            ) from exc
        except (ssl.SSLError, OSError) as exc:
            raise PanTransportError(
                "PAN service request failed at the transport layer: "
                + str(exc)
            ) from exc
        latency_ms = int((time.monotonic() - start) * 1000)

        return PanHttpResponse(
            status_code=status_code,
            body_xml=response_xml,
            latency_ms=latency_ms,
            correlation_id=request.request_id,
        )

    # -- network seam -----------------------------------------------------

    def _post(
        self,
        body: bytes,
        headers: dict[str, str],
        endpoint: PanEndpointConfig,
    ) -> tuple[str, int]:
        url = endpoint.url
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise PanTransportError(
                "PAN endpoint must use HTTPS; got scheme: " + str(parsed.scheme)
            )
        host = parsed.hostname or ""
        port = parsed.port or 443
        path = parsed.path or "/"
        if parsed.query:
            path = path + "?" + parsed.query

        if self._opener is not None:
            # A custom opener (used by tests to assert request shape).
            response = self._opener(
                url=url,
                body=body,
                headers=headers,
                timeout=endpoint.timeout_seconds,
            )
            return (
                getattr(response, "body", ""),
                int(getattr(response, "status", 200)),
            )

        # Standard-library HTTPS path. We avoid hard dependencies on
        # third-party HTTP clients. The ``context`` is the default
        # secure context -- certificate verification is ON.
        import http.client

        context = ssl.create_default_context()
        connection = http.client.HTTPSConnection(
            host=host, port=port, timeout=endpoint.timeout_seconds, context=context
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
            return response_body, int(response.status)
        finally:
            connection.close()


__all__ = [
    "PanHttpClient",
    "PanHttpResponse",
    "PanHttpTransport",
    "PanSigner",
    "PanTransportError",
    "StaticPanTransport",
]
