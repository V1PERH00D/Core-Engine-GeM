"""Deterministic quality-scoring formulas.

This module is the *only* place where numeric quality scores are
computed from raw signals. Every formula here is:

* Pure: same inputs always produce the same outputs.
* Side-effect free: no I/O, no logging, no random numbers.
* Documented: the formula for each score is given in the docstring
  of the function that computes it.

The formulas are deliberately *interpretable* rather than learned:
the engine must be auditable, so each component score is a small
closed-form expression of the signals the engine actually
observes.

Component score formulas
------------------------

Each component is scored in ``[0.0, 1.0]``:

* ``ocr_quality`` -- ``ocr_confidence`` if it is present, otherwise
  a *known-default* of ``0.0`` if the OCR text is also missing, or
  ``0.5`` if the OCR text is present but no confidence was
  reported. The 0.5 value reflects "we know we have text, we just
  don't know how confident we are"; this is intentionally
  distinguishable from "no signal at all".

* ``field_quality`` -- ``field_confidence`` if present, otherwise
  ``0.0`` if any required field is missing, or ``0.5`` if no
  confidence was reported but every required field is present.

* ``completeness`` -- ratio of present required fields to total
  required fields, plus a small bonus for raw text presence. The
  formula is documented in :func:`completeness_score`.

* ``metadata_reliability`` -- ``document_type_confidence`` if
  present, otherwise ``0.0`` if metadata is absent, or ``0.5`` if
  metadata is present but no document-type confidence was
  reported.

Overall quality score formula
-----------------------------

::

    overall = (
        0.30 * ocr_quality
        + 0.30 * field_quality
        + 0.25 * completeness
        + 0.15 * metadata_reliability
    )

The weights are tuned so the score is dominated by the two
extraction-quality signals (OCR and field) and modulated by
completeness and metadata reliability. They are stable: changing
them is a deliberate policy change, not an implementation detail.

The state mapping is conservative:

* ``overall >= GOOD_THRESHOLD`` and no critical reasons ->
  :attr:`QualityState.GOOD`.
* Any critical reason (OCR_MISSING + no text, FIELD_CONFIDENCE_MISSING,
  DOCUMENT_TEXT_MISSING, METADATA_INCOMPLETE) -> ``UNKNOWN``.
* Otherwise -> ``DEGRADED``.
"""

from __future__ import annotations

from .signals import (
    DocumentQualitySignals,
    _validate_bounded_unit_float,
)
from .state import QualityReason


#: Weight of OCR quality in the overall score.
OCR_WEIGHT: float = 0.30

#: Weight of field-extraction quality in the overall score.
FIELD_WEIGHT: float = 0.30

#: Weight of completeness in the overall score.
COMPLETENESS_WEIGHT: float = 0.25

#: Weight of metadata reliability in the overall score.
METADATA_WEIGHT: float = 0.15


#: Default quality score assigned when a signal is missing but the
#: related artefact is present. Reflects "we have it, we just don't
#: know how confident we are" -- strictly lower than a reported
#: perfect confidence and strictly higher than "no signal at all".
KNOWN_DEFAULT_WHEN_PRESENT_BUT_UNSCORED: float = 0.5


#: Threshold below which the overall quality score is classified as
#: ``DEGRADED`` rather than ``GOOD``. Conservative; tuned so that
#: even mildly imperfect extraction drops the finding out of GOOD.
GOOD_THRESHOLD: float = 0.85


#: Reasons that always force :attr:`QualityState.UNKNOWN` (i.e. the
#: engine cannot establish any reliability for the evidence).
CRITICAL_UNKNOWN_REASONS = frozenset({
    QualityReason.DOCUMENT_TEXT_MISSING,
    QualityReason.METADATA_INCOMPLETE,
})


def ocr_quality_score(signals: DocumentQualitySignals) -> float:
    """Compute the OCR-quality component in ``[0.0, 1.0]``.

    The formula:

    * If OCR confidence was reported by the pipeline: return it
      verbatim (already in ``[0.0, 1.0]``).
    * If OCR text was present but no confidence was reported:
      return :data:`KNOWN_DEFAULT_WHEN_PRESENT_BUT_UNSCORED`
      (0.5). The signal is *known present, unknown quality*.
    * Otherwise (no OCR text and no OCR confidence): return 0.0.
      The signal is *unknown*.

    Note: this function does not emit reason codes. Reasons are
    emitted by :func:`field_quality_score`, :func:`completeness_score`
    and :func:`metadata_reliability_score` (which return tuples).
    OCR reasons are emitted by :func:`evaluate_signals`, which has
    access to all of them and avoids duplicates.
    """
    ocr_conf = signals.ocr.ocr_confidence
    if ocr_conf is not None:
        score = float(ocr_conf)
    elif signals.ocr.ocr_text_present:
        score = KNOWN_DEFAULT_WHEN_PRESENT_BUT_UNSCORED
    else:
        score = 0.0
    return _validate_bounded_unit_float(score)


def field_quality_score(
    signals: DocumentQualitySignals,
) -> tuple[float, list[QualityReason]]:
    """Compute the field-quality component in ``[0.0, 1.0]``.

    Returns ``(score, reasons)`` so the caller can collect reasons
    from all components without a second pass.
    """
    reasons: list[QualityReason] = []
    fc = signals.fields.field_confidence
    if fc is not None:
        score = float(fc)
        if score < 0.85:
            reasons.append(QualityReason.FIELD_CONFIDENCE_LOW)
    elif not signals.fields.required_fields_missing:
        score = KNOWN_DEFAULT_WHEN_PRESENT_BUT_UNSCORED
        reasons.append(QualityReason.FIELD_CONFIDENCE_MISSING)
    else:
        score = 0.0
        reasons.append(QualityReason.FIELD_CONFIDENCE_MISSING)
        reasons.append(QualityReason.REQUIRED_FIELD_MISSING)
    return _validate_bounded_unit_float(score), reasons


def completeness_score(
    signals: DocumentQualitySignals,
) -> tuple[float, list[QualityReason]]:
    """Compute the completeness component in ``[0.0, 1.0]``."""
    reasons: list[QualityReason] = []
    required = signals.completeness.required_fields
    present = signals.completeness.required_fields_present

    if required:
        present_ratio = len(present) / len(required)
    else:
        present_ratio = 1.0

    raw_text_bonus = 0.10 if signals.completeness.raw_text_present else 0.0
    metadata_bonus = 0.05 if signals.completeness.metadata_present else 0.0

    if not signals.completeness.raw_text_present:
        reasons.append(QualityReason.DOCUMENT_TEXT_MISSING)
    if signals.completeness.required_fields_missing:
        reasons.append(QualityReason.REQUIRED_FIELD_MISSING)
    if not signals.completeness.metadata_present:
        reasons.append(QualityReason.METADATA_INCOMPLETE)

    score = 0.85 * present_ratio + raw_text_bonus + metadata_bonus
    return _validate_bounded_unit_float(score), reasons


def metadata_reliability_score(
    signals: DocumentQualitySignals,
) -> tuple[float, list[QualityReason]]:
    """Compute the metadata-reliability component in ``[0.0, 1.0]``."""
    reasons: list[QualityReason] = []
    dtc = signals.metadata.document_type_confidence
    if dtc is not None:
        score = float(dtc)
        if score < 0.85:
            reasons.append(QualityReason.DOCUMENT_TYPE_CONFIDENCE_LOW)
    elif signals.metadata.metadata_present:
        score = KNOWN_DEFAULT_WHEN_PRESENT_BUT_UNSCORED
    else:
        score = 0.0
    return _validate_bounded_unit_float(score), reasons


def overall_quality_score(
    ocr_quality: float,
    field_quality: float,
    completeness: float,
    metadata_reliability: float,
) -> float:
    """Compute the overall quality score in ``[0.0, 1.0]``.

    Formula::

        overall = (
            OCR_WEIGHT * ocr_quality
            + FIELD_WEIGHT * field_quality
            + COMPLETENESS_WEIGHT * completeness
            + METADATA_WEIGHT * metadata_reliability
        )

    The weights are documented at module top.
    """
    raw = (
        OCR_WEIGHT * ocr_quality
        + FIELD_WEIGHT * field_quality
        + COMPLETENESS_WEIGHT * completeness
        + METADATA_WEIGHT * metadata_reliability
    )
    return _validate_bounded_unit_float(raw)


__all__ = [
    "COMPLETENESS_WEIGHT",
    "CRITICAL_UNKNOWN_REASONS",
    "FIELD_WEIGHT",
    "GOOD_THRESHOLD",
    "KNOWN_DEFAULT_WHEN_PRESENT_BUT_UNSCORED",
    "METADATA_WEIGHT",
    "OCR_WEIGHT",
    "completeness_score",
    "field_quality_score",
    "metadata_reliability_score",
    "ocr_quality_score",
    "overall_quality_score",
]

