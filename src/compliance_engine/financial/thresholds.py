"""Threshold comparison and multi-year turnover aggregation.

Thresholds always come from tender / requirement parameters. There is
no universal turnover or net-worth threshold anywhere in this engine.

The supported operators are ``>=``, ``>``, ``=``, ``<=``, ``<``. An
unsupported or ambiguous operator makes the comparison return ``None``
so the caller can emit a controlled ``UNVERIFIABLE`` / ``NOT_CHECKED``
outcome rather than guessing.

Multi-year turnover is combined using an explicit :class:`TurnoverMode`:

* ``AVERAGE_ANNUAL`` -> ``sum(selected years) / number of selected years``
* ``MINIMUM_YEAR``   -> ``minimum(selected years)``
"""

from __future__ import annotations

from typing import Sequence

from compliance_engine.financial.models import (
    ComparisonOperator,
    TurnoverMode,
    TurnoverPoint,
)


def evaluate_threshold(
    value: float | None,
    operator: str | None,
    threshold: float | None,
) -> bool | None:
    """Evaluate ``value <operator> threshold``.

    Returns ``None`` when the operator is unsupported/absent or either
    numeric is ``None``. Equality (``=``) uses a deterministic tolerance
    of ``1e-9 * max(1, |threshold|)`` so floating-point noise from an
    average does not produce a spurious failure.
    """

    op = ComparisonOperator.parse(operator)
    if op is None or value is None or threshold is None:
        return None

    if op is ComparisonOperator.GE:
        return value >= threshold
    if op is ComparisonOperator.GT:
        return value > threshold
    if op is ComparisonOperator.EQ:
        tol = 1e-9 * max(1.0, abs(threshold))
        return abs(value - threshold) <= tol
    if op is ComparisonOperator.LE:
        return value <= threshold
    if op is ComparisonOperator.LT:
        return value < threshold
    return None


def aggregate_turnover(
    points: Sequence[TurnoverPoint],
    mode: TurnoverMode | None,
) -> float | None:
    """Combine turnover points using an explicit mode.

    Returns ``None`` when there are no points or the mode is missing,
    so an absent mode never silently becomes an average or a minimum.
    """

    if mode is None or not points:
        return None

    values = [p.turnover_inr_cr for p in points]
    if mode is TurnoverMode.AVERAGE_ANNUAL:
        return sum(values) / len(values)
    if mode is TurnoverMode.MINIMUM_YEAR:
        return min(values)
    return None


def select_turnover_by_years(
    points: Sequence[TurnoverPoint],
    required_years: Sequence[str] | None,
) -> list[TurnoverPoint]:
    """Return points whose canonical year is in ``required_years``.

    When ``required_years`` is empty/``None``, all points are returned
    unchanged (selection is the caller's responsibility).
    """

    if not required_years:
        return list(points)

    required = set(required_years)
    return [p for p in points if p.financial_year.canonical in required]


__all__ = [
    "aggregate_turnover",
    "evaluate_threshold",
    "select_turnover_by_years",
]