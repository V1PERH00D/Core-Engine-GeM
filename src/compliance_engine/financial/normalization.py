"""Convert canonical Evidence records into a FinancialProfile.

The upstream financial schema is not yet fixed, so this module defines a
documented, typed seam between generic ``Evidence`` and the typed
financial models. It supports two equivalent shapes:

* List rows (preferred): a single evidence field whose value is a list of
  row dicts, e.g. ``{"financial_year": "2023-24", "turnover_inr_cr": 25.0}``.
* Scalar fields with a sibling ``financial_year`` field on the document.

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


def normalize_financial_profile(evidence: Iterable[Evidence]) -> FinancialProfile:
    """Build a typed financial profile from generic Evidence records."""
    records = list(evidence)
    bidder_id = next((e.bidder_id for e in records if e.bidder_id), "")

    turnovers: list[TurnoverPoint] = []
    net_worth: list[NetWorth] = []
    solvency: list[Solvency] = []
    balance_sheets: list[BalanceSheet] = []
    audit: AuditInfo | None = None

    docs: dict[str, list[Evidence]] = {}
    for e in records:
        docs.setdefault(e.document_id, []).append(e)

    for doc_id, evs in docs.items():
        year = _document_year(evs)
        balance_partial: dict[FinancialYear, dict[str, float | None]] = {}
        audit_partial: dict[str, str | bool | None] = {}

        for e in evs:
            fn = e.field_name
            val = e.value

            if fn in ("financial_year", "assessment_year"):
                continue

            if fn == "annual_turnovers":
                for idx, row in enumerate(_rows(val)):
                    row_year = _row_year(row)
                    if row_year is None:
                        continue
                    value = _number(row.get("turnover_inr_cr", row.get("turnover")))
                    if value is None:
                        continue
                    turnovers.append(
                        TurnoverPoint(
                            financial_year=row_year,
                            turnover_inr_cr=value,
                            evidence_id=f"{e.evidence_id}#{idx}",
                            document_id=doc_id,
                            confidence=row.get("confidence"),
                        )
                    )
                continue

            if fn == "net_worth":
                for idx, row in enumerate(_rows(val)):
                    row_year = _row_year(row)
                    value = _number(row.get("value_inr_cr", row.get("net_worth")))
                    if row_year is None or value is None:
                        continue
                    net_worth.append(
                        NetWorth(
                            financial_year=row_year,
                            value_inr_cr=value,
                            evidence_id=f"{e.evidence_id}#{idx}",
                            document_id=doc_id,
                            confidence=row.get("confidence"),
                        )
                    )
                continue

            if fn == "solvency":
                for idx, row in enumerate(_rows(val)):
                    row_year = _row_year(row)
                    flag = row.get("is_solvency_positive", row.get("solvency_indicator"))
                    if row_year is None or flag is None:
                        continue
                    solvency.append(
                        Solvency(
                            financial_year=row_year,
                            is_solvency_positive=bool(flag),
                            evidence_id=f"{e.evidence_id}#{idx}",
                            document_id=doc_id,
                            confidence=row.get("confidence"),
                        )
                    )
                continue

            if fn in ("balance_sheets", "balance_sheet"):
                for idx, row in enumerate(_rows(val)):
                    row_year = _row_year(row)
                    if row_year is None:
                        continue
                    balance_sheets.append(
                        _balance_sheet(
                            row_year,
                            row,
                            f"{e.evidence_id}#{idx}",
                            doc_id,
                            row.get("confidence"),
                        )
                    )
                continue

            if fn == "audit":
                parsed = _parse_audit(val, e.evidence_id, doc_id, year)
                if parsed is not None and audit is None:
                    audit = parsed
                continue

            if year is not None:
                if fn in ("turnover_inr_cr", "turnover", "total_turnover_inr_cr"):
                    value = _number(val)
                    if value is not None:
                        turnovers.append(
                            TurnoverPoint(
                                financial_year=year,
                                turnover_inr_cr=value,
                                evidence_id=e.evidence_id,
                                document_id=doc_id,
                                confidence=e.confidence,
                            )
                        )
                elif fn in ("net_worth_inr_cr", "net_worth"):
                    value = _number(val)
                    if value is not None:
                        net_worth.append(
                            NetWorth(
                                financial_year=year,
                                value_inr_cr=value,
                                evidence_id=e.evidence_id,
                                document_id=doc_id,
                                confidence=e.confidence,
                            )
                        )
                elif fn in ("is_solvency_positive", "solvency_indicator"):
                    solvency.append(
                        Solvency(
                            financial_year=year,
                            is_solvency_positive=bool(val),
                            evidence_id=e.evidence_id,
                            document_id=doc_id,
                            confidence=e.confidence,
                        )
                    )
                elif fn in _BALANCE_FIELDS:
                    value = _number(val)
                    balance_partial.setdefault(year, {})[fn] = value

            if fn in _AUDIT_FIELDS:
                audit_partial[fn] = val

        for bs_year, parts in balance_partial.items():
            balance_sheets.append(
                _balance_sheet(
                    bs_year,
                    parts,
                    f"{doc_id}:balance_sheet:{bs_year.canonical}",
                    doc_id,
                    None,
                )
            )

        if audit is None and audit_partial:
            audit = AuditInfo(
                financial_year=year,
                evidence_id=f"{doc_id}:audit",
                document_id=doc_id,
                **audit_partial,
            )

    return FinancialProfile(
        bidder_id=bidder_id,
        annual_turnovers=tuple(turnovers),
        net_worth=tuple(net_worth),
        solvency=tuple(solvency),
        balance_sheets=tuple(balance_sheets),
        audit=audit,
    )


def _document_year(evs: list[Evidence]) -> FinancialYear | None:
    for e in evs:
        if e.field_name == "financial_year":
            parsed = _year(e.value)
            if parsed is not None:
                return parsed
    return None


def _balance_sheet(
    year: FinancialYear,
    row: dict[str, Any],
    evidence_id: str,
    document_id: str,
    confidence: Any,
) -> BalanceSheet:
    def num(name: str) -> float | None:
        return _number(row.get(name))

    return BalanceSheet(
        financial_year=year,
        total_assets_inr_cr=num("total_assets_inr_cr"),
        total_liabilities_inr_cr=num("total_liabilities_inr_cr"),
        profit_after_tax_inr_cr=num("profit_after_tax_inr_cr"),
        current_assets_inr_cr=num("current_assets_inr_cr"),
        current_liabilities_inr_cr=num("current_liabilities_inr_cr"),
        working_capital_inr_cr=num("working_capital_inr_cr"),
        evidence_id=evidence_id,
        document_id=document_id,
        confidence=confidence,
    )


def _parse_audit(
    value: Any,
    evidence_id: str,
    document_id: str,
    year: FinancialYear | None,
) -> AuditInfo | None:
    if not isinstance(value, dict):
        return None
    fields = {k: value[k] for k in _AUDIT_FIELDS if k in value}
    if not fields and "financial_year" not in value:
        return None
    audit_year = _row_year(value) if "financial_year" in value else year
    return AuditInfo(
        financial_year=audit_year,
        evidence_id=evidence_id,
        document_id=document_id,
        confidence=value.get("confidence"),
        **fields,
    )


__all__ = ["normalize_financial_profile"]
