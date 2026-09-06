"""Centralized, documented policy constants for the bidder risk engine."""

from __future__ import annotations

from typing import Final

from compliance_engine.flags import FlagSeverity


# Severity -> numeric weight mapping.
# Weights are tuned so a single HIGH signal is enough on its own to
# drive HIGH_RISK and a single MEDIUM signal is enough on its own to
# drive REVIEW.

SEVERITY_WEIGHT_CRITICAL: Final[float] = 1.00
SEVERITY_WEIGHT_HIGH: Final[float] = 0.90
SEVERITY_WEIGHT_MEDIUM: Final[float] = 0.60
SEVERITY_WEIGHT_LOW: Final[float] = 0.30
SEVERITY_WEIGHT_INFO: Final[float] = 0.10


# Aggregation constants.

#: Cap on the total boost independent supporting signals can add.
SUPPORTING_BOOST_CAP: Final[float] = 0.30

#: Per-signal contribution before the cap is applied.
SUPPORTING_BOOST_PER_SIGNAL: Final[float] = 0.05


# Risk-state thresholds.

#: Lower bound for REVIEW state.
REVIEW_THRESHOLD: Final[float] = 0.30

#: Lower bound for HIGH_RISK state.
HIGH_RISK_THRESHOLD: Final[float] = 0.60


# INDETERMINATE policy.

#: Minimum severity of the strongest signal for a score-based HIGH_RISK
#: to take precedence over an INDETERMINATE override.
INDETERMINATE_MIN_STRONGEST_SEVERITY: Final[FlagSeverity] = FlagSeverity.MEDIUM


__all__ = [
    "HIGH_RISK_THRESHOLD",
    "INDETERMINATE_MIN_STRONGEST_SEVERITY",
    "REVIEW_THRESHOLD",
    "SEVERITY_WEIGHT_CRITICAL",
    "SEVERITY_WEIGHT_HIGH",
    "SEVERITY_WEIGHT_INFO",
    "SEVERITY_WEIGHT_LOW",
    "SEVERITY_WEIGHT_MEDIUM",
    "SUPPORTING_BOOST_CAP",
    "SUPPORTING_BOOST_PER_SIGNAL",
]