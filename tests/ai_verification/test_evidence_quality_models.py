"""Focused tests for the evidence-quality data models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_verification.evidence_quality import (
    CompletenessSignals,
    EvidenceQualityAssessment,
    FieldQualitySignals,
    MetadataReliabilitySignals,
    OCRQualitySignals,
    QualityComponentScores,
    QualityReason,
    QualityState,
)


# ---------------------------------------------------------------------------
# Bounded scalar validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [-0.0001, 1.0001, 1.5, -0.1])
def test_bounded_score_rejects_out_of_range(bad: float) -> None:
    with pytest.raises(ValidationError):
        QualityComponentScores(
            ocr_quality=0.5,
            field_quality=0.5,
            completeness=0.5,
            metadata_reliability=bad,
        )


def test_bounded_score_rejects_nan() -> None:
    with pytest.raises(ValidationError):
        QualityComponentScores(
            ocr_quality=0.5,
            field_quality=0.5,
            completeness=0.5,
            metadata_reliability=float("nan"),
        )


def test_bounded_score_rejects_infinity() -> None:
    with pytest.raises(ValidationError):
        QualityComponentScores(
            ocr_quality=0.5,
            field_quality=0.5,
            completeness=0.5,
            metadata_reliability=float("inf"),
        )


def test_bounded_score_rejects_negative_infinity() -> None:
    with pytest.raises(ValidationError):
        QualityComponentScores(
            ocr_quality=0.5,
            field_quality=0.5,
            completeness=float("-inf"),
            metadata_reliability=0.5,
        )


def test_bounded_score_accepts_zero_and_one() -> None:
    QualityComponentScores(
        ocr_quality=0.0,
        field_quality=1.0,
        completeness=0.0,
        metadata_reliability=1.0,
    )


def test_extra_fields_rejected_on_signal_model() -> None:
    with pytest.raises(ValidationError):
        OCRQualitySignals(ocr_confidence=0.5, garbage=1.0)  # type: ignore[call-arg]


def test_extra_fields_rejected_on_assessment() -> None:
    with pytest.raises(ValidationError):
        EvidenceQualityAssessment(
            state=QualityState.GOOD,
            quality_score=1.0,
            components=QualityComponentScores(
                ocr_quality=1.0,
                field_quality=1.0,
                completeness=1.0,
                metadata_reliability=1.0,
            ),
            extra_garbage=1.0,  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# Reason / state enums
# ---------------------------------------------------------------------------


def test_quality_reasons_are_stable_strings() -> None:
    assert QualityReason.OCR_LOW == "OCR_LOW"
    assert QualityReason.OCR_MISSING == "OCR_MISSING"
    assert QualityReason.FIELD_CONFIDENCE_LOW == "FIELD_CONFIDENCE_LOW"
    assert QualityReason.FIELD_CONFIDENCE_MISSING == "FIELD_CONFIDENCE_MISSING"
    assert QualityReason.DOCUMENT_TEXT_MISSING == "DOCUMENT_TEXT_MISSING"
    assert QualityReason.REQUIRED_FIELD_MISSING == "REQUIRED_FIELD_MISSING"
    assert QualityReason.DOCUMENT_TYPE_CONFIDENCE_LOW == "DOCUMENT_TYPE_CONFIDENCE_LOW"
    assert QualityReason.METADATA_INCOMPLETE == "METADATA_INCOMPLETE"


def test_quality_states_are_stable_strings() -> None:
    assert QualityState.GOOD == "GOOD"
    assert QualityState.DEGRADED == "DEGRADED"
    assert QualityState.UNKNOWN == "UNKNOWN"


# ---------------------------------------------------------------------------
# Signal model behavior
# ---------------------------------------------------------------------------


def test_completeness_is_complete_when_everything_present() -> None:
    signals = CompletenessSignals(
        required_fields=["issuer", "authorization_number"],
        required_fields_present=["issuer", "authorization_number"],
        required_fields_missing=[],
        raw_text_present=True,
        metadata_present=True,
    )
    assert signals.is_complete is True


def test_completeness_is_incomplete_when_required_missing() -> None:
    signals = CompletenessSignals(
        required_fields=["issuer"],
        required_fields_present=[],
        required_fields_missing=["issuer"],
        raw_text_present=True,
        metadata_present=True,
    )
    assert signals.is_complete is False


def test_completeness_is_incomplete_when_text_missing() -> None:
    signals = CompletenessSignals(
        required_fields=[],
        required_fields_present=[],
        required_fields_missing=[],
        raw_text_present=False,
        metadata_present=True,
    )
    assert signals.is_complete is False


def test_completeness_with_no_required_fields_defaults_complete_when_text_meta_present() -> None:
    signals = CompletenessSignals(
        required_fields=[],
        required_fields_present=[],
        required_fields_missing=[],
        raw_text_present=True,
        metadata_present=True,
    )
    assert signals.is_complete is True


def test_ocr_signals_accept_none_confidence() -> None:
    sig = OCRQualitySignals(ocr_confidence=None, ocr_text_present=False)
    assert sig.ocr_confidence is None


def test_field_signals_accept_none_confidence() -> None:
    sig = FieldQualitySignals(field_confidence=None, required_fields_missing=["x"])
    assert sig.field_confidence is None
    assert sig.required_fields_missing == ["x"]


def test_metadata_signals_accept_none_confidence() -> None:
    sig = MetadataReliabilitySignals(document_type_confidence=None, metadata_present=False)
    assert sig.document_type_confidence is None


# ---------------------------------------------------------------------------
# Assessment properties for backward compatibility
# ---------------------------------------------------------------------------


def test_assessment_ocr_confidence_property_returns_component() -> None:
    assessment = EvidenceQualityAssessment(
        state=QualityState.GOOD,
        quality_score=1.0,
        components=QualityComponentScores(
            ocr_quality=0.42,
            field_quality=0.7,
            completeness=0.9,
            metadata_reliability=0.8,
        ),
    )
    assert assessment.ocr_confidence == 0.42
    assert assessment.field_confidence == 0.7


def test_assessment_reasons_default_to_empty_list() -> None:
    assessment = EvidenceQualityAssessment(
        state=QualityState.GOOD,
        quality_score=1.0,
        components=QualityComponentScores(
            ocr_quality=1.0,
            field_quality=1.0,
            completeness=1.0,
            metadata_reliability=1.0,
        ),
    )
    assert assessment.reasons == []


def test_assessment_rejects_nan_quality_score() -> None:
    with pytest.raises(ValidationError):
        EvidenceQualityAssessment(
            state=QualityState.GOOD,
            quality_score=float("nan"),
            components=QualityComponentScores(
                ocr_quality=1.0,
                field_quality=1.0,
                completeness=1.0,
                metadata_reliability=1.0,
            ),
        )


def test_assessment_rejects_inf_quality_score() -> None:
    with pytest.raises(ValidationError):
        EvidenceQualityAssessment(
            state=QualityState.GOOD,
            quality_score=float("inf"),
            components=QualityComponentScores(
                ocr_quality=1.0,
                field_quality=1.0,
                completeness=1.0,
                metadata_reliability=1.0,
            ),
        )
