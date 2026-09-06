"""Severity -> numeric weight mapping.

The risk engine consumes the canonical
:class:`compliance_engine.flags.registry.FlagSeverity` enum and maps
each severity to a *deterministic* numeric weight in ``[0, 1]``.

The weights live in :mod:`risk.policy`. This module only contains the
mapping function and the strong/weak classification used by the
aggregation layer.

The mapping is conservative:

* HIGH and CRITICAL both map to a weight that is *high enough on its
  own* to drive the aggregate score across the HIGH_RISK threshold
  (``HIGH_RISK_THRESHOLD = 0.60``).
* MEDIUM maps to a weight that is high enough on its own to drive a
  REVIEW state (``REVIEW_THRESHOLD = 0.30``).
* LOW and INFO produce small weights that require supporting
  independent signals to push the score into REVIEW or HIGH_RISK.

This module does *not* invent new severities. It also does *not* try
to re-interpret INFO as LOW or vice versa: the enum is preserved
verbatim on every emitted :class:`RiskSignal` so the audit trail
matches the source flag exactly.
"""

from __future__ import annotations

from compliance_engine.flags import FlagSeverity

from .policy import (
    SEVERITY_WEIGHT_CRITICAL,
    SEVERITY_WEIGHT_HIGH,
    SEVERITY_WEIGHT_INFO,
    SEVERITY_WEIGHT_LOW,
    SEVERITY_WEIGHT_MEDIUM,
)


# ---------------------------------------------------------------------------
# Severity weight map
# ---------------------------------------------------------------------------

SEVERITY_WEIGHTS: dict[FlagSeverity, float] = {
    FlagSeverity.CRITICAL: SEVERITY_WEIGHT_CRITICAL,
    FlagSeverity.HIGH: SEVERITY_WEIGHT_HIGH,
    FlagSeverity.MEDIUM: SEVERITY_WEIGHT_MEDIUM,
    FlagSeverity.LOW: SEVERITY_WEIGHT_LOW,
    FlagSeverity.INFO: SEVERITY_WEIGHT_INFO,
}


#: Severities classified as "strong" -- i.e. a single such signal on
#: its own can drive the aggregate into HIGH_RISK.
STRONG_SEVERITIES: frozenset[FlagSeverity] = frozenset(
    {FlagSeverity.CRITICAL, FlagSeverity.HIGH}
)


#: Severities classified as "moderate" -- a single such signal can
#: drive the aggregate into REVIEW.
MODERATE_SEVERITIES: frozenset[FlagSeverity] = frozenset(
    {FlagSeverity.MEDIUM}
)


def severity_weight(severity: FlagSeverity | str) -> float:
    """Return the numeric weight for a severity.

    The function accepts either a :class:`FlagSeverity` enum member or
    the *string* form of one (because :class:`RiskSignal.severity` is a
    string for forward compatibility with arbitrary upstream severities
    that happen to share the canonical vocabulary).

    Unknown strings map to ``0.0`` so the engine never invents a
    severity weight for an unknown severity. The risk state machine
    treats a weight of zero as "no contribution".
    """

    if isinstance(severity, FlagSeverity):
        return SEVERITY_WEIGHTS.get(severity, 0.0)
    try:
        enum_value = FlagSeverity(str(severity))
    except ValueError:
        return 0.0
    return SEVERITY_WEIGHTS.get(enum_value, 0.0)


def is_strong(severity: FlagSeverity | str) -> bool:
    """Return True iff ``severity`` is classified as strong."""

    if isinstance(severity, FlagSeverity):
        return severity in STRONG_SEVERITIES
    try:
        enum_value = FlagSeverity(str(severity))
    except ValueError:
        return False
    return enum_value in STRONG_SEVERITIES


def normalize_severity(severity: FlagSeverity | str) -> FlagSeverity | None:
    """Return the canonical :class:`FlagSeverity` for ``severity``.

    Returns ``None`` when the string is not a known severity. The
    caller decides what to do with the ``None``.
    """

    if isinstance(severity, FlagSeverity):
        return severity
    try:
        return FlagSeverity(str(severity))
    except ValueError:
        return None


__all__ = [
    "MODERATE_SEVERITIES",
    "SEVERITY_WEIGHTS",
    "STRONG_SEVERITIES",
    "is_strong",
    "normalize_severity",
    "severity_weight",
]