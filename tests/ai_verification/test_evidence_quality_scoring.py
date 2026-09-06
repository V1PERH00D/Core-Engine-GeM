"""Focused tests for the deterministic quality scoring + evaluator.

Covers:

* valid high-quality evidence
* low OCR confidence
* missing OCR confidence
* low field confidence
* missing field confidence
* missing raw text
* incomplete metadata
* document-type confidence effects
* deterministic quality score
* quality reason generation
* QUALITY_GOOD / QUALITY_DEGRADED / QUALITY_UNKNOWN states
* completeness behaviour
"""

from __future__ import annotations

import pytest

from ai_verification.evidence_quality import (
    CompletenessSignals,
    DocumentQualitySignals,
    FieldQualitySignals,
    MetadataReliabilitySignals,
    OCRQualitySignals,
    QualityReason,
    QualityState,
    StaticEvidenceQualityEvaluator,
    completeness_score,
    evaluate_signals,
    field_quality_score,
    metadata_reliability_score,
    ocr_quality_score,
    overall_quality_score,
)


# ---------------------------------------------------------------------------
# Component scoring
# ---------------------------------------------------------------------------


def test_ocr_quality_high_when_confidence_high() -> None:
    signals = DocumentQualitySignals(
        ocr=OCRQualitySignals(ocr_confidence=0.95, ocr_text_present=True),
    )
    assert ocr_quality_score(signals) == 0.95


def test_ocr_quality_low_when_confidence_low() -> None:
    signals = DocumentQualitySignals(
        ocr=OCRQualitySignals(ocr_confidence=0.30, ocr_text_present=True),
    )
    assert ocr_quality_score(signals) == 0.30


def test_ocr_quality_zero_when_text_missing_and_no_confidence() -> None:
    signals = DocumentQualitySignals(
        ocr=OCRQualitySignals(ocr_confidence=None, ocr_text_present=False),
    )
    assert ocr_quality_score(signals) == 0.0


def test_ocr_quality_default_when_text_present_but_no_confidence() -> None:
    signals = DocumentQualitySignals(
        ocr=OCRQualitySignals(ocr_confidence=None, ocr_text_present=True),
    )
    # Default: "we have text but we don't know confidence".
    assert ocr_quality_score(signals) == 0.5


def test_field_quality_high_when_confidence_high_and_required_present() -> None:
    signals = DocumentQualitySignals(
        fields=FieldQualitySignals(
            field_confidence=0.92, required_fields_missing=[]
        ),
    )
    score, _ = field_quality_score(signals)
    assert score == 0.92


def test_field_quality_low_when_confidence_low() -> None:
    signals = DocumentQualitySignals(
        fields=FieldQualitySignals(
            field_confidence=0.40, required_fields_missing=[]
        ),
    )
    score, reasons = field_quality_score(signals)
    assert score == 0.40
    assert QualityReason.FIELD_CONFIDENCE_LOW in reasons


def test_field_quality_default_when_required_present_but_no_confidence() -> None:
    signals = DocumentQualitySignals(
        fields=FieldQualitySignals(
            field_confidence=None, required_fields_missing=[]
        ),
    )
    score, reasons = field_quality_score(signals)
    assert score == 0.5
    assert QualityReason.FIELD_CONFIDENCE_MISSING in reasons


def test_field_quality_zero_when_required_missing_and_no_confidence() -> None:
    signals = DocumentQualitySignals(
        fields=FieldQualitySignals(
            field_confidence=None, required_fields_missing=["authorization_number"]
        ),
    )
    score, reasons = field_quality_score(signals)
    assert score == 0.0
    assert QualityReason.FIELD_CONFIDENCE_MISSING in reasons
    assert QualityReason.REQUIRED_FIELD_MISSING in reasons


def test_completeness_full_when_everything_present() -> None:
    signals = DocumentQualitySignals(
        completeness=CompletenessSignals(
            required_fields=["issuer", "authorization_number"],
            required_fields_present=["issuer", "authorization_number"],
            required_fields_missing=[],
            raw_text_present=True,
            metadata_present=True,
        ),
    )
    score, reasons = completeness_score(signals)
    assert score == pytest.approx(1.0)
    assert reasons == []


def test_completeness_partial_when_half_required_present() -> None:
    signals = DocumentQualitySignals(
        completeness=CompletenessSignals(
            required_fields=["issuer", "authorization_number"],
            required_fields_present=["issuer"],
            required_fields_missing=["authorization_number"],
            raw_text_present=False,
            metadata_present=True,
        ),
    )
    score, reasons = completeness_score(signals)
    # 0.85 * 0.5 + 0.0 (no text) + 0.05 (meta) = 0.475
    assert score == pytest.approx(0.475)
    assert QualityReason.REQUIRED_FIELD_MISSING in reasons
    assert QualityReason.DOCUMENT_TEXT_MISSING in reasons


def test_completeness_missing_metadata_emits_incomplete_reason() -> None:
    signals = DocumentQualitySignals(
        completeness=CompletenessSignals(
            required_fields=[],
            required_fields_present=[],
            required_fields_missing=[],
            raw_text_present=True,
            metadata_present=False,
        ),
    )
    score, reasons = completeness_score(signals)
    assert score == pytest.approx(0.95)
    assert QualityReason.METADATA_INCOMPLETE in reasons


def test_metadata_reliability_high_when_confidence_high() -> None:
    signals = DocumentQualitySignals(
        metadata=MetadataReliabilitySignals(
            document_type_confidence=0.95, metadata_present=True
        ),
    )
    score, reasons = metadata_reliability_score(signals)
    assert score == 0.95
    assert reasons == []


def test_metadata_reliability_low_when_confidence_low() -> None:
    signals = DocumentQualitySignals(
        metadata=MetadataReliabilitySignals(
            document_type_confidence=0.40, metadata_present=True
        ),
    )
    score, reasons = metadata_reliability_score(signals)
    assert score == 0.40
    assert QualityReason.DOCUMENT_TYPE_CONFIDENCE_LOW in reasons


def test_metadata_reliability_zero_when_metadata_missing() -> None:
    signals = DocumentQualitySignals(
        metadata=MetadataReliabilitySignals(
            document_type_confidence=None, metadata_present=False
        ),
    )
    score, reasons = metadata_reliability_score(signals)
    assert score == 0.0
    assert reasons == []


# ---------------------------------------------------------------------------
# Overall scoring + state derivation
# ---------------------------------------------------------------------------


def test_overall_quality_score_is_bounded_weighted_sum() -> None:
    overall = overall_quality_score(1.0, 1.0, 1.0, 1.0)
    assert overall == pytest.approx(1.0)


def test_overall_quality_score_uses_documented_weights() -> None:
    # 0.30 + 0.30 + 0.25 + 0.15 = 1.00
    overall = overall_quality_score(
        ocr_quality=1.0,
        field_quality=1.0,
        completeness=1.0,
        metadata_reliability=1.0,
    )
    assert overall == pytest.approx(1.0)


def test_overall_quality_score_zero_when_all_components_zero() -> None:
    overall = overall_quality_score(0.0, 0.0, 0.0, 0.0)
    assert overall == pytest.approx(0.0)


def test_assessment_high_quality_is_good() -> None:
    signals = DocumentQualitySignals(
        ocr=OCRQualitySignals(ocr_confidence=0.95, ocr_text_present=True),
        fields=FieldQualitySignals(
            field_confidence=0.95, required_fields_missing=[]
        ),
        metadata=MetadataReliabilitySignals(
            document_type_confidence=0.95, metadata_present=True
        ),
        completeness=CompletenessSignals(
            required_fields=["issuer"],
            required_fields_present=["issuer"],
            required_fields_missing=[],
            raw_text_present=True,
            metadata_present=True,
        ),
    )
    assessment = evaluate_signals(signals)
    assert assessment.state is QualityState.GOOD
    assert assessment.reasons == []
    assert assessment.quality_score > 0.85


def test_assessment_unknown_when_text_missing() -> None:
    signals = DocumentQualitySignals(
        completeness=CompletenessSignals(
            required_fields=[],
            required_fields_present=[],
            required_fields_missing=[],
            raw_text_present=False,
            metadata_present=True,
        ),
    )
    assessment = evaluate_signals(signals)
    assert assessment.state is QualityState.UNKNOWN
    assert QualityReason.DOCUMENT_TEXT_MISSING in assessment.reasons


def test_assessment_unknown_when_metadata_incomplete() -> None:
    signals = DocumentQualitySignals(
        completeness=CompletenessSignals(
            required_fields=[],
            required_fields_present=[],
            required_fields_missing=[],
            raw_text_present=True,
            metadata_present=False,
        ),
    )
    assessment = evaluate_signals(signals)
    assert assessment.state is QualityState.UNKNOWN
    assert QualityReason.METADATA_INCOMPLETE in assessment.reasons


def test_assessment_degraded_for_low_ocr() -> None:
    signals = DocumentQualitySignals(
        ocr=OCRQualitySignals(ocr_confidence=0.40, ocr_text_present=True),
        fields=FieldQualitySignals(
            field_confidence=0.95, required_fields_missing=[]
        ),
        metadata=MetadataReliabilitySignals(
            document_type_confidence=0.95, metadata_present=True
        ),
        completeness=CompletenessSignals(
            required_fields=[],
            required_fields_present=[],
            required_fields_missing=[],
            raw_text_present=True,
            metadata_present=True,
        ),
    )
    assessment = evaluate_signals(signals)
    assert assessment.state is QualityState.DEGRADED
    assert QualityReason.OCR_LOW in assessment.reasons


def test_assessment_degraded_for_low_field_confidence() -> None:
    signals = DocumentQualitySignals(
        ocr=OCRQualitySignals(ocr_confidence=0.95, ocr_text_present=True),
        fields=FieldQualitySignals(
            field_confidence=0.40, required_fields_missing=[]
        ),
        metadata=MetadataReliabilitySignals(
            document_type_confidence=0.95, metadata_present=True
        ),
        completeness=CompletenessSignals(
            required_fields=[],
            required_fields_present=[],
            required_fields_missing=[],
            raw_text_present=True,
            metadata_present=True,
        ),
    )
    assessment = evaluate_signals(signals)
    assert assessment.state is QualityState.DEGRADED
    assert QualityReason.FIELD_CONFIDENCE_LOW in assessment.reasons


def test_assessment_reasons_deduplicated() -> None:
    # Field confidence is BOTH low AND missing -> reasons must
    # contain FIELD_CONFIDENCE_LOW exactly once.
    signals = DocumentQualitySignals(
        fields=FieldQualitySignals(
            field_confidence=0.40,
            required_fields_missing=["authorization_number"],
        ),
    )
    assessment = evaluate_signals(signals)
    assert assessment.reasons.count(QualityReason.FIELD_CONFIDENCE_LOW) == 1


def test_assessment_is_deterministic() -> None:
    signals = DocumentQualitySignals(
        ocr=OCRQualitySignals(ocr_confidence=0.85, ocr_text_present=True),
        fields=FieldQualitySignals(
            field_confidence=0.85, required_fields_missing=[]
        ),
        metadata=MetadataReliabilitySignals(
            document_type_confidence=0.85, metadata_present=True
        ),
        completeness=CompletenessSignals(
            required_fields=[],
            required_fields_present=[],
            required_fields_missing=[],
            raw_text_present=True,
            metadata_present=True,
        ),
    )
    a = evaluate_signals(signals)
    b = evaluate_signals(signals)
    assert a == b


def test_static_evaluator_matches_free_function() -> None:
    signals = DocumentQualitySignals(
        ocr=OCRQualitySignals(ocr_confidence=0.85, ocr_text_present=True),
        fields=FieldQualitySignals(
            field_confidence=0.85, required_fields_missing=[]
        ),
        metadata=MetadataReliabilitySignals(
            document_type_confidence=0.85, metadata_present=True
        ),
        completeness=CompletenessSignals(
            required_fields=[],
            required_fields_present=[],
            required_fields_missing=[],
            raw_text_present=True,
            metadata_present=True,
        ),
    )
    evaluator = StaticEvidenceQualityEvaluator()
    assert evaluator.evaluate(signals) == evaluate_signals(signals)
