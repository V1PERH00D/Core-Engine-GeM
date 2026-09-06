"""Bidder-level compliance risk aggregation.

This subpackage provides a deterministic, auditable bidder-level
risk-aggregation layer on top of the existing compliance, AI
verification, identity, cross-bidder, and evidence-quality subsystems.

Public API
----------

* :class:`BidderRiskEngine` -- the orchestrator. Call
  :meth:`BidderRiskEngine.assess` with already-produced artefacts.
* :class:`BidderRiskAssessment` -- the immutable aggregate result.
* :class:`RiskSignal` -- the per-finding risk projection.
* :class:`CorrelationKey` -- the deterministic identity used for
  deduplication.
* :class:`RiskCategory`, :class:`RiskState`, :class:`EvidenceState`,
  :class:`ReasonCode` -- controlled taxonomies.
* :func:`ai_verification.risk.aggregation.build_assessment` -- the
  pure aggregation function (useful for tests and alternative
  compositions).
* :mod:`policy`, :mod:`severity` -- centralized numeric constants and
  severity-weight mappings.

Design constraints
------------------

* Deterministic and side-effect free.
* No network calls.
* No LLM explanation.
* No fabricated identifiers or refs.
* Immutable result models.
* Reuses canonical flag registry severities and existing
  evidence-quality assessments.
"""

from .aggregation import build_assessment
from .engine import BidderRiskEngine
from .models import (
    BidderRiskAssessment,
    CorrelationKey,
    EvidenceAvailability,
    EvidenceState,
    ReasonCode,
    RiskCategory,
    RiskSignal,
    RiskState,
)
from .severity import (
    MODERATE_SEVERITIES,
    SEVERITY_WEIGHTS,
    STRONG_SEVERITIES,
    is_strong,
    normalize_severity,
    severity_weight,
)


__all__ = [
    "BidderRiskAssessment",
    "BidderRiskEngine",
    "CorrelationKey",
    "EvidenceAvailability",
    "EvidenceState",
    "MODERATE_SEVERITIES",
    "ReasonCode",
    "RiskCategory",
    "RiskSignal",
    "RiskState",
    "SEVERITY_WEIGHTS",
    "STRONG_SEVERITIES",
    "build_assessment",
    "is_strong",
    "normalize_severity",
    "severity_weight",
]