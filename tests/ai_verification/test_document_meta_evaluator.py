"""Tests for the default DocumentMeta-based quality evaluator."""

from __future__ import annotations

from datetime import date

import pytest

from ai_verification.cross_bidder.document_artifact_store import (
    DocumentMeta,
    InMemoryDocumentArtifactStore,
)
from ai_verification.evidence_quality import (
    DocumentMetaQualityEvaluator,
    QualityReason,
    QualityState,
    build_signals_for_document,
)


def _meta(**overrides) -> DocumentMeta:
    base = DocumentMeta(
        document_type="OEM_AUTH",
        issuer="ACME",
        authorization_number="AUTH-1",
        issue_date=date(2026, 1, 10),
        valid_until=date(2027, 1, 10),
        bidder_name="Bidder A",
        territory="India",
        ocr_confidence=0.95,
        document_type_confidence=0.99,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_signals_built_from_meta_for_present_document() -> None:
    meta = _meta()
    store = InMemoryDocumentArtifactStore(
        raw_texts={"doc-1": "body"},
        metadata={"doc-1": meta},
    )
    signals = build_signals_for_document("doc-1", meta, store)
    assert signals.ocr.ocr_confidence == 0.95
    assert signals.ocr.ocr_text_present is True
    assert signals.metadata.document_type_confidence == 0.99
    assert signals.metadata.metadata_present is True
    assert signals.completeness.raw_text_present is True
    assert signals.completeness.metadata_present is True


def test_signals_indicate_missing_text_when_store_has_none() -> None:
    meta = _meta()
    store = InMemoryDocumentArtifactStore(
        raw_texts={},
        metadata={"doc-1": meta},
    )
    signals = build_signals_for_document("doc-1", meta, store)
    assert signals.ocr.ocr_text_present is False
    assert signals.completeness.raw_text_present is False


def test_signals_indicate_missing_required_field() -> None:
    meta = _meta(authorization_number=None)
    store = InMemoryDocumentArtifactStore(
        raw_texts={"doc-1": "body"},
        metadata={"doc-1": meta},
    )
    signals = build_signals_for_document("doc-1", meta, store)
    assert "authorization_number" in signals.completeness.required_fields_missing


def test_evaluator_for_document_returns_state() -> None:
    meta = _meta()
    store = InMemoryDocumentArtifactStore(
        raw_texts={"doc-1": "body"},
        metadata={"doc-1": meta},
    )
    evaluator = DocumentMetaQualityEvaluator(artifact_store=store)
    assessment = evaluator.evaluate_for_document("doc-1", meta)
    # The default evaluator doesn't know per-field confidence,
    # so FIELD_CONFIDENCE_MISSING will be emitted and the state
    # is DEGRADED. The score should still be reasonably high
    # (because the field-quality default of 0.5 is used).
    assert assessment.quality_score >= 0.80
    assert QualityReason.FIELD_CONFIDENCE_MISSING in assessment.reasons


def test_evaluator_returns_unknown_when_text_missing() -> None:
    meta = _meta()
    store = InMemoryDocumentArtifactStore(
        raw_texts={},
        metadata={"doc-1": meta},
    )
    evaluator = DocumentMetaQualityEvaluator(artifact_store=store)
    assessment = evaluator.evaluate_for_document("doc-1", meta)
    assert assessment.state is QualityState.UNKNOWN
    assert QualityReason.DOCUMENT_TEXT_MISSING in assessment.reasons


def test_evaluator_returns_degraded_for_low_ocr() -> None:
    meta = _meta(ocr_confidence=0.30)
    store = InMemoryDocumentArtifactStore(
        raw_texts={"doc-1": "body"},
        metadata={"doc-1": meta},
    )
    evaluator = DocumentMetaQualityEvaluator(artifact_store=store)
    assessment = evaluator.evaluate_for_document("doc-1", meta)
    assert assessment.state is QualityState.DEGRADED
    assert QualityReason.OCR_LOW in assessment.reasons


def test_evaluator_handles_missing_meta() -> None:
    # None meta must not raise.
    evaluator = DocumentMetaQualityEvaluator()
    assessment = evaluator.evaluate_for_document("doc-1", None)
    assert assessment.state is QualityState.UNKNOWN
    assert QualityReason.METADATA_INCOMPLETE in assessment.reasons
