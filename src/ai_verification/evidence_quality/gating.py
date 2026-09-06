"""Conservative quality-gating policy.

This module decides whether an evidence-quality assessment is
strong enough to allow a *semantic / extraction-based* finding to
be emitted. It deliberately does **not** override the higher
precedence rules:

* Exact byte reuse (``SimilarityLayer.EXACT``) is never blocked
  by quality gating: a cryptographic hash equality does not
  depend on OCR quality, field confidence or any other
  extraction signal.
* Normalized-text reuse (``SimilarityLayer.NORMALIZED``) is
  equally strong and is never blocked.
* Lexical reuse (``SimilarityLayer.LEXICAL``) is gated only by
  the existing template gate; quality gating does not suppress it.
* The semantic layer (``SimilarityLayer.SEMANTIC``) is the only
  layer that is *additionally* subject to quality gating.

The reason for this asymmetry is fundamental: hash equality is
exact, lexical similarity is deterministic, and semantic
similarity depends on opaque, externally trained models that can
amplify noise. Quality gating therefore only kicks in when the
evidence pipeline is so broken that the semantic similarity
score cannot be trusted.
"""

from __future__ import annotations

from .assessment import EvidenceQualityAssessment
from .state import QualityReason, QualityState


#: Overall quality score below which the semantic layer is
#: considered unsafe. Tuned so that *known poor* quality
#: (``DEGRADED``) still permits emission, but *severely broken*
#: quality (``UNKNOWN`` with low overall score) does not.
SEMANTIC_MINIMUM_QUALITY_SCORE: float = 0.50


def should_allow_semantic_finding(
    assessment: EvidenceQualityAssessment,
) -> bool:
    """Return ``True`` iff a semantic finding may be emitted.

    The rule:

    * If the assessment is :attr:`QualityState.GOOD`, allow.
    * If the assessment is :attr:`QualityState.DEGRADED`, allow
      only if the overall quality score is at or above
      :data:`SEMANTIC_MINIMUM_QUALITY_SCORE`.
    * If the assessment is :attr:`QualityState.UNKNOWN`, deny.
    """
    if assessment.state is QualityState.GOOD:
        return True
    if assessment.state is QualityState.DEGRADED:
        return assessment.quality_score >= SEMANTIC_MINIMUM_QUALITY_SCORE
    # UNKNOWN
    return False


def should_allow_exact_reuse(
    assessment: EvidenceQualityAssessment,
) -> bool:
    """Return ``True`` iff an exact / normalized / lexical finding
    may be emitted.

    The rule: always allow. The cross-bidder detector's higher
    precedence rules already cover the cases where exact reuse
    should be suppressed (template gate mismatch, same bidder,
    missing artifact). Quality gating does not add to them.
    """
    return True


__all__ = [
    "SEMANTIC_MINIMUM_QUALITY_SCORE",
    "should_allow_exact_reuse",
    "should_allow_semantic_finding",
]
