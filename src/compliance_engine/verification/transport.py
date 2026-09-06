"""Transport seam for real government verification sources.

This module defines the **smallest** abstraction needed to keep the
provider-adapter contract honest about where future HTTP / network /
credentials / signing concerns will live, without actually implementing
any of them.

Design goals
------------

* No network, no HTTP, no scraping, no credentials, no authentication
  in this milestone.
* The transport object is a ``Protocol`` (duck-typed) with one method:
  it accepts a query envelope and returns a response envelope.
* A default ``InProcessTransport`` raises ``NotImplementedError`` so
  the production-shaped adapters that depend on it fail fast and loud
  if they are ever wired in without a real transport.
* A :class:`StaticTransport` is provided for deterministic testing.

The transport is intentionally tiny. The real GSTN/Udyam/PAN/MCA
adapters will at some later milestone subclass it (or supply their own
implementation) to plug in HTTP clients, OAuth, request signing, etc.

Source-specific query and response shapes live next to their adapter
(:class:`GstQuery` here; ``UdyamQuery``, ``PanQuery``, ``McaQuery``
in their respective adapter modules). The transport is generic over
the query/envelope types via :class:`VerificationTransport` so a single
transport can be shared by every source.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from compliance_engine.models.verification import VerificationStatus


class TransportError(RuntimeError):
    """Raised when the transport layer cannot complete the request.

    The provider adapter catches this and translates it into a
    :class:`VerificationStatus.ERROR` or :class:`VerificationStatus.UNAVAILABLE`
    so the rule layer never sees a transport exception.
    """


# TypeVars make the Protocol reusable for any source's query/envelope
# pair without forcing a single universal query schema.
_QueryT = TypeVar("_QueryT", bound=BaseModel)
_EnvelopeT = TypeVar("_EnvelopeT", bound="SourceResponseEnvelope")


class SourceResponseEnvelope(BaseModel):
    """Generic transport-layer response envelope.

    The transport returns one of these for every source. ``raw_response``
    is the unmodified, structured payload the future HTTP client would
    receive; ``status_code`` is the HTTP-style transport status, which
    is **advisory only** and is stored on ``Verification`` for audit.
    The domain :class:`VerificationStatus` is derived from the
    payload by the per-source parser, never from ``status_code`` alone.
    """

    model_config = ConfigDict(extra="forbid")

    status_code: int = Field(
        ..., description="Transport status code (HTTP-style). Advisory only."
    )
    raw_response: dict[str, Any] | None = Field(
        None, description="Unparsed response payload."
    )
    latency_ms: int | None = Field(
        None, description="Round-trip latency in milliseconds."
    )
    correlation_id: str | None = Field(
        None, description="End-to-end correlation id, if available."
    )


# Backward-compatible alias: existing callers import GstResponseEnvelope
# from this module. New code should prefer SourceResponseEnvelope.
GstResponseEnvelope = SourceResponseEnvelope


def _new_call_id() -> str:
    """Generate a per-call UUID4 hex string used in the query envelope.

    Each adapter call produces a fresh ``call_id`` so that two
    verification events for the same source + identifier have distinct
    ``Verification.verification_id`` values.
    """
    return uuid4().hex


class GstQuery(BaseModel):
    """Typed query for a future GSTN request.

    The model is **GST-specific** and intentionally does not grow
    into a universal government query. A real GSTN adapter would
    also receive authentication headers, request signing, and a
    correlation id from the caller; those are intentionally out of
    scope for this milestone and are documented as extension points
    in :class:`GSTNAdapter`.

    Three distinct per-call identity concepts are modelled here, and
    they are deliberately separate fields so a future integration can
    populate all three from independent sources (e.g. transport
    supplies the ``correlation_id``, the engine supplies the
    ``verification_id``, and the adapter supplies the ``call_id``):

    * ``call_id`` — per-attempt UUID4, generated here. Used as the
      tail of :attr:`Verification.verification_id` so two attempts
      against the same source + identifier produce distinct
      verification IDs.
    * ``verification_id`` — pre-allocated by the engine / rule
      layer when the consumer needs the audit ID known up-front
      (e.g. for cross-system correlation). ``None`` by default;
      when supplied the adapter is expected to use it as the
      returned ``Verification.verification_id`` instead of
      generating one.
    * ``correlation_id`` — end-to-end trace ID shared with other
      systems. ``None`` by default; a future real transport that
      injects tracing will populate this.
    """

    model_config = ConfigDict(extra="forbid")

    bidder_id: str = Field(
        ..., description="Bidder whose GSTIN is being verified."
    )
    gstin: str = Field(
        ..., description="The GSTIN being queried."
    )
    call_id: str = Field(
        default_factory=_new_call_id,
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
            "transport for tracing. Distinct from ``call_id`` and "
            "``verification_id``."
        ),
    )


@runtime_checkable
class VerificationTransport(Protocol):
    """Pluggable transport for verification providers.

    Adapters call ``send_query(query)`` and receive a
    :class:`SourceResponseEnvelope`. The transport is the only place
    where future HTTP, authentication, and signing concerns will
    live. The default implementation raises
    :class:`NotImplementedError` so a real adapter cannot accidentally
    execute against the network in this milestone.
    """

    def send_query(self, query: _QueryT) -> _EnvelopeT:
        ...


class InProcessTransport:
    """Default transport that fails fast and loud.

    Wiring a real adapter to this transport will raise
    :class:`NotImplementedError` on the first query, which is the
    intended behaviour for a milestone that must not perform any
    network I/O.
    """

    def send_query(self, query: Any) -> SourceResponseEnvelope:
        raise NotImplementedError(
            "Adapter has no real transport. "
            "Inject a VerificationTransport (e.g. StaticTransport) "
            "for tests, or wire a real HTTP client in a future milestone."
        )


class StaticTransport:
    """Deterministic in-memory transport for tests.

    Maps an identifier (key) to a fixed :class:`SourceResponseEnvelope`.
    The lookup key is extracted from a query by the ``query_key``
    callable (default: ``query.gstin``). The transport records every
    query it received so tests can assert on the request side of the
    contract.
    """

    def __init__(
        self,
        responses: dict[str, SourceResponseEnvelope] | None = None,
        *,
        default_response: SourceResponseEnvelope | None = None,
        query_key: Any = None,
    ) -> None:
        self._responses: dict[str, SourceResponseEnvelope] = dict(responses or {})
        self._default = default_response
        self.queries: list[Any] = []
        # ``query_key`` is a callable (query) -> str. The default looks
        # up ``query.gstin``; tests for Udyam/PAN/MCA can supply a
        # different callable.
        self._query_key = query_key or (lambda q: q.gstin)

    def set(self, key: str, envelope: SourceResponseEnvelope) -> None:
        """Register a canned response for ``key``."""

        self._responses[key] = envelope

    def send_query(self, query: Any) -> SourceResponseEnvelope:
        self.queries.append(query)
        key = self._query_key(query)
        envelope = self._responses.get(key)
        if envelope is not None:
            return envelope
        if self._default is not None:
            return self._default
        # No canned response: surface this as a 404 so the parser can
        # map to NOT_FOUND deterministically.
        return SourceResponseEnvelope(
            status_code=404,
            raw_response=None,
            latency_ms=None,
            correlation_id=None,
        )


# Re-export for callers that want to do status mapping without
# importing the model module directly.
__all__ = [
    "GstQuery",
    "GstResponseEnvelope",
    "InProcessTransport",
    "SourceResponseEnvelope",
    "StaticTransport",
    "TransportError",
    "VerificationStatus",
    "VerificationTransport",
]
