"""Input signal models for the evidence-quality evaluator.

These are the *observables* the evaluator consumes. They are kept
separate from the assessment models so the evaluator can be tested
with arbitrary signal bundles without going through artifact stores.

Every model in this module uses ``extra='forbid'`` so accidental
field additions from production extraction pipelines are caught at
the boundary rather than propagated into the confidence formula.
"""

from __future__ import annotations

import math
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


#: A bounded float in ``[0.0, 1.0]`` used for every quality score
#: / confidence in this module. NaN and infinities are explicitly
#: rejected (see :func:`_validate_bounded_unit_float`).
BoundedUnitFloat = Annotated[
    float,
    Field(ge=0.0, le=1.0, description="Bounded score in [0.0, 1.0]."),
]


def _validate_bounded_unit_float(value: float) -> float:
    """Reject NaN, +/-inf and out-of-range floats.

    Pydantic's ``Field(ge=0.0, le=1.0)`` only enforces the numeric
    range. It happily accepts ``float('nan')`` because NaN compares
    as False against every bound. We explicitly reject NaN and
    infinities so the quality pipeline never silently carries
    poisoned values into confidence calculations.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"Expected a real number, got {type(value).__name__}")
    as_float = float(value)
    if math.isnan(as_float):
        raise ValueError("Quality values must not be NaN")
    if math.isinf(as_float):
        raise ValueError("Quality values must not be infinite")
    if as_float < 0.0 or as_float > 1.0:
        raise ValueError(
            f"Quality value must be in [0.0, 1.0], got {as_float!r}"
        )
    return as_float


class OCRQualitySignals(BaseModel):
    """OCR-related signals the evaluator can consume.

    ``ocr_confidence`` is the per-character / per-token OCR
    confidence in ``[0.0, 1.0]``; ``None`` means the upstream OCR
    pipeline did not report any confidence for this document. The
    distinction is deliberate: a low value is *known bad*, ``None``
    is *unknown*.
    """

    model_config = ConfigDict(extra="forbid")

    ocr_confidence: float | None = None
    ocr_text_present: bool = False

    @field_validator("ocr_confidence")
    @classmethod
    def _validate_ocr_confidence(cls, value: float | None) -> float | None:
        if value is None:
            return None
        return _validate_bounded_unit_float(value)


class FieldQualitySignals(BaseModel):
    """Field-extraction-related signals the evaluator can consume."""

    model_config = ConfigDict(extra="forbid")

    field_confidence: float | None = None
    required_fields_missing: list[str] = Field(default_factory=list)

    @field_validator("field_confidence")
    @classmethod
    def _validate_field_confidence(cls, value: float | None) -> float | None:
        if value is None:
            return None
        return _validate_bounded_unit_float(value)


class MetadataReliabilitySignals(BaseModel):
    """Metadata-related signals the evaluator can consume."""

    model_config = ConfigDict(extra="forbid")

    document_type_confidence: float | None = None
    metadata_present: bool = False

    @field_validator("document_type_confidence")
    @classmethod
    def _validate_document_type_confidence(
        cls, value: float | None
    ) -> float | None:
        if value is None:
            return None
        return _validate_bounded_unit_float(value)


class CompletenessSignals(BaseModel):
    """Observations about which evidence ingredients are present.

    This is *not* a score: it is a deterministic boolean breakdown
    of what the engine could and could not retrieve. The evaluator
    turns this breakdown into a completeness score and the
    corresponding reason codes.
    """

    model_config = ConfigDict(extra="forbid")

    required_fields: list[str] = Field(default_factory=list)
    required_fields_present: list[str] = Field(default_factory=list)
    required_fields_missing: list[str] = Field(default_factory=list)
    raw_text_present: bool = False
    metadata_present: bool = False

    @property
    def is_complete(self) -> bool:
        """Return ``True`` iff every required field was present and the
        raw text and metadata were available.
        """
        return (
            not self.required_fields_missing
            and self.raw_text_present
            and self.metadata_present
        )


class DocumentQualitySignals(BaseModel):
    """Bundle of every observable the evaluator can consume.

    The evaluator never reaches into artifact stores directly;
    callers pass this bundle, so the evaluator remains testable in
    isolation.
    """

    model_config = ConfigDict(extra="forbid")

    ocr: OCRQualitySignals = Field(default_factory=OCRQualitySignals)
    fields: FieldQualitySignals = Field(default_factory=FieldQualitySignals)
    metadata: MetadataReliabilitySignals = Field(
        default_factory=MetadataReliabilitySignals
    )
    completeness: CompletenessSignals = Field(
        default_factory=CompletenessSignals
    )


__all__ = [
    "BoundedUnitFloat",
    "CompletenessSignals",
    "DocumentQualitySignals",
    "FieldQualitySignals",
    "MetadataReliabilitySignals",
    "OCRQualitySignals",
]
