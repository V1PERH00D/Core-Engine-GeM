"""Output assessment models for the evidence-quality engine.

The :class:`EvidenceQualityAssessment` is the deterministic result
of running an :class:`EvidenceQualityEvaluator` over a
:class:`DocumentQualitySignals` bundle.

Backward compatibility
----------------------
The legacy :class:`ai_verification.cross_bidder.trace.QualitySignals`
exposes three fields: ``ocr_confidence``, ``field_confidence``,
``quality_score``. The :class:`EvidenceQualityAssessment` exposes
the same values through:

* ``assessment.ocr_confidence`` (property) -> ``components.ocr_quality``
* ``assessment.field_confidence`` (property) -> ``components.field_quality``
* ``assessment.quality_score`` (field) -> the overall quality score

This means the existing trace can be populated from the
assessment without duplicating scoring logic, and existing tests
that build a :class:`QualitySignals` from raw fields keep passing
unchanged.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .signals import BoundedUnitFloat, _validate_bounded_unit_float
from .state import QualityReason, QualityState


class QualityComponentScores(BaseModel):
    """Per-dimension component scores produced by the evaluator.

    The four components are documented in
    :mod:`ai_verification.evidence_quality.scoring`. They are kept
    separate so the audit trace can show why the overall quality
    score was high or low.
    """

    model_config = ConfigDict(extra="forbid")

    ocr_quality: BoundedUnitFloat
    field_quality: BoundedUnitFloat
    completeness: BoundedUnitFloat
    metadata_reliability: BoundedUnitFloat

    @field_validator(
        "ocr_quality",
        "field_quality",
        "completeness",
        "metadata_reliability",
    )
    @classmethod
    def _validate_components(cls, value: float) -> float:
        return _validate_bounded_unit_float(value)


class EvidenceQualityAssessment(BaseModel):
    """Deterministic output of an :class:`EvidenceQualityEvaluator`.

    The overall :attr:`quality_score` is the value the existing
    cross-bidder confidence formula consumes as ``Q``. The
    cross-bidder formula itself remains authoritative; the
    assessment is just a cleaner, typed source for the inputs.
    """

    model_config = ConfigDict(extra="forbid")

    state: QualityState
    quality_score: BoundedUnitFloat
    components: QualityComponentScores
    reasons: list[QualityReason] = Field(default_factory=list)

    @property
    def ocr_confidence(self) -> float:
        """OCR component score in ``[0.0, 1.0]``.

        Backward-compatibility shim: returns the per-dimension
        OCR quality, not the raw OCR confidence value (those can
        diverge when the raw OCR confidence is ``None``).
        """
        return self.components.ocr_quality

    @property
    def field_confidence(self) -> float:
        """Field-quality component score in ``[0.0, 1.0]``.

        Backward-compatibility shim.
        """
        return self.components.field_quality

    @field_validator("quality_score")
    @classmethod
    def _validate_quality_score(cls, value: float) -> float:
        return _validate_bounded_unit_float(value)


__all__ = [
    "EvidenceQualityAssessment",
    "QualityComponentScores",
]
