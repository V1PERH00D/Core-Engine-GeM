"""Evidence-quality evaluator abstraction.

The :class:`EvidenceQualityEvaluator` is the only public
interface the rest of the AI Verification Engine uses to obtain
quality assessments. Implementations must be:

* Deterministic: same inputs -> same outputs.
* Side-effect free: no I/O, no network, no random numbers.
* Cheap to call: this is in the hot path of cross-bidder
  detection.

The default implementation
(:class:`DocumentMetaQualityEvaluator`) constructs a
:class:`DocumentQualitySignals` bundle from a
:class:`ai_verification.cross_bidder.document_artifact_store.DocumentMeta`
plus the artifact store's view of raw text and metadata
availability.

For tests, :class:`StaticEvidenceQualityEvaluator` accepts an
explicit :class:`DocumentQualitySignals` bundle (or a callable that
produces one) and returns the corresponding assessment.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from .assessment import EvidenceQualityAssessment, QualityComponentScores
from .scoring import (
    GOOD_THRESHOLD,
    completeness_score,
    field_quality_score,
    metadata_reliability_score,
    ocr_quality_score,
    overall_quality_score,
)
from .signals import DocumentQualitySignals
from .state import QualityReason, QualityState


@runtime_checkable
class EvidenceQualityEvaluator(Protocol):
    """Protocol every evidence-quality evaluator must satisfy."""

    def evaluate(
        self, signals: DocumentQualitySignals
    ) -> EvidenceQualityAssessment:
        """Return a deterministic assessment.

        Implementations MUST:

        * Return a value with ``quality_score`` in ``[0.0, 1.0]``.
        * Populate ``reasons`` with at least one
          :class:`QualityReason` when state is not
          :attr:`QualityState.GOOD`.
        * Never raise on missing signals.
        """
        ...


def _derive_state(
    overall: float, reasons: list[QualityReason]
) -> QualityState:
    """Map an overall score + reason set to a :class:`QualityState`.

    Conservative rules:

    * If any *critical* reason is present, state is ``UNKNOWN``.
      Critical reasons are the ones that mean the engine cannot
      establish any reliability for the evidence.
    * Otherwise, if the overall score is at or above
      :data:`GOOD_THRESHOLD` and there are no reasons at all,
      the state is ``GOOD``.
    * Otherwise, the state is ``DEGRADED``.
    """
    from .scoring import CRITICAL_UNKNOWN_REASONS

    if any(r in CRITICAL_UNKNOWN_REASONS for r in reasons):
        return QualityState.UNKNOWN
    if overall >= GOOD_THRESHOLD and not reasons:
        return QualityState.GOOD
    return QualityState.DEGRADED


def evaluate_signals(
    signals: DocumentQualitySignals,
) -> EvidenceQualityAssessment:
    """Compute the assessment for a :class:`DocumentQualitySignals`.

    This is the *single* deterministic core. It is a free function
    so tests can call it directly without an evaluator instance.

    Reason handling:

    * OCR_LOW / OCR_MISSING are emitted here.
    * Field reasons are emitted by :func:`field_quality_score`.
    * Completeness reasons are emitted by
      :func:`completeness_score`.
    * Document-type reasons are emitted by
      :func:`metadata_reliability_score`.
    * The final list is deduplicated while preserving order.
    """
    ocr_q = ocr_quality_score(signals)
    field_q, field_reasons = field_quality_score(signals)
    comp_q, comp_reasons = completeness_score(signals)
    meta_q, meta_reasons = metadata_reliability_score(signals)

    ocr_reasons: list[QualityReason] = []
    if signals.ocr.ocr_confidence is None:
        ocr_reasons.append(QualityReason.OCR_MISSING)
    elif signals.ocr.ocr_confidence < 0.85:
        ocr_reasons.append(QualityReason.OCR_LOW)

    overall = overall_quality_score(ocr_q, field_q, comp_q, meta_q)

    seen: set[QualityReason] = set()
    ordered: list[QualityReason] = []
    for reason in (
        ocr_reasons + field_reasons + comp_reasons + meta_reasons
    ):
        if reason not in seen:
            seen.add(reason)
            ordered.append(reason)

    state = _derive_state(overall, ordered)

    return EvidenceQualityAssessment(
        state=state,
        quality_score=overall,
        components=QualityComponentScores(
            ocr_quality=ocr_q,
            field_quality=field_q,
            completeness=comp_q,
            metadata_reliability=meta_q,
        ),
        reasons=ordered,
    )


class StaticEvidenceQualityEvaluator:
    """Evaluator that returns assessments derived from explicit signals.

    Construction modes:

    * Pass a :class:`DocumentQualitySignals` instance directly:
      every call to :meth:`evaluate` returns the assessment
      computed from that bundle.
    * Pass ``None``: defaults to an empty signals bundle.

    This is the implementation tests should use. It is fully
    deterministic and easy to fake.
    """

    def __init__(
        self,
        signals: DocumentQualitySignals | None = None,
    ) -> None:
        self._default_signals = signals or DocumentQualitySignals()

    def evaluate(
        self, signals: DocumentQualitySignals
    ) -> EvidenceQualityAssessment:
        return evaluate_signals(signals)


__all__ = [
    "EvidenceQualityEvaluator",
    "StaticEvidenceQualityEvaluator",
    "evaluate_signals",
]

