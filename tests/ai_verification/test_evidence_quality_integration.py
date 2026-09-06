"""Integration tests for evidence-quality inside the cross-bidder detector.

Covers:

* quality propagation into SimilarityTrace
* quality influence on confidence
* exact reuse unaffected by OCR quality
* normalized reuse unaffected by OCR quality
* semantic finding confidence reduced by poor quality
* insufficient quality preventing a semantic finding
* existing template gate still wins
* existing 0.70 emission threshold remains authoritative
* quality fields are optional / backward compatible
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from ai_verification.cross_bidder import (
    SimilarityLayer,
    StaticEmbeddingProvider,
    detect_cross_bidder_anomalies,
)
from ai_verification.cross_bidder.document_artifact_store import (
    DocumentMeta,
    InMemoryDocumentArtifactStore,
)
from ai_verification.cross_bidder.trace import (
    CorroborationSignals,
    QualitySignals,
    SimilarityTrace,
    TemplateGate,
    TemplateGateStatus,
)
from ai_verification.evidence_quality import (
    DocumentMetaQualityEvaluator,
    DocumentQualitySignals,
    EvidenceQualityAssessment,
    OCRQualitySignals,
    QualityComponentScores,
    QualityReason,
    QualityState,
    StaticEvidenceQualityEvaluator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _left_meta(**overrides) -> DocumentMeta:
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


def _right_meta(**overrides) -> DocumentMeta:
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


def _store(
    *,
    left_raw: str | None = "Same content",
    right_raw: str | None = "Same content",
    left_hash: str | None = "abc",
    right_hash: str | None = "abc",
    left_meta: DocumentMeta | None = None,
    right_meta: DocumentMeta | None = None,
) -> InMemoryDocumentArtifactStore:
    raw_texts: dict[str, str] = {}
    file_hashes: dict[str, str] = {}
    metadata: dict[str, DocumentMeta] = {}
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


# ---------------------------------------------------------------------------
# Quality propagation into SimilarityTrace
# ---------------------------------------------------------------------------


def test_trace_quality_state_populated_by_default_evaluator() -> None:
    store = _store(
        left_meta=_left_meta(),
        right_meta=_right_meta(),
    )
    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )
    assert trace.quality.quality_state is not None
    assert trace.quality.ocr_quality is not None
    assert trace.quality.field_quality is not None
    assert trace.quality.completeness is not None
    assert trace.quality.metadata_reliability is not None


def test_trace_quality_reasons_populated_when_low_ocr() -> None:
    store = _store(
        left_meta=_left_meta(ocr_confidence=0.30),
        right_meta=_right_meta(),
    )
    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )
    assert QualityReason.OCR_LOW.value in trace.quality.quality_reasons


def test_trace_quality_reasons_populated_when_missing_text() -> None:
    store = _store(
        left_raw=None,
        right_raw=None,
        left_meta=_left_meta(),
        right_meta=_right_meta(),
    )
    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )
    assert (
        QualityReason.DOCUMENT_TEXT_MISSING.value
        in trace.quality.quality_reasons
    )


def test_trace_quality_state_unknown_when_text_missing() -> None:
    store = _store(
        left_raw=None,
        right_raw=None,
        left_meta=_left_meta(),
        right_meta=_right_meta(),
    )
    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )
    assert trace.quality.quality_state == "UNKNOWN"


# ---------------------------------------------------------------------------
# Quality influence on confidence
# ---------------------------------------------------------------------------


def test_exact_reuse_emits_regardless_of_ocr_quality() -> None:
    # Strong exact byte reuse should still EMIT even when OCR
    # metadata is weak, because exact hash equality does not
    # depend on OCR. The quality gate must NOT suppress exact.
    store_high = _store(
        left_meta=_left_meta(ocr_confidence=0.95),
        right_meta=_right_meta(ocr_confidence=0.95),
    )
    store_low = _store(
        left_meta=_left_meta(ocr_confidence=0.05),
        right_meta=_right_meta(ocr_confidence=0.05),
    )
    findings_high, trace_high = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store_high,
    )
    findings_low, trace_low = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store_low,
    )
    # Both must emit the same flag, regardless of OCR quality.
    assert trace_high.layer is SimilarityLayer.EXACT
    assert trace_low.layer is SimilarityLayer.EXACT
    assert len(findings_high) == 1
    assert len(findings_low) == 1
    assert findings_high[0].flag_id == "CROSS_BIDDER_DOCUMENT_REUSED"
    assert findings_low[0].flag_id == "CROSS_BIDDER_DOCUMENT_REUSED"


def test_normalized_reuse_emits_regardless_of_ocr_quality() -> None:
    # Strong normalized-text reuse should still EMIT even when
    # OCR metadata is weak, because normalized hash equality does
    # not depend on OCR.
    store_high = InMemoryDocumentArtifactStore(
        raw_texts={"doc-left": "  Same Text  ", "doc-right": "Same Text"},
        metadata={
            "doc-left": _left_meta(ocr_confidence=0.95),
            "doc-right": _right_meta(ocr_confidence=0.95),
        },
    )
    store_low = InMemoryDocumentArtifactStore(
        raw_texts={"doc-left": "  Same Text  ", "doc-right": "Same Text"},
        metadata={
            "doc-left": _left_meta(ocr_confidence=0.05),
            "doc-right": _right_meta(ocr_confidence=0.05),
        },
    )
    findings_high, trace_high = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store_high,
    )
    findings_low, trace_low = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store_low,
    )
    assert trace_high.layer is SimilarityLayer.NORMALIZED
    assert trace_low.layer is SimilarityLayer.NORMALIZED
    assert len(findings_high) == 1
    assert len(findings_low) == 1


def test_semantic_finding_confidence_reduced_by_poor_quality() -> None:
    # Build a strong semantic match between two distinct raw
    # texts so EXACT/NORMALIZED/LEXICAL do not win.
    provider = StaticEmbeddingProvider(
        model="quality-mock",
        vectors={
            "apple": [1.0, 0.0, 0.0],
            "orange": [1.0, 0.0, 0.0],
        },
    )
    store_high = _store(
        left_raw="apple",
        right_raw="orange",
        left_hash=None,
        right_hash=None,
        left_meta=_left_meta(ocr_confidence=0.95),
        right_meta=_right_meta(ocr_confidence=0.95),
    )
    store_low = _store(
        left_raw="apple",
        right_raw="orange",
        left_hash=None,
        right_hash=None,
        left_meta=_left_meta(ocr_confidence=0.10),
        right_meta=_right_meta(ocr_confidence=0.10),
    )
    _, trace_high = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store_high,
        embedding_provider=provider,
        semantic_similarity_threshold=0.85,
    )
    _, trace_low = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store_low,
        embedding_provider=provider,
        semantic_similarity_threshold=0.85,
    )
    assert trace_high.layer is SimilarityLayer.SEMANTIC
    assert trace_low.layer is SimilarityLayer.SEMANTIC
    assert trace_low.confidence < trace_high.confidence


def test_insufficient_quality_suppresses_semantic_finding() -> None:
    # When the quality is so degraded that the gate refuses,
    # the SEMANTIC layer must NOT emit, even though raw text and
    # embeddings are available. We use distinct enough raw text
    # that EXACT/NORMALIZED/LEXICAL all fail, so the semantic
    # layer would otherwise be the only path.
    provider = StaticEmbeddingProvider(
        model="quality-mock",
        vectors={
            "apple": [1.0, 0.0, 0.0],
            "orange": [1.0, 0.0, 0.0],
        },
    )

    class _UnknownEvaluator:
        def evaluate(self, signals):
            return EvidenceQualityAssessment(
                state=QualityState.UNKNOWN,
                quality_score=0.0,
                components=QualityComponentScores(
                    ocr_quality=0.0,
                    field_quality=0.0,
                    completeness=0.0,
                    metadata_reliability=0.0,
                ),
                reasons=[QualityReason.METADATA_INCOMPLETE],
            )

    store = _store(
        left_raw="apple",
        right_raw="orange",
        left_hash=None,
        right_hash=None,
        left_meta=_left_meta(),
        right_meta=_right_meta(),
    )
    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
        embedding_provider=provider,
        semantic_similarity_threshold=0.85,
        quality_evaluator=_UnknownEvaluator(),
    )
    # The semantic layer must NOT have fired -- the gate stopped it.
    assert findings == []
    assert trace.layer is SimilarityLayer.UNKNOWN


# ---------------------------------------------------------------------------
# Existing precedence is preserved
# ---------------------------------------------------------------------------


def test_template_gate_still_blocks_emission_when_mismatch() -> None:
    # Template mismatch must still block even with perfect quality.
    # Build a true template mismatch by making all three template
    # fields differ.
    left_meta = _left_meta(
        issuer="ACME",
        authorization_number="AUTH-A",
        issue_date=date(2026, 1, 10),
        territory="India",
    )
    right_meta = _right_meta(
        issuer="OTHER",
        authorization_number="AUTH-B",
        issue_date=date(2025, 6, 10),
        territory="Brazil",
    )
    store = _store(
        left_raw="Same content here for byte matching",
        right_raw="Same content here for byte matching",
        left_hash="h",
        right_hash="h",
        left_meta=left_meta,
        right_meta=right_meta,
    )
    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )
    assert findings == []
    assert trace.template_gate.status is TemplateGateStatus.MISMATCH


def test_existing_quality_signals_fields_still_present() -> None:
    # The three legacy QualitySignals fields must remain populated.
    store = _store(
        left_meta=_left_meta(),
        right_meta=_right_meta(),
    )
    _, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )
    assert hasattr(trace.quality, "ocr_confidence")
    assert hasattr(trace.quality, "field_confidence")
    assert hasattr(trace.quality, "quality_score")
    # And they must be in [0, 1].
    for value in (
        trace.quality.ocr_confidence,
        trace.quality.field_confidence,
        trace.quality.quality_score,
    ):
        assert 0.0 <= value <= 1.0


def test_zero_point_seven_threshold_still_authoritative() -> None:
    # Lexical near-duplicate with mismatched corroboration should
    # fall below 0.70 and not emit. The new quality subsystem must
    # not change this threshold.
    left_meta = _left_meta(
        issuer="ACME",
        authorization_number="AUTH-1",
        issue_date=date(2026, 1, 10),
    )
    right_meta = _right_meta(
        issuer="OTHER",
        authorization_number="AUTH-2",
        issue_date=date(2025, 1, 10),
    )
    raw = "lorem ipsum dolor sit amet " * 20  # long string for dice
    store = _store(
        left_raw=raw,
        right_raw=raw,
        left_hash=None,
        right_hash=None,
        left_meta=left_meta,
        right_meta=right_meta,
    )
    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )
    # Either no findings, or the confidence must be < 0.70.
    if findings:
        for finding in findings:
            assert finding.confidence < 0.70


# ---------------------------------------------------------------------------
# Custom evaluator injection
# ---------------------------------------------------------------------------


def test_custom_static_evaluator_overrides_assessment() -> None:
    # Inject a static evaluator that forces UNKNOWN state.
    class _UnknownEvaluator:
        def evaluate(self, signals):
            return EvidenceQualityAssessment(
                state=QualityState.UNKNOWN,
                quality_score=0.0,
                components=QualityComponentScores(
                    ocr_quality=0.0,
                    field_quality=0.0,
                    completeness=0.0,
                    metadata_reliability=0.0,
                ),
                reasons=[QualityReason.METADATA_INCOMPLETE],
            )

    store = _store(
        left_meta=_left_meta(),
        right_meta=_right_meta(),
    )
    _, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
        quality_evaluator=_UnknownEvaluator(),
    )
    assert trace.quality.quality_state == "UNKNOWN"
    assert QualityReason.METADATA_INCOMPLETE.value in trace.quality.quality_reasons
