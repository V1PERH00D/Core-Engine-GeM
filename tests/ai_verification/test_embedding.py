"""Tests for the embedding abstraction.

These tests cover the public surface of
:mod:`ai_verification.cross_bidder.embedding`:

* the ``EmbeddingProvider`` Protocol is duck-typed
* ``StaticEmbeddingProvider`` returns the configured vectors
* ``UnavailableEmbeddingProvider`` returns ``None`` deterministically
* ``cosine_similarity`` rejects malformed inputs (empty, dim mismatch,
  NaN, inf, zero vectors)
* the HTTPS-only adapter refuses non-HTTPS URLs and never opens the
  network when no opener is wired in
* the ``HttpEmbeddingAdapter`` uses the configurable timeout and
  injectable opener seam
"""

from __future__ import annotations

import math

import pytest

from ai_verification.cross_bidder.embedding import (
    EmbeddingEndpointConfig,
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingTransportError,
    EmbeddingValidationError,
    HttpEmbeddingAdapter,
    StaticEmbeddingProvider,
    StaticEmbeddingTransport,
    UnavailableEmbeddingProvider,
    cosine_similarity,
)


# ---------------------------------------------------------------------------
# cosine_similarity
# ---------------------------------------------------------------------------


def test_cosine_similarity_identical_vectors_returns_one() -> None:
    """Identical unit vectors produce cosine similarity of 1.0."""
    v = [0.6, 0.8, 0.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_returns_zero() -> None:
    """Orthogonal non-zero vectors produce cosine similarity of 0.0."""
    left = [1.0, 0.0, 0.0]
    right = [0.0, 1.0, 0.0]
    assert cosine_similarity(left, right) == pytest.approx(0.0)


def test_cosine_similarity_opposite_returns_zero_via_clamp() -> None:
    """Opposite vectors: dot product is negative; clamped to 0.0."""
    left = [1.0, 0.0, 0.0]
    right = [-1.0, 0.0, 0.0]
    assert cosine_similarity(left, right) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector_returns_zero_safely() -> None:
    """All-zero vector on either side must NOT divide by zero."""
    assert cosine_similarity([0.0, 0.0, 0.0], [1.0, 2.0, 3.0]) == 0.0
    assert cosine_similarity([1.0, 2.0, 3.0], [0.0, 0.0, 0.0]) == 0.0
    assert cosine_similarity([0.0, 0.0, 0.0], [0.0, 0.0, 0.0]) == 0.0


def test_cosine_similarity_rejects_empty_vectors() -> None:
    with pytest.raises(EmbeddingValidationError):
        cosine_similarity([], [1.0, 2.0])
    with pytest.raises(EmbeddingValidationError):
        cosine_similarity([1.0, 2.0], [])


def test_cosine_similarity_rejects_dimension_mismatch() -> None:
    with pytest.raises(EmbeddingValidationError):
        cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])


def test_cosine_similarity_rejects_nan_and_inf() -> None:
    nan = float("nan")
    inf = float("inf")
    with pytest.raises(EmbeddingValidationError):
        cosine_similarity([nan, 1.0], [1.0, 1.0])
    with pytest.raises(EmbeddingValidationError):
        cosine_similarity([1.0, 1.0], [nan, 1.0])
    with pytest.raises(EmbeddingValidationError):
        cosine_similarity([inf, 1.0], [1.0, 1.0])
    with pytest.raises(EmbeddingValidationError):
        cosine_similarity([1.0, 1.0], [-inf, 1.0])


def test_cosine_similarity_rejects_none() -> None:
    with pytest.raises(EmbeddingValidationError):
        cosine_similarity(None, [1.0, 2.0])  # type: ignore[arg-type]
    with pytest.raises(EmbeddingValidationError):
        cosine_similarity([1.0, 2.0], None)  # type: ignore[arg-type]


def test_cosine_similarity_clamps_floating_drift() -> None:
    """A result slightly above 1.0 from float error is clamped to 1.0."""
    a = [1.0, 1.0, 1.0]
    b = [1.0 + 1e-15, 1.0, 1.0]
    result = cosine_similarity(a, b)
    assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# UnavailableEmbeddingProvider
# ---------------------------------------------------------------------------


def test_unavailable_provider_returns_none_for_embed() -> None:
    provider = UnavailableEmbeddingProvider()
    assert provider.embed("any text") is None
    assert provider.embed("any text", model="any-model") is None


def test_unavailable_provider_returns_none_for_embed_request() -> None:
    provider = UnavailableEmbeddingProvider(model="x")
    req = EmbeddingRequest(text="hello", model=None, correlation_id="abc")
    assert provider.embed_request(req) is None
    # model_name still returns the configured model so the trace can
    # at least record what *would* have been used.
    assert provider.model_name() == "x"


def test_unavailable_provider_model_defaults_to_none() -> None:
    provider = UnavailableEmbeddingProvider()
    assert provider.model_name() is None


# ---------------------------------------------------------------------------
# StaticEmbeddingProvider
# ---------------------------------------------------------------------------


def test_static_provider_returns_configured_vector() -> None:
    provider = StaticEmbeddingProvider(
        model="unit-test",
        vectors={"hello": [0.1, 0.2, 0.3]},
    )
    out = provider.embed("hello")
    assert out == [0.1, 0.2, 0.3]
    # The returned list is a copy; mutating it must not affect the
    # provider's internal state.
    out.append(99.0)
    assert provider.embed("hello") == [0.1, 0.2, 0.3]


def test_static_provider_returns_none_for_unknown_text() -> None:
    provider = StaticEmbeddingProvider(model="unit-test", vectors={"a": [1.0]})
    assert provider.embed("missing") is None


def test_static_provider_embed_request_returns_response() -> None:
    provider = StaticEmbeddingProvider(
        model="unit-test", vectors={"hello": [1.0, 0.0]}
    )
    req = EmbeddingRequest(text="hello", model=None, correlation_id="cid-1")
    response = provider.embed_request(req)
    assert response is not None
    assert response.embedding == [1.0, 0.0]
    assert response.embedding_model == "unit-test"
    assert response.correlation_id == "cid-1"


def test_static_provider_embed_request_returns_none_when_missing() -> None:
    provider = StaticEmbeddingProvider(model="x", vectors={"a": [1.0]})
    req = EmbeddingRequest(text="b", model=None, correlation_id=None)
    assert provider.embed_request(req) is None


def test_static_provider_satisfies_protocol() -> None:
    """Duck-typed protocol check."""
    provider: EmbeddingProvider = StaticEmbeddingProvider(model="x")
    assert isinstance(provider, EmbeddingProvider)


def test_unavailable_provider_satisfies_protocol() -> None:
    provider: EmbeddingProvider = UnavailableEmbeddingProvider()
    assert isinstance(provider, EmbeddingProvider)


# ---------------------------------------------------------------------------
# HttpEmbeddingAdapter (production-shaped)
# ---------------------------------------------------------------------------


def test_http_adapter_rejects_non_https_url() -> None:
    config = EmbeddingEndpointConfig(url="http://example.com/embed")
    with pytest.raises(EmbeddingTransportError):
        HttpEmbeddingAdapter(config)


def test_http_adapter_rejects_non_https_url_with_http_explicitly() -> None:
    config = EmbeddingEndpointConfig(
        url="http://example.com/embed", timeout_seconds=2.0
    )
    with pytest.raises(EmbeddingTransportError):
        HttpEmbeddingAdapter(config)


def test_http_adapter_construction_accepts_https() -> None:
    config = EmbeddingEndpointConfig(
        url="https://example.com/embed",
        timeout_seconds=2.5,
        default_model="unit-test-model",
    )
    adapter = HttpEmbeddingAdapter(config)
    assert adapter.model_name() == "unit-test-model"


def test_http_adapter_embed_returns_none_when_no_opener() -> None:
    """Without an opener, embed() returns None deterministically."""
    config = EmbeddingEndpointConfig(
        url="https://example.com/embed", timeout_seconds=1.0
    )
    adapter = HttpEmbeddingAdapter(config)
    assert adapter.embed("hello world") is None


def test_http_adapter_embed_request_returns_none_when_no_opener() -> None:
    config = EmbeddingEndpointConfig(
        url="https://example.com/embed", timeout_seconds=1.0
    )
    adapter = HttpEmbeddingAdapter(config)
    req = EmbeddingRequest(text="hello", model=None, correlation_id=None)
    assert adapter.embed_request(req) is None


def test_http_adapter_uses_injected_opener() -> None:
    """An injected opener is invoked; the adapter parses its result."""
    captured = {}

    def fake_opener(*, url, body, headers, timeout):
        captured["url"] = url
        captured["body"] = body
        captured["headers"] = headers
        captured["timeout"] = timeout
        from ai_verification.cross_bidder.embedding import _HttpOpenerResult
        return _HttpOpenerResult(
            status=200,
            body={
                "embedding": [0.1, 0.2, 0.3],
                "embedding_model": "fake-model",
            },
        )

    config = EmbeddingEndpointConfig(
        url="https://example.com/embed",
        timeout_seconds=3.5,
        default_model="default-model",
    )
    adapter = HttpEmbeddingAdapter(config, opener=fake_opener)
    result = adapter.embed("hello world")
    assert result == [0.1, 0.2, 0.3]
    assert captured["url"] == "https://example.com/embed"
    assert captured["timeout"] == 3.5
    assert "Content-Type" in captured["headers"]


def test_http_adapter_propagates_opener_exception_as_unavailable() -> None:
    """An opener that raises must surface as ``None`` from embed()."""

    def broken_opener(*, url, body, headers, timeout):
        raise RuntimeError("network is unreachable")

    config = EmbeddingEndpointConfig(url="https://example.com/embed")
    adapter = HttpEmbeddingAdapter(config, opener=broken_opener)
    assert adapter.embed("hello") is None


def test_http_adapter_rejects_non_2xx_status() -> None:
    """A non-success response makes the adapter return ``None``."""
    from ai_verification.cross_bidder.embedding import _HttpOpenerResult

    def fail_opener(*, url, body, headers, timeout):
        return _HttpOpenerResult(status=500, body={"error": "boom"})

    config = EmbeddingEndpointConfig(url="https://example.com/embed")
    adapter = HttpEmbeddingAdapter(config, opener=fail_opener)
    assert adapter.embed("hello") is None


def test_http_adapter_rejects_malformed_body() -> None:
    """Missing keys in the upstream body produce ``None`` from embed()."""
    from ai_verification.cross_bidder.embedding import _HttpOpenerResult

    def bad_opener(*, url, body, headers, timeout):
        return _HttpOpenerResult(status=200, body={"embedding": [1.0]})

    config = EmbeddingEndpointConfig(url="https://example.com/embed")
    adapter = HttpEmbeddingAdapter(config, opener=bad_opener)
    assert adapter.embed("hello") is None


def test_http_adapter_rejects_invalid_vector() -> None:
    """An embedding containing NaN makes the adapter return ``None``."""
    from ai_verification.cross_bidder.embedding import _HttpOpenerResult

    def nan_opener(*, url, body, headers, timeout):
        return _HttpOpenerResult(
            status=200,
            body={
                "embedding": [1.0, float("nan"), 0.5],
                "embedding_model": "m",
            },
        )

    config = EmbeddingEndpointConfig(url="https://example.com/embed")
    adapter = HttpEmbeddingAdapter(config, opener=nan_opener)
    assert adapter.embed("hello") is None


# ---------------------------------------------------------------------------
# StaticEmbeddingTransport
# ---------------------------------------------------------------------------


def test_static_transport_returns_configured_response() -> None:
    transport = StaticEmbeddingTransport(
        responses={
            "hello": EmbeddingResponse(
                embedding=[0.5, 0.5], embedding_model="m"
            )
        }
    )
    req = EmbeddingRequest(text="hello", model=None, correlation_id=None)
    response = transport.send(req)
    assert response.embedding == [0.5, 0.5]
    assert response.embedding_model == "m"
    assert transport.requests == [req]


def test_static_transport_falls_back_to_default() -> None:
    fallback = EmbeddingResponse(embedding=[1.0], embedding_model="default")
    transport = StaticEmbeddingTransport(default_response=fallback)
    req = EmbeddingRequest(text="missing", model=None, correlation_id=None)
    assert transport.send(req) is fallback


def test_static_transport_prefers_correlation_id_key() -> None:
    by_text = EmbeddingResponse(embedding=[0.0], embedding_model="text")
    by_cid = EmbeddingResponse(embedding=[9.0], embedding_model="cid")
    transport = StaticEmbeddingTransport(
        responses={"hello": by_text, "cid-1": by_cid}
    )
    req = EmbeddingRequest(text="hello", model=None, correlation_id="cid-1")
    assert transport.send(req) is by_cid


def test_static_transport_raises_when_unmapped() -> None:
    transport = StaticEmbeddingTransport()
    req = EmbeddingRequest(text="nope", model=None, correlation_id=None)
    with pytest.raises(EmbeddingTransportError):
        transport.send(req)
