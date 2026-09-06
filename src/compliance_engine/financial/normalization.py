"""Convert canonical :class:`Evidence` records into a :class:`FinancialProfile`.

The upstream financial schema is not yet fixed, so this module defines a
documented, typed seam between generic ``Evidence`` and the typed
financial models. It supports two equivalent shapes:

* **List rows** (preferred; matches the capability matrix's
  ``annual_turnovers[]``): a single evidence field whose value is a list
  of row dictionaries, e.g. ``{"financial_year": "2023-24",
  "turnover_inr_cr": 25.0}``.
* **Scalar fields** with a sibling ``financial_year`` field on the same
  document.

Missing fields are left ``None``; values are never fabricated.
"""

from __future__ import annotations

from typing import Any, Iterable

from compliance_engine.models import Evidence

from compliance_engine.financial.models import (
    AuditInfo,
    BalanceSheet,
    FinancialProfile,
    FinancialYear,
    NetWorth,
    Solvency,
    TurnoverPoint,
)

_AUDIT_FIELDS = (
    "audited",
    "auditor_name",
    "auditor_firm",
    "ca_udin",
    "certificate_type",
    "certificate_date",
    "ca_name",
    "ca_membership_number",
    "certificate_subject",
)

_BALANCE_FIELDS = (
    "total_assets_inr_cr",
    "total_liabilities_inr_cr",
    "profit_after_tax_inr_cr",
    "current_assets_inr_cr",
    "current_liabilities_inr_cr",
    "working_capital_inr_cr",
)


def _year(value: Any) -> FinancialYear | None:
    return FinancialYear.parse(value)


def _row_year(row: dict[str, Any]) -> FinancialYear | None:
    return _year(row.get("financial_year"))


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [r for r in value if isinstance(r, dict)]
    if isinstance(value, dict):
        return [value]
    return []