"""Evidence-quality and reliability engine.

Public API:

* :class:`EvidenceQualityEvaluator` -- the Protocol every
  evaluator must satisfy.
* :class:`StaticEvidenceQualityEvaluator` -- deterministic test
  evaluator that operates on explicit signals.
* :class:`DocumentMetaQualityEvaluator` -- default production
  evaluator that reads signals from
  :class:`ai_verification.cross_bidder.document_artifact_store.DocumentMeta`.
* :func:`evaluate_signals` -- the pure deterministic core; the
  same function the evaluators use internally.
* :class:`DocumentQualitySignals` -- the input bundle of
  observables the evaluator consumes.
* :class:`EvidenceQualityAssessment` -- the deterministic output.
* :class:`QualityState` -- ``GOOD`` / ``DEGRADED`` / ``UNKNOWN``.
* :class:`QualityReason` -- typed reason codes.
* :func:`should_allow_semantic_finding` -- the conservative
  gating policy.
"""

from .assessment import EvidenceQualityAssessment, QualityComponentScores
from .document_meta_evaluator import (
    DEFAULT_REQUIRED_METADATA_FIELDS,
    DocumentMetaQualityEvaluator,
    build_signals_for_document,
    default_evaluator,
)
from .evaluator import (
    EvidenceQualityEvaluator,
    StaticEvidenceQualityEvaluator,
    evaluate_signals,
)
from .gating import (
    SEMANTIC_MINIMUM_QUALITY_SCORE,
    should_allow_exact_reuse,
    should_allow_semantic_finding,
)
from .scoring import (
    COMPLETENESS_WEIGHT,
    CRITICAL_UNKNOWN_REASONS,
    FIELD_WEIGHT,
    GOOD_THRESHOLD,
    KNOWN_DEFAULT_WHEN_PRESENT_BUT_UNSCORED,
    METADATA_WEIGHT,
    OCR_WEIGHT,
    completeness_score,
    field_quality_score,
    metadata_reliability_score,
    ocr_quality_score,
    overall_quality_score,
)
from .signals import (
    BoundedUnitFloat,
    CompletenessSignals,
    DocumentQualitySignals,
    FieldQualitySignals,
    MetadataReliabilitySignals,
    OCRQualitySignals,
)
from .state import QualityReason, QualityState


__all__ = [
    "BoundedUnitFloat",
    "COMPLETENESS_WEIGHT",
    "CRITICAL_UNKNOWN_REASONS",
    "CompletenessSignals",
    "DEFAULT_REQUIRED_METADATA_FIELDS",
    "DocumentMetaQualityEvaluator",
    "DocumentQualitySignals",
    "EvidenceQualityAssessment",
    "EvidenceQualityEvaluator",
    "FIELD_WEIGHT",
    "FieldQualitySignals",
    "GOOD_THRESHOLD",
    "KNOWN_DEFAULT_WHEN_PRESENT_BUT_UNSCORED",
    "METADATA_WEIGHT",
    "MetadataReliabilitySignals",
    "OCR_WEIGHT",
    "OCRQualitySignals",
    "QualityComponentScores",
    "QualityReason",
    "QualityState",
    "SEMANTIC_MINIMUM_QUALITY_SCORE",
    "StaticEvidenceQualityEvaluator",
    "build_signals_for_document",
    "completeness_score",
    "default_evaluator",
    "evaluate_signals",
    "field_quality_score",
    "metadata_reliability_score",
    "ocr_quality_score",
    "overall_quality_score",
    "should_allow_exact_reuse",
    "should_allow_semantic_finding",
]
