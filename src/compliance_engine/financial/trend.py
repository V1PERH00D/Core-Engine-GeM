"""Deterministic turnover-trend anomaly detection.

A trend anomaly is an investigative signal only. It is a ``WARNING`` and
is **never** phrased as fraud, manipulation, falsification, or
deliberate misreporting.

Signals
-------

The detector requires at least three distinct financial years of
turnover. When enough evidence exists it flags, as ``TURNOVER_TREND_ANOMALY``:

* an abrupt year-over-year transition whose magnitude ratio exceeds
  ``MAX_ANNUAL_TREND_RATIO`` (default 10.0) in either direction;
* a missing intermediate financial year inside an otherwise contiguous
  span of three or more distinct years.

With fewer than three distinct years, or with a stable sequence, no
anomaly is produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from compliance_engine.financial import flags as F
from compliance_engine.financial.models import TurnoverPoint

#: Documented heuristic: a year-over-year ratio beyond this (up or down)
#: is treated as an implausible transition warranting review.
MAX_ANNUAL_TREND_RATIO: float = 10.0

#: Minimum distinct years required before any trend analysis happens.
MIN_TREND_YEARS: int = 3


@dataclass(frozen=True)
class TrendAnomaly:
    """One turnover-trend warning signal."""

    reason: str
    financial_years: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    @property
    def flag_id(self) -> str:
        return F.TURNOVER_TREND_ANOMALY


def _year_number(start_year: int) -> int:
    return start_year


def detect_turnover_trend_anomaly(
    points: Sequence[TurnoverPoint],
) -> TrendAnomaly | None:
    """Return a warning when turnover history looks implausible.

    ``None`` means there is no anomaly to report (insufficient data or a
    stable, contiguous sequence).
    """

    # Collapse to one value per distinct year (latest document wins is
    # *not* used; if a year repeats with different values that is a
    # consistency concern handled elsewhere, so here the first distinct
    # value in year order is taken deterministically).
    by_year: dict[int, TurnoverPoint] = {}
    for p in points:
        key = p.financial_year.start_year
        if key not in by_year:
            by_year[key] = p

    ordered = sorted(by_year.items())
    if len(ordered) < MIN_TREND_YEARS:
        return None

    years = [year for year, _ in ordered]
    values = [p.turnover_inr_cr for _, p in ordered]
    refs = tuple(p.evidence_id or "" for _, p in ordered if p.evidence_id)
    canonical_years = tuple(p.financial_year.canonical for _, p in ordered)

    # Missing intermediate year (gap > 1 in the contiguous span).
    for a, b in zip(years, years[1:]):
        if b - a > 1:
            return TrendAnomaly(
                reason=(
                    "Turnover history is missing the intermediate financial "
                    f"year between {a:04d}-{a % 100 + 1:02d} and "
                    f"{b:04d}-{b % 100 + 1:02d}; this gap warrants review."
                ),
                financial_years=canonical_years,
                evidence_refs=refs,
            )

    # Abrupt transition (implausible magnitude ratio).
    for prev, curr, prev_point, curr_point in zip(values, values[1:], ordered, ordered[1:]):
        lo = min(prev, curr)
        hi = max(prev, curr)
        if lo == 0 and hi > 0:
            ratio = float("inf")
        elif lo == 0:
            ratio = 1.0
        else:
            ratio = hi / lo
        if ratio > MAX_ANNUAL_TREND_RATIO:
            a = prev_point[1].financial_year.canonical
            b = curr_point[1].financial_year.canonical
            return TrendAnomaly(
                reason=(
                    f"Turnover changed abruptly between {a} (₹{prev:g} crore) and "
                    f"{b} (₹{curr:g} crore). The year-over-year magnitude change "
                    "exceeds the documented review threshold and warrants "
                    "investigation."
                ),
                financial_years=canonical_years,
                evidence_refs=refs,
            )

    return None


__all__ = [
    "MAX_ANNUAL_TREND_RATIO",
    "MIN_TREND_YEARS",
    "TrendAnomaly",
    "detect_turnover_trend_anomaly",
]