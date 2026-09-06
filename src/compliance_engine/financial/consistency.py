"""Deterministic financial numeric consistency across submitted evidence.

Two semantically compatible values (same financial year, same metric,
from different submitted documents) are compared with a deterministic
numeric tolerance. Only values from the same year and metric are ever
compared; unrelated periods are never mixed.

Tolerance
---------

Money is in INR crore. Two monetary values are considered consistent
when their absolute difference is ``<= FINANCIAL_NUMERIC_TOLERANCE``
(0.01 crore = ₹1 lakh), which absorbs ordinary rounding in one-decimal
or two-decimal crore figures without treating materially different
amounts as equal.

A material difference yields ``FINANCIAL_DATA_INCONSISTENCY``. Missing
or unavailable evidence never becomes a consistency failure.
"""

from __future__ import annotations

from dataclasses import dataclass

from compliance_engine.financial import flags as F
from compliance_engine.financial.models import FinancialProfile

#: Absolute tolerance for monetary comparison, in INR crore (₹1 lakh).
FINANCIAL_NUMERIC_TOLERANCE: float = 0.01


@dataclass(frozen=True)
class ConsistencyFinding:
    """One material numeric inconsistency between two evidence items."""

    metric: str
    financial_year: str
    left_value: float
    right_value: float
    left_evidence_id: str
    right_evidence_id: str
    left_document_id: str | None
    right_document_id: str | None
    formula: str = "abs(left - right) > FINANCIAL_NUMERIC_TOLERANCE"

    @property
    def flag_id(self) -> str:
        return F.FINANCIAL_DATA_INCONSISTENCY


def _within_tolerance(a: float, b: float) -> bool:
    return abs(a - b) <= FINANCIAL_NUMERIC_TOLERANCE


def _grouped(values: list[tuple[str, str | None, float, str]]) -> dict[str, list[tuple[str | None, float, str]]]:
    """Group ``(year, document_id, value, evidence_id)`` records by year."""

    grouped: dict[str, list[tuple[str | None, float, str]]] = {}
    for year, doc_id, value, ev_id in values:
        grouped.setdefault(year, []).append((doc_id, value, ev_id))
    return grouped


def _compare_year_metric(
    metric: str,
    year: str,
    records: list[tuple[str | None, float, str]],
) -> list[ConsistencyFinding]:
    """Compare all distinct-document pairs within one year/metric."""

    findings: list[ConsistencyFinding] = []
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            _, left_val, left_ev = records[i]
            right_doc, right_val, right_ev = records[j]
            left_doc = records[i][0]
            # Never compare two records from the same document.
            if left_doc is not None and right_doc is not None and left_doc == right_doc:
                continue
            if _within_tolerance(left_val, right_val):
                continue
            findings.append(
                ConsistencyFinding(
                    metric=metric,
                    financial_year=year,
                    left_value=left_val,
                    right_value=right_val,
                    left_evidence_id=left_ev,
                    right_evidence_id=right_ev,
                    left_document_id=left_doc,
                    right_document_id=right_doc,
                )
            )
    return findings


def check_financial_consistency(
    profile: FinancialProfile,
) -> list[ConsistencyFinding]:
    """Return material numeric inconsistencies within one bidder's profile.

    Compares same year + same metric across different documents for:

    * turnover
    * net worth
    * total assets
    * total liabilities
    * profit after tax
    * current assets
    * current liabilities
    """

    findings: list[ConsistencyFinding] = []

    # Turnover.
    turnovers: list[tuple[str, str | None, float, str]] = [
        (p.financial_year.canonical, p.document_id, p.turnover_inr_cr, p.evidence_id or "")
        for p in profile.annual_turnovers
    ]
    for year, records in _grouped(turnovers).items():
        findings.extend(_compare_year_metric("turnover_inr_cr", year, records))

    # Net worth.
    net_worth: list[tuple[str, str | None, float, str]] = [
        (n.financial_year.canonical, n.document_id, n.value_inr_cr, n.evidence_id or "")
        for n in profile.net_worth
    ]
    for year, records in _grouped(net_worth).items():
        findings.extend(_compare_year_metric("net_worth_inr_cr", year, records))

    # Balance-sheet components.
    components = (
        ("total_assets_inr_cr", "total_assets_inr_cr"),
        ("total_liabilities_inr_cr", "total_liabilities_inr_cr"),
        ("profit_after_tax_inr_cr", "profit_after_tax_inr_cr"),
        ("current_assets_inr_cr", "current_assets_inr_cr"),
        ("current_liabilities_inr_cr", "current_liabilities_inr_cr"),
    )
    for metric, attr in components:
        records: list[tuple[str, str | None, float, str]] = []
        for bs in profile.balance_sheets:
            value = getattr(bs, attr, None)
            if value is None:
                continue
            records.append(
                (bs.financial_year.canonical, bs.document_id, value, bs.evidence_id or "")
            )
        for year, grouped in _grouped(records).items():
            findings.extend(_compare_year_metric(metric, year, grouped))

    # Deterministic ordering.
    findings.sort(
        key=lambda f: (
            f.metric,
            f.financial_year,
            f.left_evidence_id,
            f.right_evidence_id,
        )
    )
    return findings


__all__ = [
    "FINANCIAL_NUMERIC_TOLERANCE",
    "ConsistencyFinding",
    "check_financial_consistency",
]