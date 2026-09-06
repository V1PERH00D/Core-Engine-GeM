"""Focused tests for the conservative quality gating policy."""

from __future__ import annotations

from ai_verification.evidence_quality import (
    QualityComponentScores,
    QualityState,
    should_allow_exact_reuse,
    should_allow_semantic_finding,
)
from ai_verification.evidence_quality.assessment import (
    EvidenceQualityAssessment,
)


def _assess(state: QualityState, score: float) -> EvidenceQualityAssessment:
    return EvidenceQualityAssessment(
        state=state,
        quality_score=score,
        components=QualityComponentScores(
            ocr_quality=score,
            field_quality=score,
            completeness=score,
            metadata_reliability=score,
        ),
    )


def test_good_quality_allows_semantic_finding() -> None:
    assert should_allow_semantic_finding(_assess(QualityState.GOOD, 0.99)) is True


def test_degraded_high_quality_allows_semantic_finding() -> None:
    assert (
        should_allow_semantic_finding(_assess(QualityState.DEGRADED, 0.85))
        is True
    )


def test_degraded_low_quality_blocks_semantic_finding() -> None:
    assert (
        should_allow_semantic_finding(_assess(QualityState.DEGRADED, 0.10))
        is False
    )


def test_unknown_quality_always_blocks_semantic_finding() -> None:
    assert (
        should_allow_semantic_finding(_assess(QualityState.UNKNOWN, 1.0))
        is False
    )
    assert (
        should_allow_semantic_finding(_assess(QualityState.UNKNOWN, 0.0))
        is False
    )


def test_exact_reuse_always_allowed_under_quality_gating() -> None:
    # Strong exact byte reuse must remain strong even if OCR
    # metadata is weak, because exact hash equality does not
    # depend on OCR.
    assert should_allow_exact_reuse(_assess(QualityState.UNKNOWN, 0.0)) is True
    assert should_allow_exact_reuse(_assess(QualityState.DEGRADED, 0.0)) is True
    assert should_allow_exact_reuse(_assess(QualityState.GOOD, 1.0)) is True
