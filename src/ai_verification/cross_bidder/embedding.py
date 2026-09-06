"""Semantic embedding abstraction for cross-bidder document comparison.

What "semantic" means here
--------------------------
The EXACT, NORMALIZED and LEXICAL layers are deterministic, locally
computed character / byte / hash operations. They require no external
service.

The SEMANTIC layer compares *normalized text* embeddings obtained from an
externally supplied embedding service. Embedding vectors are produced by
a deterministic, dependency-injected ``EmbeddingProvider`` whose exact
implementation is owned by the production environment, **not** by this
package. This module defines:

* :class:`EmbeddingProvider` -- the narrow, typed interface every
  embedding implementation must satisfy. It is intentionally small
  enough to be faked in unit tests and large enough to expose the
  metadata required by :class:`SimilarityTrace`.
* :class:`EmbeddingRequest` / :class:`EmbeddingResponse` -- the typed
  request / response boundary. The response carries an ``embedding_model``
  string so the detector can populate
  :attr:`SimilarityTrace.embedding_model`.
* :class:`EmbeddingTransport` -- the HTTPS-only transport seam. Mirrors
  the pattern established by
  :mod:`compliance_engine.verification.gst_http_transport`: the
  protocol is HTTP-shaped, the real client is HTTPS-only with an
  explicit timeout, and the test transport is deterministic.
* :class:`HttpEmbeddingAdapter` -- production-shaped adapter. It does
  not embed any commercial API key; it expects an
  :class:`EmbeddingEndpointConfig` injected at construction time.
* :class:`UnavailableEmbeddingProvider` -- default provider used when
  no real embedding service has been wired in. It never fabricates a
  similarity score: it returns ``None`` for both ``embed`` and
  ``embed_request``. The detector treats ``None`` as "semantic layer
  unavailable", which is distinct in the trace from "low similarity".

What semantic detection does **not** claim
------------------------------------------
* It is **not** a paraphrase detector. Two documents may carry
  semantically equivalent vectors while having different factual content
  (and vice versa).
* It is **not** a fraud / eligibility decision. The flag is
  ``CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE``, identical to the LEXICAL
  flag, and inherits its ``MEDIUM`` severity.
* It is **not** a substitute for exact / normalized reuse detection.
  Exact byte reuse (``CROSS_BIDDER_DOCUMENT_REUSED``) is strictly
  stronger than any embedding-derived similarity, because it has no
  false-positive surface from vector quantization or model drift.
* It does **not** silently map provider failure to a low similarity
  score. The trace distinguishes "semantic layer unavailable" from
  "semantic similarity below threshold".

How provider failure is represented
-----------------------------------
* A provider that raises :class:`EmbeddingValidationError` or returns
  ``None`` is recorded in :class:`SimilarityTrace` with
  ``layer = SimilarityLayer.UNKNOWN`` and ``embedding_model = None``
  (or the configured ``model`` string if explicitly set). The
  ``similarity_score`` is ``0.0``; the audit reader can detect the
  unavailable state because ``embedding_model`` is unset and no
  SEMANTIC layer was emitted.
* A provider that returns a malformed vector (wrong dimension,
  empty, NaN, inf, all zeros) raises :class:`EmbeddingValidationError`.
  The detector catches this and treats the layer as unavailable.

Why semantic detection is weaker than exact / normalized reuse
--------------------------------------------------------------
* Exact byte reuse is a one-shot cryptographic comparison; it has no
  embedding drift, no quantization error, and no model-version
  dependency.
* Normalized-text reuse is the same comparison run on deterministic
  whitespace / OCR noise removal.
* Semantic similarity is a *function* of an opaque, externally
  trained model. Two semantically equivalent but textually distinct
  documents produce a high score; two textually distinct documents
  that happen to share a model blind spot can produce an
  artificially low score.
* Therefore the SEMANTIC layer is only consulted when EXACT,
  NORMALIZED and LEXICAL have already failed to establish a stronger
  reuse condition. It is the weakest layer that can still raise
  ``CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Protocol, Sequence, runtime_checkable
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class EmbeddingEndpointConfig(BaseModel):
    """Configuration for the (future) embedding HTTP endpoint.

    The fields are intentionally minimal: ``url``, ``timeout_seconds``
    and an optional ``default_model``. The adapter refuses to start
    against a non-HTTPS URL so production wiring is forced through the
    safe path.

    No credentials live in this config. Authentication is supplied as
    an injectable ``headers`` callable at construction.
    """

    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., description="HTTPS endpoint for embedding requests.")
    timeout_seconds: float = Field(
        default=10.0,
        ge=0.0,
        le=120.0,
        description="Hard HTTP timeout for a single embedding request.",
    )
    default_model: str | None = Field(
        default=None,
        description="Default model name; may be overridden per request.",
    )


# ---------------------------------------------------------------------------
# Typed request / response
# ---------------------------------------------------------------------------


class EmbeddingRequest(BaseModel):
    """Typed request envelope for an embedding service.

    The interface is intentionally vendor-neutral. The provider that
    actually serialises this into the wire format is injected via the
    :class:`HttpEmbeddingAdapter`.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, description="Text to embed.")
    model: str | None = Field(
        default=None,
        description="Optional model name; falls back to provider default.",
    )
    correlation_id: str | None = Field(
        default=None,
        description="Optional end-to-end correlation id.",
    )


class EmbeddingResponse(BaseModel):
    """Typed response envelope from an embedding service.

    ``embedding_model`` is mandatory on success: the detector uses it to
    populate :attr:`SimilarityTrace.embedding_model`.
    """

    model_config = ConfigDict(extra="forbid")

    embedding: list[float] = Field(
        ...,
        description="Dense embedding vector (floating point).",
    )
    embedding_model: str = Field(
        ...,
        description="Identifier of the model that produced the embedding.",
    )
    correlation_id: str | None = Field(
        default=None,
        description="Echoed correlation id, if one was supplied.",
    )


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class EmbeddingValidationError(ValueError):
    """Raised when an embedding is malformed.

    The detector catches this and represents the layer as
    ``SimilarityLayer.UNKNOWN`` with no fabricated similarity score.
    """


class EmbeddingTransportError(RuntimeError):
    """Raised when the embedding transport cannot complete the request.

    The detector catches this and represents the layer as unavailable.
    """


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Pluggable embedding provider.

    The detector consumes this interface exclusively. Implementations
    must be deterministic at the interface level for the same input
    text and model identifier. Returning ``None`` from ``embed`` means
    "the semantic layer is unavailable for this document", **not**
    "the document is semantically empty".
    """

    model: str | None

    def embed(
        self, text: str, *, model: str | None = None
    ) -> Sequence[float] | None:
        """Return the embedding for ``text``.

        Returns ``None`` if the embedding is unavailable for any
        reason (no model wired in, upstream provider returned an
        empty vector, transport failure). Implementations must NOT
        return a fabricated zero vector or a constant vector in
        place of a real embedding.
        """
        ...

    def embed_request(self, request: EmbeddingRequest) -> EmbeddingResponse | None:
        """Typed variant. Returns ``None`` when unavailable."""
        ...

    def model_name(self) -> str | None:
        """Return the configured model name, or ``None`` if absent."""
        ...


# ---------------------------------------------------------------------------
# Numerics: cosine similarity with safety checks
# ---------------------------------------------------------------------------


def _is_finite_scalar(x: float) -> bool:
    """Return ``True`` if ``x`` is a finite real number (no NaN, no inf)."""
    # ``math.isfinite`` raises TypeError for non-numbers; we pre-check.
    return (
        isinstance(x, (int, float))
        and not isinstance(x, bool)
        and math.isfinite(float(x))
    )


def cosine_similarity(
    left: Sequence[float], right: Sequence[float]
) -> float:
    """Compute cosine similarity between two vectors.

    The function rejects, with :class:`EmbeddingValidationError`:

    * empty vectors
    * dimension mismatch
    * NaN / infinite values on either side
    * all-zero vectors (returns ``0.0`` deterministically)

    On success the return value is in the closed interval ``[0.0, 1.0]``
    after clamping negative components of the dot product (which arise
    from numerical drift) and values slightly above 1.0 (which arise
    from floating-point error) to the interval endpoints.
    """
    if left is None or right is None:
        raise EmbeddingValidationError("cosine_similarity received None")
    if not isinstance(left, (list, tuple)) or not isinstance(right, (list, tuple)):
        raise EmbeddingValidationError(
            "cosine_similarity requires list/tuple inputs"
        )
    if len(left) == 0 or len(right) == 0:
        raise EmbeddingValidationError("cosine_similarity received empty vector")
    if len(left) != len(right):
        raise EmbeddingValidationError(
            f"cosine_similarity dimension mismatch: {len(left)} vs {len(right)}"
        )

    dot = 0.0
    left_sq = 0.0
    right_sq = 0.0
    for lv, rv in zip(left, right):
        if not _is_finite_scalar(lv):
            raise EmbeddingValidationError(
                f"cosine_similarity: left vector contains non-finite value {lv!r}"
            )
        if not _is_finite_scalar(rv):
            raise EmbeddingValidationError(
                f"cosine_similarity: right vector contains non-finite value {rv!r}"
            )
        flv = float(lv)
        frv = float(rv)
        dot += flv * frv
        left_sq += flv * flv
        right_sq += frv * frv

    if left_sq == 0.0 or right_sq == 0.0:
        # Zero vector: cannot divide. Return 0.0 explicitly and safely.
        return 0.0

    magnitude = math.sqrt(left_sq) * math.sqrt(right_sq)
    if magnitude == 0.0:
        return 0.0

    raw = dot / magnitude
    if not math.isfinite(raw):
        raise EmbeddingValidationError(
            f"cosine_similarity: non-finite result {raw!r}"
        )

    # Clamp to [0.0, 1.0]. Negative values arise from numerical drift;
    # values above 1.0 arise from floating-point error. Both are
    # treated as exact endpoints.
    if raw < 0.0:
        return 0.0
    if raw > 1.0:
        return 1.0
    return raw


# ---------------------------------------------------------------------------
# Default unavailable provider
# ---------------------------------------------------------------------------


class UnavailableEmbeddingProvider:
    """Embedding provider used when no real service is wired in.

    Behaves deterministically: every call returns ``None``. The
    detector treats that as "semantic layer unavailable", which is
    distinguishable in the trace from "low similarity".
    """

    def __init__(self, model: str | None = None) -> None:
        self.model = model

    def embed(
        self, text: str, *, model: str | None = None
    ) -> Sequence[float] | None:
        return None

    def embed_request(
        self, request: EmbeddingRequest
    ) -> EmbeddingResponse | None:
        return None

    def model_name(self) -> str | None:
        return self.model


# ---------------------------------------------------------------------------
# Static provider for tests / offline operation
# ---------------------------------------------------------------------------


class StaticEmbeddingProvider:
    """Deterministic in-memory provider used by tests.

    Maps ``text`` to a pre-recorded vector. If no mapping is found for
    ``text``, returns ``None`` -- never a fabricated score.

    The provider exposes the model identifier through ``model_name`` so
    the detector can populate :class:`SimilarityTrace.embedding_model`
    in tests.
    """

    def __init__(
        self,
        *,
        model: str,
        vectors: dict[str, Sequence[float]] | None = None,
    ) -> None:
        self.model = model
        self._vectors: dict[str, Sequence[float]] = dict(vectors or {})

    def set(self, text: str, vector: Sequence[float]) -> None:
        self._vectors[text] = list(vector)

    def embed(
        self, text: str, *, model: str | None = None
    ) -> Sequence[float] | None:
        if text in self._vectors:
            return list(self._vectors[text])
        return None

    def embed_request(
        self, request: EmbeddingRequest
    ) -> EmbeddingResponse | None:
        vector = self.embed(request.text, model=request.model)
        if vector is None:
            return None
        return EmbeddingResponse(
            embedding=list(vector),
            embedding_model=self.model_name(),
            correlation_id=request.correlation_id,
        )

    def model_name(self) -> str | None:
        return self.model


# ---------------------------------------------------------------------------
# Transport seam
# ---------------------------------------------------------------------------


@runtime_checkable
class EmbeddingTransport(Protocol):
    """Pluggable transport for embedding HTTP requests.

    Mirrors :class:`compliance_engine.verification.transport.VerificationTransport`
    but is shaped around embedding requests. The default production
    client is :class:`HttpEmbeddingAdapter`; tests use
    :class:`StaticEmbeddingTransport`.
    """

    def send(self, request: EmbeddingRequest) -> EmbeddingResponse:
        ...


class StaticEmbeddingTransport:
    """Deterministic transport used in tests.

    Maps ``request.text`` (or, if set, ``request.correlation_id``) to
    a canned :class:`EmbeddingResponse`. Records every request so
    tests can assert on the request side of the contract.
    """

    def __init__(
        self,
        responses: dict[str, EmbeddingResponse] | None = None,
        *,
        default_response: EmbeddingResponse | None = None,
    ) -> None:
        self._responses: dict[str, EmbeddingResponse] = dict(responses or {})
        self._default = default_response
        self.requests: list[EmbeddingRequest] = []

    def set(self, key: str, response: EmbeddingResponse) -> None:
        self._responses[key] = response

    def send(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.requests.append(request)
        if request.correlation_id and request.correlation_id in self._responses:
            return self._responses[request.correlation_id]
        if request.text in self._responses:
            return self._responses[request.text]
        if self._default is not None:
            return self._default
        raise EmbeddingTransportError(
            f"StaticEmbeddingTransport: no canned response for {request.text!r}"
        )


# ---------------------------------------------------------------------------
# HTTPS-only production-shaped adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _HttpOpenerResult:
    """Result envelope returned by an opener callable."""

    status: int
    body: dict


def _noop_opener(
    *,
    url: str,
    body: bytes,
    headers: dict,
    timeout: float,
) -> _HttpOpenerResult:
    """Default opener that refuses to operate; never opens a network."""

    raise EmbeddingTransportError(
        "HttpEmbeddingAdapter has no opener wired in. "
        "Inject an opener callable for tests, or wire a real HTTPS "
        "client in production after supplying an EmbeddingEndpointConfig."
    )


class HttpEmbeddingAdapter:
    """Production-shaped HTTPS embedding adapter.

    The adapter is shaped exactly like
    :class:`compliance_engine.verification.gst_http_transport.GstHttpClient`:
    it refuses any URL whose scheme is not ``https``, requires an
    explicit ``timeout_seconds``, and exposes the network seam as an
    injectable ``opener`` callable so tests can swap it.

    The adapter holds no credentials and never opens the network unless
    an opener is explicitly provided. Calling ``embed`` without an
    opener wired in returns ``None`` and never raises -- the contract
    for the detector is that failure is represented as "unavailable".
    """

    def __init__(
        self,
        config: EmbeddingEndpointConfig,
        *,
        opener: Optional[object] = None,
        headers_provider: Optional[object] = None,
    ) -> None:
        self._config = config
        # Fail fast on non-HTTPS URLs. Production integration MUST supply
        # an HTTPS endpoint; this is intentional.
        parsed = urlparse(config.url)
        if parsed.scheme.lower() != "https":
            raise EmbeddingTransportError(
                "HttpEmbeddingAdapter requires an HTTPS endpoint URL; "
                f"got scheme={parsed.scheme!r}"
            )
        self._opener = opener or _noop_opener
        self._headers_provider = headers_provider or (lambda: {})

    @property
    def model(self) -> str | None:
        return self._config.default_model

    def model_name(self) -> str | None:
        return self._config.default_model

    def _send(self, request: EmbeddingRequest) -> EmbeddingResponse:
        body = {
            "text": request.text,
            "model": request.model or self._config.default_model,
        }
        if request.correlation_id is not None:
            body["correlation_id"] = request.correlation_id
        headers = self._headers_provider() or {}
        headers.setdefault("Content-Type", "application/json")
        headers.setdefault("Accept", "application/json")
        try:
            import json

            result = self._opener(
                url=self._config.url,
                body=json.dumps(body).encode("utf-8"),
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
        except EmbeddingTransportError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingTransportError(
                "HttpEmbeddingAdapter transport call failed: "
                + repr(exc)
            ) from exc

        status = int(getattr(result, "status", 0))
        body_dict = getattr(result, "body", None) or {}
        if status < 200 or status >= 300:
            raise EmbeddingTransportError(
                f"HttpEmbeddingAdapter: upstream returned status {status}"
            )
        if not isinstance(body_dict, dict):
            raise EmbeddingTransportError(
                "HttpEmbeddingAdapter: upstream body is not a JSON object"
            )
        try:
            embedding = body_dict["embedding"]
            embedding_model = body_dict["embedding_model"]
        except KeyError as exc:
            raise EmbeddingTransportError(
                f"HttpEmbeddingAdapter: upstream missing key {exc.args[0]!r}"
            ) from exc
        return EmbeddingResponse(
            embedding=list(embedding),
            embedding_model=str(embedding_model),
            correlation_id=request.correlation_id,
        )

    def embed(
        self, text: str, *, model: str | None = None
    ) -> Sequence[float] | None:
        if not text:
            return None
        request = EmbeddingRequest(
            text=text, model=model, correlation_id=None
        )
        try:
            response = self._send(request)
        except EmbeddingTransportError:
            return None
        # Validate the response vector before returning.
        try:
            self._validate_vector(response.embedding)
        except EmbeddingValidationError:
            return None
        return list(response.embedding)

    def embed_request(
        self, request: EmbeddingRequest
    ) -> EmbeddingResponse | None:
        try:
            response = self._send(request)
        except EmbeddingTransportError:
            return None
        try:
            self._validate_vector(response.embedding)
        except EmbeddingValidationError:
            return None
        return response

    @staticmethod
    def _validate_vector(vector: Sequence[float]) -> None:
        """Validate the vector shape; raise on malformed data."""
        if vector is None:
            raise EmbeddingValidationError("embedding is None")
        if len(vector) == 0:
            raise EmbeddingValidationError("embedding is empty")
        for value in vector:
            if not _is_finite_scalar(value):
                raise EmbeddingValidationError(
                    f"embedding contains non-finite value {value!r}"
                )


__all__ = [
    "EmbeddingEndpointConfig",
    "EmbeddingProvider",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "EmbeddingTransport",
    "EmbeddingTransportError",
    "EmbeddingValidationError",
    "HttpEmbeddingAdapter",
    "StaticEmbeddingProvider",
    "StaticEmbeddingTransport",
    "UnavailableEmbeddingProvider",
    "cosine_similarity",
]