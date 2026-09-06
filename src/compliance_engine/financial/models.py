"""Canonical typed financial-evidence models for Financial Capacity.

Money values use an explicit unit. The project convention is INR crore,
so every monetary field is suffixed ``_inr_cr`` and the unit is exposed
via :class:`MoneyUnit.INR_CRORE`. Rupees, lakhs and crores are never
mixed silently.

All monetary inputs are bounded where mathematically appropriate (e.g.
turnover and asset balances cannot be negative) and unbounded where
they legitimately can be negative (net worth, profit after tax, working
capital). ``float`` fields reject NaN and infinity (Pydantic v2 default
``allow_inf_nan=False``).

Models are frozen and forbid extra fields, so a financial record is an
immutable audit artefact exactly like ``Verification``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from compliance_engine.financial.years import normalize_financial_year
from compliance_engine.models.evidence import Confidence

# Non-negative money amount in INR crore.
NonNegative = Annotated[float, Field(ge=0.0)]


class MoneyUnit(StrEnum):
    """Explicit unit for monetary values."""

    INR_CRORE = "INR_CRORE"


class ComparisonOperator(StrEnum):
    """Supported threshold comparison operators."""

    GE = ">="
    GT = ">"
    EQ = "="
    LE = "<="
    LT = "<"

    @classmethod
    def parse(cls, value: str | None) -> "ComparisonOperator | None":
        """Return the operator for a string, or ``None`` if unsupported."""

        if value is None:
            return None
        normalized = str(value).strip()
        return _OPERATOR_BY_STRING.get(normalized, None)


_OPERATOR_BY_STRING: dict[str, ComparisonOperator] = {
    op.value: op for op in ComparisonOperator
}


class TurnoverMode(StrEnum):
    """How multiple financial years of turnover are combined."""

    AVERAGE_ANNUAL = "AVERAGE_ANNUAL"
    MINIMUM_YEAR = "MINIMUM_YEAR"

    @classmethod
    def parse(cls, value: str | None) -> "TurnoverMode | None":
        if value is None:
            return None
        normalized = str(value).strip().upper()
        for mode in cls:
            if mode.value == normalized:
                return mode
        return None


class FinancialCheck(StrEnum):
    """The single financial aspect a requirement evaluates."""

    TURNOVER = "TURNOVER"
    NET_WORTH = "NET_WORTH"
    SOLVENCY = "SOLVENCY"
    AUDIT = "AUDIT"
    BALANCE_SHEET = "BALANCE_SHEET"


class FinancialYear(BaseModel):
    """A canonical normalized financial year (``YYYY-YY``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical: str

    @property
    def start_year(self) -> int:
        return int(self.canonical[:4])

    @property
    def end_year(self) -> int:
        return self.start_year + 1

    @classmethod
    def parse(cls, value: Any) -> "FinancialYear | None":
        normalized = normalize_financial_year(value)
        if normalized is None:
            return None
        return cls(canonical=normalized)


class TurnoverPoint(BaseModel):
    """One financial year of annual turnover."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    financial_year: FinancialYear
    turnover_inr_cr: NonNegative
    evidence_id: str | None = None
    document_id: str | None = None
    confidence: Confidence | None = None


class NetWorth(BaseModel):
    """Net worth for a single financial year (can be negative)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    financial_year: FinancialYear
    value_inr_cr: float
    evidence_id: str | None = None
    document_id: str | None = None
    confidence: Confidence | None = None


class Solvency(BaseModel):
    """Solvency indicator for a single financial year."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    financial_year: FinancialYear
    is_solvency_positive: bool
    evidence_id: str | None = None
    document_id: str | None = None
    confidence: Confidence | None = None


class BalanceSheet(BaseModel):
    """Balance-sheet components for a single financial year.

    Every numeric field is optional and, when absent, must remain
    ``None`` (unavailable) rather than being fabricated.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    financial_year: FinancialYear
    total_assets_inr_cr: NonNegative | None = None
    total_liabilities_inr_cr: NonNegative | None = None
    profit_after_tax_inr_cr: float | None = None
    current_assets_inr_cr: NonNegative | None = None
    current_liabilities_inr_cr: NonNegative | None = None
    working_capital_inr_cr: float | None = None
    evidence_id: str | None = None
    document_id: str | None = None
    confidence: Confidence | None = None


class AuditInfo(BaseModel):
    """Audit and CA/UDIN information attached to submitted financials.

    CA/UDIN fields are preserved verbatim for a future authoritative
    verifier. Nothing here claims UDIN authenticity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    financial_year: FinancialYear | None = None
    audited: bool | None = None
    auditor_name: str | None = None
    auditor_firm: str | None = None
    ca_udin: str | None = None
    certificate_type: str | None = None
    certificate_date: str | None = None
    ca_name: str | None = None
    ca_membership_number: str | None = None
    certificate_subject: str | None = None
    evidence_id: str | None = None
    document_id: str | None = None
    confidence: Confidence | None = None


class FinancialProfile(BaseModel):
    """Aggregate typed financial picture for one bidder."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bidder_id: str
    annual_turnovers: tuple[TurnoverPoint, ...] = ()
    net_worth: tuple[NetWorth, ...] = ()
    solvency: tuple[Solvency, ...] = ()
    balance_sheets: tuple[BalanceSheet, ...] = ()
    audit: AuditInfo | None = None

    def turnover_for_year(self, year: FinancialYear) -> TurnoverPoint | None:
        for point in self.annual_turnovers:
            if point.financial_year.canonical == year.canonical:
                return point
        return None

    def net_worth_for_year(self, year: FinancialYear) -> NetWorth | None:
        for nw in self.net_worth:
            if nw.financial_year.canonical == year.canonical:
                return nw
        return None

    def solvency_for_year(self, year: FinancialYear) -> Solvency | None:
        for s in self.solvency:
            if s.financial_year.canonical == year.canonical:
                return s
        return None

    def balance_sheet_for_year(
        self, year: FinancialYear
    ) -> BalanceSheet | None:
        for bs in self.balance_sheets:
            if bs.financial_year.canonical == year.canonical:
                return bs
        return None


__all__ = [
    "AuditInfo",
    "BalanceSheet",
    "ComparisonOperator",
    "Confidence",
    "FinancialCheck",
    "FinancialProfile",
    "FinancialYear",
    "MoneyUnit",
    "NetWorth",
    "NonNegative",
    "Solvency",
    "TurnoverMode",
    "TurnoverPoint",
]