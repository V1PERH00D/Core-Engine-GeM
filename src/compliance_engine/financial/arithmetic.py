"""Deterministic financial arithmetic and derived metrics.

Derived metrics are computed only from present inputs and never
silently inferred from missing values. An unavailable derived metric is
represented by ``None``, not by a guessed number.
"""

from __future__ import annotations

from compliance_engine.financial.models import BalanceSheet


def working_capital(
    current_assets_inr_cr: float | None,
    current_liabilities_inr_cr: float | None,
) -> float | None:
    """``current_assets - current_liabilities`` when both are present.

    Returns ``None`` when either input is absent, so callers cannot
    mistake a partial balance sheet for a complete one.
    """

    if current_assets_inr_cr is None or current_liabilities_inr_cr is None:
        return None
    return current_assets_inr_cr - current_liabilities_inr_cr


def derived_working_capital(balance_sheet: BalanceSheet) -> float | None:
    """Derive working capital from a :class:`BalanceSheet` record."""

    return working_capital(
        balance_sheet.current_assets_inr_cr,
        balance_sheet.current_liabilities_inr_cr,
    )


__all__ = ["derived_working_capital", "working_capital"]