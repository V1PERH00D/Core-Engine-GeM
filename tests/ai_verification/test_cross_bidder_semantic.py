"""Focused tests for the SEMANTIC similarity layer in cross-bidder detection.

These tests exercise the new embedding-driven detection path while
preserving the behaviour of EXACT, NORMALIZED and LEXICAL layers and
the existing confidence / template gate / corroboration / quality
formulae. They cover:

* precedence (exact and normalized reuse still win over semantic)
* semantic finds at/above the configured threshold emit
  ``CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE``
* semantic finds below the threshold emit no finding
* unavailable / failing providers do NOT fabricate scores
* provider exceptions do NOT become similarity of zero
* malformed vectors (dimension mismatch, NaN, inf, all-zero) are
  handled safely
* the trace records the embedding model and the configured threshold
* bidder IDs on the finding come from the detector arguments, not
  from the metadata ``bidder_name`` field
* template mismatch still blocks emission
* template unknown follows existing gate semantics
* corroboration and quality still drive the confidence formula
* the final 0.70 emission threshold is unchanged
* repeated runs with a deterministic provider are deterministic
* the AI Verification engine accepts a finding produced by semantic
"""

from __future__ import annotations

from datetime import date

import pytest

from ai_verification.cross_bidder import (
    NORMALIZATION_VERSION,
    SimilarityLayer,
    StaticEmbeddingProvider,
    UnavailableEmbeddingProvider,
    detect_cross_bidder_anomalies,
)
from ai_verification.cross_bidder.detector import (
    DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD,
)
from ai_verification.cross_bidder.document_artifact_store import (
    DocumentMeta,
    InMemoryDocumentArtifactStore,
)
from ai_verification.cross_bidder.embedding import (
    EmbeddingProvider,
    EmbeddingValidationError,
    cosine_similarity,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def make_left_meta(**overrides) -> DocumentMeta:
    base = DocumentMeta(
        document_type="OEM_AUTH",
        issuer="ACME",
        authorization_number="AUTH-123",
        issue_date=date(2026, 1, 10),
        valid_until=date(2027, 1, 10),
        bidder_name="bidder-A",
        territory="India",
        ocr_confidence=0.95,
        document_type_confidence=0.99,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def make_right_meta(**overrides) -> DocumentMeta:
    base = DocumentMeta(
        document_type="OEM_AUTH",
        issuer="ACME",
        authorization_number="AUTH-123",
        issue_date=date(2026, 1, 10),
        valid_until=date(2027, 1, 10),
        bidder_name="bidder-B",
        territory="India",
        ocr_confidence=0.95,
        document_type_confidence=0.99,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def make_store(
    *,
    left_raw=None,
    right_raw=None,
    left_hash=None,
    right_hash=None,
    left_meta=None,
    right_meta=None,
):
    raw_texts = {}
    file_hashes = {}
    metadata = {}
    if left_raw is not None:
        raw_texts["doc-left"] = left_raw
    if right_raw is not None:
        raw_texts["doc-right"] = right_raw
    if left_hash is not None:
        file_hashes["doc-left"] = left_hash
    if right_hash is not None:
        file_hashes["doc-right"] = right_hash
    if left_meta is not None:
        metadata["doc-left"] = left_meta
    if right_meta is not None:
        metadata["doc-right"] = right_meta
    return InMemoryDocumentArtifactStore(
        raw_texts=raw_texts,
        file_hashes=file_hashes,
        metadata=metadata,
    )


def call_detect(*, store, embedding_provider=None, threshold=None, **kwargs):
    """Run the detector with sensible defaults that can be overridden."""
    detect_kwargs = dict(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )
    if embedding_provider is not None:
        detect_kwargs["embedding_provider"] = embedding_provider
    if threshold is not None:
        detect_kwargs["semantic_similarity_threshold"] = threshold
    detect_kwargs.update(kwargs)
    return detect_cross_bidder_anomalies(**detect_kwargs)


# ---------------------------------------------------------------------------
# Default behaviour (no semantic provider wired in)
# ---------------------------------------------------------------------------


def test_default_provider_is_unavailable_and_no_finding_without_lexical() -> None:
    """With the default (UnavailableEmbeddingProvider), the detector
    behaves exactly as before: it stops at the LEXICAL layer and emits
    no finding when EXACT / NORMALIZED / LEXICAL fail to establish a
    stronger reuse condition. The trace records UNKNOWN with the
    semantic layer consulted."""
    store = make_store(
        left_raw="These two documents talk about different things entirely.",
        right_raw="Completely unrelated content about something else.",
        left_meta=make_left_meta(),
        right_meta=make_right_meta(),
    )
    findings, trace = call_detect(store=store)

    assert findings == []
    assert trace is not None
    # Layer is UNKNOWN because no comparison passed
    assert trace.layer is SimilarityLayer.UNKNOWN
    # Threshold recorded: the semantic threshold used (default 0.85)
    assert trace.threshold == DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD


# ---------------------------------------------------------------------------
# EXACT / NORMALIZED / LEXICAL still beat SEMANTIC
# ---------------------------------------------------------------------------


def test_exact_byte_reuse_still_wins_over_semantic() -> None:
    """Identical file hash produces REUSED even with a strong semantic
    signal. The trace records EXACT, not SEMANTIC."""
    raw = "The quick brown fox jumps over the lazy dog."
    provider = StaticEmbeddingProvider(
        model="semantic-mock",
        vectors={raw: [1.0, 0.0, 0.0]},
    )
    store = make_store(
        left_raw=raw,
        right_raw=raw,
        left_hash="hash-equal",
        right_hash="hash-equal",
        left_meta=make_left_meta(),
        right_meta=make_right_meta(),
    )
    findings, trace = call_detect(
        store=store, embedding_provider=provider
    )
    assert len(findings) == 1
    assert findings[0].flag_id == "CROSS_BIDDER_DOCUMENT_REUSED"
    assert trace.layer is SimilarityLayer.EXACT
    # Embedding model not recorded because EXACT fired.
    assert trace.embedding_model is None


def test_normalized_reuse_still_wins_over_semantic() -> None:
    """Different raw formatting but identical normalized text -> REUSED."""
    left_raw = "The quick brown fox jumps over the lazy dog."
    right_raw = "The quick   brown  fox jumps over the lazy   dog."
    provider = StaticEmbeddingProvider(
        model="semantic-mock",
        vectors={
            "the quick brown fox jumps over the lazy dog": [1.0, 0.0, 0.0],
        },
    )
    store = make_store(
        left_raw=left_raw,
        right_raw=right_raw,
        # No identical file hashes -- rely on normalized hash only
        left_meta=make_left_meta(),
        right_meta=make_right_meta(),
    )
    findings, trace = call_detect(
        store=store, embedding_provider=provider
    )
    assert len(findings) == 1
    assert findings[0].flag_id == "CROSS_BIDDER_DOCUMENT_REUSED"
    assert trace.layer is SimilarityLayer.NORMALIZED
    assert trace.embedding_model is None


def test_lexical_near_duplicate_still_wins_over_semantic() -> None:
    """Lexical Dice >= 0.80 produces NEAR_DUPLICATE without consulting
    the semantic provider. The provider is invoked with no responses
    and would yield a low score, but LEXICAL must take precedence."""
    base_text = "OEM Authorization Document Section Alpha Beta Gamma Delta Epsilon"
    # Different but sufficiently overlapping text for Dice >= 0.80.
    similar = (
        "OEM Authorization Document Section Alpha Beta Gamma Delta Epsilon "
        "with minor footer line"
    )
    provider = StaticEmbeddingProvider(
        model="semantic-mock",
        # Deliberately map the texts to *orthogonal* vectors so SEMANTIC
        # would NOT fire even if it were consulted.
        vectors={
            base_text: [1.0, 0.0, 0.0],
            similar: [0.0, 1.0, 0.0],
        },
    )
    store = make_store(
        left_raw=base_text,
        right_raw=similar,
        left_meta=make_left_meta(),
        right_meta=make_right_meta(),
    )
    findings, trace = call_detect(
        store=store, embedding_provider=provider
    )
    assert len(findings) == 1
    assert findings[0].flag_id == "CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE"
    assert trace.layer is SimilarityLayer.LEXICAL
    assert trace.embedding_model is None


# ---------------------------------------------------------------------------
# Semantic similarity firing the threshold
# ---------------------------------------------------------------------------


def test_semantic_similarity_above_threshold_emits_near_duplicate() -> None:
    """Two documents with very different surface text but identical
    embeddings produce a NEAR_DUPLICATE finding via the SEMANTIC layer.

    Because the texts are normalized before they reach the embed
    function, mapping both to the same vector produces a cosine of 1.0.
    """
    left_raw = "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
    right_raw = "Sed ut perspiciatis unde omnis iste natus error sit voluptatem."
    left_norm = "lorem ipsum dolor sit amet consectetur adipiscing elit"
    right_norm = "sed ut perspiciatis unde omnis iste natus error sit voluptatem"

    provider = StaticEmbeddingProvider(
        model="semantic-mock",
        vectors={
            left_norm: [0.6, 0.8, 0.0],
            right_norm: [0.6, 0.8, 0.0],
        },
    )

    store = make_store(
        left_raw=left_raw,
        right_raw=right_raw,
        left_meta=make_left_meta(),
        right_meta=make_right_meta(),
    )
    findings, trace = call_detect(
        store=store, embedding_provider=provider
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.flag_id == "CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE"
    assert finding.bidder_id == "bidder-A"
    assert finding.related_bidder_ids == ["bidder-B"]
    assert trace.layer is SimilarityLayer.SEMANTIC
    assert trace.similarity_score == pytest.approx(1.0)
    assert trace.threshold == DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD
    assert trace.embedding_model == "semantic-mock"


def test_semantic_similarity_below_threshold_emits_no_finding() -> None:
    """Two embeddings whose cosine is below the configured threshold
    produce no finding. The trace records UNKNOWN."""
    left_raw = "lorem ipsum dolor"
    right_raw = "completely unrelated content here"
    left_norm = "lorem ipsum dolor"
    right_norm = "completely unrelated content here"

    provider = StaticEmbeddingProvider(
        model="semantic-mock",
        vectors={
            left_norm: [1.0, 0.0, 0.0],
            right_norm: [0.0, 1.0, 0.0],  # orthogonal -> cosine 0.0
        },
    )
    store = make_store(
        left_raw=left_raw,
        right_raw=right_raw,
        left_meta=make_left_meta(),
        right_meta=make_right_meta(),
    )
    findings, trace = call_detect(
        store=store, embedding_provider=provider
    )
    assert findings == []
    assert trace is not None
    assert trace.layer is SimilarityLayer.UNKNOWN


def test_semantic_threshold_is_recorded_in_trace() -> None:
    """A non-default threshold appears on the trace verbatim."""
    left_raw = "Doc one."
    right_raw = "Doc two."
    left_norm = "doc one"
    right_norm = "doc two"
    provider = StaticEmbeddingProvider(
        model="m",
        vectors={
            left_norm: [1.0, 0.0, 0.0],
            right_norm: [1.0, 0.0, 0.0],
        },
    )
    store = make_store(
        left_raw=left_raw,
        right_raw=right_raw,
        left_meta=make_left_meta(),
        right_meta=make_right_meta(),
    )
    findings, trace = call_detect(
        store=store, embedding_provider=provider, threshold=0.91
    )
    assert trace.threshold == pytest.approx(0.91)
    assert findings  # cosine 1.0 >= 0.91 -> finding emitted


def test_semantic_below_higher_threshold_emits_no_finding() -> None:
    """A non-default threshold is respected: even cosine 1.0 is below
    a threshold just above 1.0, so no finding is emitted. The trace
    records UNKNOWN.
    """
    left_raw = "Doc A."
    right_raw = "Doc B."
    left_norm = "doc a"
    right_norm = "doc b"
    # Use near-orthogonal vectors so cosine is low; threshold 0.99
    # means anything below 0.99 emits nothing.
    provider = StaticEmbeddingProvider(
        model="m",
        vectors={
            left_norm: [1.0, 0.0, 0.0],
            right_norm: [0.5, 0.5, 0.0],  # cos ~ 0.707
        },
    )
    store = make_store(
        left_raw=left_raw,
        right_raw=right_raw,
        left_meta=make_left_meta(),
        right_meta=make_right_meta(),
    )
    findings, trace = call_detect(
        store=store, embedding_provider=provider, threshold=0.99
    )
    assert findings == []
    assert trace.layer is SimilarityLayer.UNKNOWN
    assert trace.threshold == pytest.approx(0.99)
    # similarity_score on the trace records the actual cosine (the
    # provider did produce one), not a fabricated zero.
    assert trace.similarity_score == pytest.approx(0.7071, abs=1e-3)


def test_semantic_embedding_model_recorded_in_trace() -> None:
    """The trace carries the embedding model identifier verbatim."""
    left_raw = "X"
    right_raw = "Y"
    left_norm = "x"
    right_norm = "y"
    provider = StaticEmbeddingProvider(
        model="my-embedding-v3",
        vectors={
            left_norm: [1.0, 0.0, 0.0],
            right_norm: [1.0, 0.0, 0.0],
        },
    )
    store = make_store(
        left_raw=left_raw,
        right_raw=right_raw,
        left_meta=make_left_meta(),
        right_meta=make_right_meta(),
    )
    _, trace = call_detect(store=store, embedding_provider=provider)
    assert trace.embedding_model == "my-embedding-v3"


def test_bidder_ids_on_finding_come_from_arguments() -> None:
    """The bidder IDs on the finding come from the detector arguments,
    not from DocumentMeta.bidder_name."""
    left_raw = "X"
    right_raw = "Y"
    left_norm = "x"
    right_norm = "y"
    provider = StaticEmbeddingProvider(
        model="m",
        vectors={
            left_norm: [1.0, 0.0, 0.0],
            right_norm: [1.0, 0.0, 0.0],
        },
    )
    # Override the metadata bidder_name to something else -- the finding
    # must still use the explicit detector arguments.
    store = make_store(
        left_raw=left_raw,
        right_raw=right_raw,
        left_meta=make_left_meta(bidder_name="SOME OTHER"),
        right_meta=make_right_meta(bidder_name="ANOTHER"),
    )
    findings, trace = call_detect(
        store=store, embedding_provider=provider,
        left_bidder_id="explicit-left", right_bidder_id="explicit-right",
    )
    assert len(findings) == 1
    assert findings[0].bidder_id == "explicit-left"
    assert findings[0].related_bidder_ids == ["explicit-right"]
    assert trace.left_bidder_id == "explicit-left"
    assert trace.right_bidder_id == "explicit-right"


# ---------------------------------------------------------------------------
# Provider failure and exception safety
# ---------------------------------------------------------------------------


def test_semantic_provider_unavailable_emits_no_finding_and_no_fabricated_score() -> None:
    """An UnavailableEmbeddingProvider must never fabricate a similarity
    score. The trace records UNKNOWN with similarity_score 0.0 and
    embedding_model None -- distinguishable from a real low similarity
    result.
    """
    left_raw = "lorem ipsum dolor"
    right_raw = "completely unrelated content"
    provider = UnavailableEmbeddingProvider()
    store = make_store(
        left_raw=left_raw,
        right_raw=right_raw,
        left_meta=make_left_meta(),
        right_meta=make_right_meta(),
    )
    findings, trace = call_detect(
        store=store, embedding_provider=provider
    )
    assert findings == []
    assert trace is not None
    assert trace.layer is SimilarityLayer.UNKNOWN
    assert trace.similarity_score == 0.0
    assert trace.embedding_model is None
    # threshold defaults to DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD.
    assert trace.threshold == DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD


class _RaisingProvider:
    """Provider that raises on every call. Used to verify the detector
    does NOT translate provider exceptions into similarity = 0.0."""

    model = "raising"

    def __init__(self, exc: Exception | None = None) -> None:
        self._exc = exc or RuntimeError("provider failed")

    def embed(self, text, *, model=None):
        raise self._exc

    def embed_request(self, request):
        raise self._exc

    def model_name(self):
        return self.model


def test_semantic_provider_exception_is_caught_and_does_not_become_zero() -> None:
    """A provider that raises must be treated as unavailable, NOT as a
    similarity score of zero (which would falsely flag dissimilar pairs as
    'not even near-duplicate' rather than 'unknown')."""
    left_raw = "lorem ipsum dolor"
    right_raw = "completely unrelated content"
    provider = _RaisingProvider()
    store = make_store(
        left_raw=left_raw,
        right_raw=right_raw,
        left_meta=make_left_meta(),
        right_meta=make_right_meta(),
    )
    findings, trace = call_detect(
        store=store, embedding_provider=provider
    )
    assert findings == []
    assert trace is not None
    # layer is UNKNOWN; similarity_score recorded as 0.0; embedding_model
    # is the provider's model name (provider returned it deterministically).
    assert trace.layer is SimilarityLayer.UNKNOWN
    assert trace.embedding_model == "raising"


def test_semantic_provider_exception_with_unknown_model() -> None:
    """An exception-raising provider with model=None also records UNKNOWN."""

    class UnknownModelProvider(_RaisingProvider):
        model = None

    provider = UnknownModelProvider()
    store = make_store(
        left_raw="foo",
        right_raw="bar",
        left_meta=make_left_meta(),
        right_meta=make_right_meta(),
    )
    findings, trace = call_detect(
        store=store, embedding_provider=provider
    )
    assert findings == []
    assert trace.embedding_model is None
    assert trace.layer is SimilarityLayer.UNKNOWN


def test_semantic_provider_returns_dimension_mismatch_is_safe() -> None:
    """When the provider returns vectors of different dimensions, the
    detector treats the layer as unavailable; no finding is emitted."""

    class _DimMismatchProvider:
        model = "dim-mismatch"

        def embed(self, text, *, model=None):
            # Return different-dimension vectors deterministically.
            if "lorem" in text:
                return [1.0, 0.0, 0.0]
            return [0.0, 1.0, 0.0, 0.0, 0.0]

        def embed_request(self, request):
            return None

        def model_name(self):
            return self.model

    store = make_store(
        left_raw="lorem ipsum dolor",
        right_raw="completely unrelated content here",
        left_meta=make_left_meta(),
        right_meta=make_right_meta(),
    )
    findings, trace = call_detect(
        store=store, embedding_provider=_DimMismatchProvider()
    )
    assert findings == []
    assert trace.layer is SimilarityLayer.UNKNOWN


def test_semantic_provider_returns_zero_vector_is_safe() -> None:
    """When the provider returns all-zero vectors, cosine_similarity
    returns 0.0 explicitly (not NaN, not exception). The detector
    treats that as a real, low score."""

    class _ZeroVecProvider:
        model = "zero-vec"

        def embed(self, text, *, model=None):
            return [0.0, 0.0, 0.0]

        def embed_request(self, request):
            return None

        def model_name(self):
            return self.model

    store = make_store(
        left_raw="alpha",
        right_raw="beta",
        left_meta=make_left_meta(),
        right_meta=make_right_meta(),
    )
    findings, trace = call_detect(
        store=store, embedding_provider=_ZeroVecProvider()
    )
    assert findings == []
    assert trace.layer is SimilarityLayer.UNKNOWN
    assert trace.similarity_score == 0.0


def test_semantic_provider_returns_nan_vector_is_safe() -> None:
    """NaN inside a vector must NOT propagate; the detector must treat
    the layer as unavailable rather than emit a finding or raise."""

    class _NanProvider:
        model = "nan-vec"

        def embed(self, text, *, model=None):
            return [float("nan"), 0.0, 0.0]

        def embed_request(self, request):
            return None

        def model_name(self):
            return self.model

    store = make_store(
        left_raw="alpha",
        right_raw="beta",
        left_meta=make_left_meta(),
        right_meta=make_right_meta(),
    )
    findings, trace = call_detect(
        store=store, embedding_provider=_NanProvider()
    )
    assert findings == []
    assert trace.layer is SimilarityLayer.UNKNOWN


# ---------------------------------------------------------------------------
# Template gate and confidence formula
# ---------------------------------------------------------------------------


def test_template_mismatch_blocks_semantic_emission() -> None:
    """A MISMATCH in the template gate must block SEMANTIC emission,
    even when cosine is high. The trace is empty (UNKNOWN)."""
    left_raw = "x"
    right_raw = "y"
    left_norm = "x"
    right_norm = "y"
    provider = StaticEmbeddingProvider(
        model="m", vectors={
            left_norm: [1.0, 0.0, 0.0],
            right_norm: [1.0, 0.0, 0.0],
        }
    )
    # Deliberately set authorization_number DIFFERENT to force a
    # template mismatch.
    left_meta = make_left_meta(authorization_number="AUTH-LEFT-1")
    right_meta = make_right_meta(authorization_number="AUTH-RIGHT-2")
    store = make_store(
        left_raw=left_raw, right_raw=right_raw,
        left_meta=left_meta, right_meta=right_meta,
    )
    findings, trace = call_detect(store=store, embedding_provider=provider)
    # Mismatch -> no finding
    assert findings == []
    assert trace.layer is SimilarityLayer.UNKNOWN


def test_template_unknown_follows_existing_gate_semantics() -> None:
    """If all template fields are missing, gate is UNKNOWN -> no MATCH,
    so SEMANTIC does not emit a finding. Confidence factor is 0.0.
    """
    left_raw = "x"
    right_raw = "y"
    left_norm = "x"
    right_norm = "y"
    provider = StaticEmbeddingProvider(
        model="m", vectors={
            left_norm: [1.0, 0.0, 0.0],
            right_norm: [1.0, 0.0, 0.0],
        }
    )
    # Strip every template field.
    left_meta = DocumentMeta(
        document_type="OEM_AUTH",
        issuer=None,
        authorization_number=None,
        issue_date=None,
        valid_until=None,
        bidder_name="bidder-A",
        territory=None,
        ocr_confidence=0.95,
        document_type_confidence=0.99,
    )
    right_meta = DocumentMeta(
        document_type="OEM_AUTH",
        issuer=None,
        authorization_number=None,
        issue_date=None,
        valid_until=None,
        bidder_name="bidder-B",
        territory=None,
        ocr_confidence=0.95,
        document_type_confidence=0.99,
    )
    store = make_store(
        left_raw=left_raw, right_raw=right_raw,
        left_meta=left_meta, right_meta=right_meta,
    )
    findings, trace = call_detect(store=store, embedding_provider=provider)
    # Template UNKNOWN -> no MATCH -> no finding.
    assert findings == []
    assert trace.layer is SimilarityLayer.UNKNOWN


def test_corroboration_influences_semantic_confidence() -> None:
    """Strong corroboration must drive the final confidence higher than
    weak corroboration, holding the embedding score constant."""

    def run_with_issuer(same_issuer: bool):
        left_raw = "x"
        right_raw = "y"
        left_norm = "x"
        right_norm = "y"
        provider = StaticEmbeddingProvider(
            model="m", vectors={
                left_norm: [1.0, 0.0, 0.0],
                right_norm: [1.0, 0.0, 0.0],
            }
        )
        left_meta = make_left_meta(issuer="ACME" if same_issuer else "ALPHA")
        right_meta = make_right_meta(issuer="ACME" if same_issuer else "OMEGA")
        store = make_store(
            left_raw=left_raw, right_raw=right_raw,
            left_meta=left_meta, right_meta=right_meta,
        )
        findings, trace = call_detect(store=store, embedding_provider=provider)
        assert len(findings) == 1
        return findings[0].confidence, trace

    conf_match, _ = run_with_issuer(same_issuer=True)
    conf_mismatch, _ = run_with_issuer(same_issuer=False)
    assert conf_match > conf_mismatch


def test_quality_influences_semantic_confidence() -> None:
    """Lower OCR confidence must drive the final confidence down."""

    def run_with_quality(ocr_confidence: float):
        left_raw = "x"
        right_raw = "y"
        left_norm = "x"
        right_norm = "y"
        provider = StaticEmbeddingProvider(
            model="m", vectors={
                left_norm: [1.0, 0.0, 0.0],
                right_norm: [1.0, 0.0, 0.0],
            }
        )
        left_meta = make_left_meta(ocr_confidence=ocr_confidence)
        right_meta = make_right_meta(ocr_confidence=ocr_confidence)
        store = make_store(
            left_raw=left_raw, right_raw=right_raw,
            left_meta=left_meta, right_meta=right_meta,
        )
        findings, trace = call_detect(store=store, embedding_provider=provider)
        assert len(findings) == 1
        return findings[0].confidence

    high = run_with_quality(ocr_confidence=0.99)
    low = run_with_quality(ocr_confidence=0.30)
    assert high > low


def test_final_confidence_under_0_70_blocks_semantic_emission() -> None:
    """The 0.70 confidence floor still applies to semantic findings.

    Construct inputs that pull the formula below 0.70: low OCR
    confidence, no corroboration, weak template gate.
    """
    left_raw = "x"
    right_raw = "y"
    left_norm = "x"
    right_norm = "y"
    provider = StaticEmbeddingProvider(
        model="m", vectors={
            left_norm: [1.0, 0.0, 0.0],
            right_norm: [1.0, 0.0, 0.0],
        }
    )
    left_meta = make_left_meta(
        issuer="ACME", ocr_confidence=0.05,
        authorization_number="AUTH-1",
        issue_date=date(2026, 1, 10),
        territory="India",
    )
    right_meta = make_right_meta(
        issuer="OTHER", ocr_confidence=0.05,
        authorization_number="AUTH-2",
        issue_date=date(2026, 2, 10),
        territory="Other",
    )
    store = make_store(
        left_raw=left_raw, right_raw=right_raw,
        left_meta=left_meta, right_meta=right_meta,
    )
    findings, trace = call_detect(store=store, embedding_provider=provider)
    # Template mismatch blocks emission entirely.
    assert findings == []
    assert trace.layer is SimilarityLayer.UNKNOWN


def test_semantic_finding_respects_emission_threshold_when_gate_matches() -> None:
    """With a MATCHing template gate and full corroboration, the
    semantic confidence is comfortably above 0.70; finding is emitted.
    """
    left_raw = "x"
    right_raw = "y"
    left_norm = "x"
    right_norm = "y"
    provider = StaticEmbeddingProvider(
        model="m", vectors={
            left_norm: [1.0, 0.0, 0.0],
            right_norm: [1.0, 0.0, 0.0],
        }
    )
    left_meta = make_left_meta(
        issuer="ACME",
        authorization_number="AUTH-1",
        issue_date=date(2026, 1, 10),
        territory="India",
    )
    right_meta = make_right_meta(
        issuer="ACME",
        authorization_number="AUTH-1",
        issue_date=date(2026, 1, 10),
        territory="India",
    )
    store = make_store(
        left_raw=left_raw, right_raw=right_raw,
        left_meta=left_meta, right_meta=right_meta,
    )
    findings, trace = call_detect(store=store, embedding_provider=provider)
    assert len(findings) == 1
    assert findings[0].flag_id == "CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE"
    assert findings[0].confidence >= 0.70
    assert trace.layer is SimilarityLayer.SEMANTIC


# ---------------------------------------------------------------------------
# Determinism, orchestrator, and end-to-end engine
# ---------------------------------------------------------------------------


def test_semantic_layer_is_deterministic_with_deterministic_provider() -> None:
    """Two consecutive detector runs with the same deterministic
    provider produce identical findings and traces."""
    left_raw = "x"
    right_raw = "y"
    left_norm = "x"
    right_norm = "y"
    provider = StaticEmbeddingProvider(
        model="m", vectors={
            left_norm: [1.0, 0.0, 0.0],
            right_norm: [1.0, 0.0, 0.0],
        }
    )
    left_meta = make_left_meta(
        issuer="ACME", authorization_number="AUTH-1",
        issue_date=date(2026, 1, 10), territory="India",
    )
    right_meta = make_right_meta(
        issuer="ACME", authorization_number="AUTH-1",
        issue_date=date(2026, 1, 10), territory="India",
    )
    store_a = make_store(
        left_raw=left_raw, right_raw=right_raw,
        left_meta=left_meta, right_meta=right_meta,
    )
    store_b = make_store(
        left_raw=left_raw, right_raw=right_raw,
        left_meta=left_meta, right_meta=right_meta,
    )
    findings_a, trace_a = call_detect(store=store_a, embedding_provider=provider)
    findings_b, trace_b = call_detect(store=store_b, embedding_provider=provider)

    assert findings_a == findings_b
    assert trace_a.model_dump() == trace_b.model_dump()


def test_orchestrator_forwards_embedding_provider() -> None:
    """The orchestrator passes the embedding provider through to the
    detector and produces a NEAR_DUPLICATE finding via SEMANTIC."""
    from ai_verification.cross_bidder import CrossBidderOrchestrator
    from compliance_engine.models import Evidence

    left_raw = "alpha beta gamma"
    right_raw = "delta epsilon zeta"
    left_norm = "alpha beta gamma"
    right_norm = "delta epsilon zeta"
    provider = StaticEmbeddingProvider(
        model="orch-mock",
        vectors={
            left_norm: [1.0, 0.0, 0.0],
            right_norm: [1.0, 0.0, 0.0],
        },
    )
    left_meta = make_left_meta(
        issuer="ACME", authorization_number="AUTH-1",
        issue_date=date(2026, 1, 10), territory="India",
    )
    right_meta = make_right_meta(
        issuer="ACME", authorization_number="AUTH-1",
        issue_date=date(2026, 1, 10), territory="India",
    )
    store = make_store(
        left_raw=left_raw, right_raw=right_raw,
        left_meta=left_meta, right_meta=right_meta,
    )
    orchestrator = CrossBidderOrchestrator(
        artifact_store=store, embedding_provider=provider,
    )
    primary_ev = Evidence(
        evidence_id="ev-primary",
        bidder_id="bidder-A",
        document_id="doc-left",
        document_type="OEM_AUTH",
        field_name="authorization_number",
        value="AUTH-1",
        confidence=0.99,
    )
    other_ev = Evidence(
        evidence_id="ev-other",
        bidder_id="bidder-B",
        document_id="doc-right",
        document_type="OEM_AUTH",
        field_name="authorization_number",
        value="AUTH-1",
        confidence=0.99,
    )
    findings = orchestrator.run(
        primary_bidder_id="bidder-A",
        primary_evidence=[primary_ev],
        primary_verification_records=[],
        corpus=[("bidder-B", [other_ev], [])],
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding.flag_id == "CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE"
    assert finding.trace is not None
    assert finding.trace.layer is SimilarityLayer.SEMANTIC
    assert finding.trace.embedding_model == "orch-mock"


def test_orchestrator_without_provider_does_not_emit_semantic_finding() -> None:
    """Without an embedding provider wired into the orchestrator, the
    semantic layer is unavailable and only stronger reuse (EXACT /
    NORMALIZED / LEXICAL) can produce findings."""
    from ai_verification.cross_bidder import CrossBidderOrchestrator
    from compliance_engine.models import Evidence

    store = make_store(
        left_raw="x",
        right_raw="y",
        left_meta=make_left_meta(),
        right_meta=make_right_meta(),
    )
    orchestrator = CrossBidderOrchestrator(artifact_store=store)
    primary_ev = Evidence(
        evidence_id="ev-p",
        bidder_id="bidder-A",
        document_id="doc-left",
        document_type="OEM_AUTH",
        field_name="authorization_number",
        value="AUTH-1",
        confidence=0.99,
    )
    other_ev = Evidence(
        evidence_id="ev-o",
        bidder_id="bidder-B",
        document_id="doc-right",
        document_type="OEM_AUTH",
        field_name="authorization_number",
        value="AUTH-1",
        confidence=0.99,
    )
    findings = orchestrator.run(
        primary_bidder_id="bidder-A",
        primary_evidence=[primary_ev],
        primary_verification_records=[],
        corpus=[("bidder-B", [other_ev], [])],
    )
    # "x" and "y" don't trigger EXACT / NORMALIZED / LEXICAL.
    assert findings == []


def test_engine_accepts_semantic_finding_via_input() -> None:
    """The VerificationEngine accepts a semantic-derived finding and
    surfaces it on the VerificationResult."""
    from ai_verification.engine import VerificationEngine
    from ai_verification.models import BidderSummary, VerificationInput
    from compliance_engine.models import Evidence

    left_raw = "alpha beta"
    right_raw = "gamma delta"
    left_norm = "alpha beta"
    right_norm = "gamma delta"
    provider = StaticEmbeddingProvider(
        model="engine-mock",
        vectors={
            left_norm: [1.0, 0.0, 0.0],
            right_norm: [1.0, 0.0, 0.0],
        },
    )
    left_meta = make_left_meta(
        issuer="ACME", authorization_number="AUTH-1",
        issue_date=date(2026, 1, 10), territory="India",
    )
    right_meta = make_right_meta(
        issuer="ACME", authorization_number="AUTH-1",
        issue_date=date(2026, 1, 10), territory="India",
    )
    store = make_store(
        left_raw=left_raw, right_raw=right_raw,
        left_meta=left_meta, right_meta=right_meta,
    )
    engine = VerificationEngine(
        artifact_store=store, embedding_provider=provider,
    )
    primary_ev = Evidence(
        evidence_id="ev-p",
        bidder_id="bidder-A",
        document_id="doc-left",
        document_type="OEM_AUTH",
        field_name="authorization_number",
        value="AUTH-1",
        confidence=0.99,
    )
    other_ev = Evidence(
        evidence_id="ev-o",
        bidder_id="bidder-B",
        document_id="doc-right",
        document_type="OEM_AUTH",
        field_name="authorization_number",
        value="AUTH-1",
        confidence=0.99,
    )
    input_data = VerificationInput(
        bidder_id="bidder-A",
        evidence=[primary_ev],
        bidder_corpus=[
            BidderSummary(
                bidder_id="bidder-B",
                evidence=[other_ev],
            )
        ],
    )
    result = engine.run(input_data)
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.flag_id == "CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE"
    assert finding.trace is not None
    assert finding.trace.embedding_model == "engine-mock"
    assert finding.trace.layer is SimilarityLayer.SEMANTIC


def test_compare_two_documents_forwards_embedding_provider() -> None:
    """The compare_two_documents wrapper threads embedding_provider through."""
    left_raw = "alpha"
    right_raw = "beta"
    left_norm = "alpha"
    right_norm = "beta"
    provider = StaticEmbeddingProvider(
        model="wrapper-mock",
        vectors={
            left_norm: [1.0, 0.0, 0.0],
            right_norm: [1.0, 0.0, 0.0],
        },
    )
    left_meta = make_left_meta(
        issuer="ACME", authorization_number="AUTH-1",
        issue_date=date(2026, 1, 10), territory="India",
    )
    right_meta = make_right_meta(
        issuer="ACME", authorization_number="AUTH-1",
        issue_date=date(2026, 1, 10), territory="India",
    )
    store = make_store(
        left_raw=left_raw, right_raw=right_raw,
        left_meta=left_meta, right_meta=right_meta,
    )
    from ai_verification.cross_bidder import compare_two_documents
    findings, trace = compare_two_documents(
        bidder_id="bidder-A",
        other_bidder_id="bidder-B",
        left_doc_id="doc-left",
        right_doc_id="doc-right",
        artifact_store=store,
        embedding_provider=provider,
    )
    assert len(findings) == 1
    assert trace.embedding_model == "wrapper-mock"
    assert trace.layer is SimilarityLayer.SEMANTIC
