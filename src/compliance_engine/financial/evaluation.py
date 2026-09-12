"""Deterministic financial requirement evaluation.

Each public function evaluates exactly one FinancialCheck and returns a
FinancialOutcome. The mapping of degenerate inputs to statuses is fixed:

* NOT_CHECKED    -- a required parameter is absent (missing threshold,
  missing mode for multi-year turnover, missing required field set).
* UNVERIFIABLE   -- a parameter is present but ambiguous/unsupported
  (unknown operator/mode, unparseable required year).
* MISSING        -- the required evidence is absent.
* FAIL           -- evidence is present but a deterministic comparison fails.
* PASS           -- evidence is present and every comparison holds.
* NOT_APPLICABLE -- the requirement explicitly does not apply.
"""

from __future__ import annotations

from typing import Sequence

from compliance_engine.models import ComplianceStatus

from compliance_engine.financial import flags as F
from compliance_engine.financial.arithmetic import derived_working_capital
from compliance_engine.financial.consistency import FINANCIAL_NUMERIC_TOLERANCE
from compliance_engine.financial.models import (
    ComparisonOperator,
    FinancialCheck,
    FinancialProfile,
    TurnoverMode,
)
from compliance_engine.financial.outcome import FinancialOutcome
from compliance_engine.financial.params import FinancialRequirementParams
from compliance_engine.financial.thresholds import (
    aggregate_turnover,
    evaluate_threshold,
)
from compliance_engine.financial.years import normalize_financial_year


def _normalize_required_years(raw):
    if not raw:
        return (), None
    result = []
    for y in raw:
        n = normalize_financial_year(y)
        if n is None:
            return (), f"unparseable financial year {y!r}"
        result.append(n)
    return tuple(sorted(set(result))), None


def _refs(points):
    return tuple(sorted({p.evidence_id for p in points if p.evidence_id}))


def _not_checked(check, reason):
    return FinancialOutcome(check=check, status=ComplianceStatus.NOT_CHECKED, reason=reason)


def _unverifiable(check, reason, **kw):
    return FinancialOutcome(check=check, status=ComplianceStatus.UNVERIFIABLE, reason=reason, **kw)


def _missing(check, reason):
    return FinancialOutcome(check=check, status=ComplianceStatus.MISSING, reason=reason)


def determine_focus(params):
    if params.focus:
        wanted = params.focus.strip().upper()
        for check in FinancialCheck:
            if check.value == wanted:
                return check
        return None

    signals = 0
    result = None
    if params.minimum_turnover_inr_cr is not None:
        signals += 1
        result = FinancialCheck.TURNOVER
    if params.minimum_net_worth_inr_cr is not None:
        signals += 1
        result = FinancialCheck.NET_WORTH
    if params.require_positive_solvency is not None:
        signals += 1
        result = FinancialCheck.SOLVENCY
    if params.require_audited is not None or params.require_ca_udin is not None:
        signals += 1
        result = FinancialCheck.AUDIT
    if params.required_balance_sheet_fields:
        signals += 1
        result = FinancialCheck.BALANCE_SHEET
    return result if signals == 1 else None


def evaluate(params, profile, *, focus=None):
    focus = focus if focus is not None else determine_focus(params)
    if focus is FinancialCheck.TURNOVER:
        return _evaluate_turnover(params, profile)
    if focus is FinancialCheck.NET_WORTH:
        return _evaluate_net_worth(params, profile)
    if focus is FinancialCheck.SOLVENCY:
        return _evaluate_solvency(params, profile)
    if focus is FinancialCheck.AUDIT:
        return _evaluate_audit(params, profile)
    if focus is FinancialCheck.BALANCE_SHEET:
        return _evaluate_balance_sheet(params, profile)
    return _not_checked(FinancialCheck.TURNOVER, "Unknown or ambiguous financial check.")


def _missing_turnover(check, required_years):
    return FinancialOutcome(
        check=check,
        status=ComplianceStatus.MISSING,
        reason="No annual turnover evidence is available.",
        flags=(F.TURNOVER_DATA_MISSING,),
        expected={"financial_years": required_years} if required_years else None,
        actual=None,
        financial_years=required_years,
    )


def _turnover_reason(op, value, threshold, years, mode, *, passed):
    span = (" for " + ", ".join(years)) if years else ""
    mode_text = {
        TurnoverMode.AVERAGE_ANNUAL: "average annual",
        TurnoverMode.MINIMUM_YEAR: "minimum year",
    }[mode]
    relation = "meets" if passed else "falls below"
    return (
        f"The tender requires {mode_text} turnover {op.value} ₹{threshold:g} crore"
        f"{span}. The available turnover evidence {relation} the requirement with "
        f"{mode_text} value ₹{value:g} crore."
    )


def _evaluate_turnover(params, profile):
    check = FinancialCheck.TURNOVER
    threshold = params.minimum_turnover_inr_cr
    op = ComparisonOperator.parse(params.turnover_operator)
    if op is None and threshold is None:
        return _not_checked(
            check,
            "Turnover evaluation needs at minimum a threshold and an operator; "
            "both are absent.",
        )
    if threshold is None:
        return _not_checked(check, "minimum_turnover_inr_cr is required but absent.")
    if op is None:
        return _unverifiable(
            check,
            f"Turnover operator {params.turnover_operator!r} is missing or "
            "unsupported; expected one of >=, >, =, <=, <.",
        )

    required_years, problem = _normalize_required_years(params.required_financial_years)
    if problem is not None:
        return _unverifiable(check, f"Required financial year(s) invalid: {problem}")

    points = list(profile.annual_turnovers)
    available_years = {p.financial_year.canonical for p in points}

    if required_years:
        selected = [p for p in points if p.financial_year.canonical in required_years]
        if not selected:
            if available_years:
                return FinancialOutcome(
                    check=check,
                    status=ComplianceStatus.FAIL,
                    reason=(
                        "Turnover evidence is available but does not cover any of "
                        f"the required financial years {required_years}; "
                        f"available years are {sorted(available_years)}."
                    ),
                    flags=(F.TURNOVER_PERIOD_MISMATCH,),
                    expected={"financial_years": required_years},
                    actual={"financial_years": sorted(available_years)},
                    financial_years=required_years,
                    evidence_refs=_refs(points),
                )
            return _missing_turnover(check, required_years)

        selected_years = {p.financial_year.canonical for p in selected}
        missing_required = set(required_years) - selected_years
        if missing_required:
            return FinancialOutcome(
                check=check,
                status=ComplianceStatus.MISSING,
                reason=(
                    f"Turnover evidence for required financial year(s) "
                    f"{sorted(missing_required)} is missing."
                ),
                flags=(F.TURNOVER_DATA_MISSING,),
                expected={"financial_years": required_years},
                actual={"financial_years": sorted(selected_years)},
                financial_years=required_years,
                evidence_refs=_refs(selected),
            )
    else:
        selected = points
        if not selected:
            return _missing_turnover(check, ())
        distinct = {p.financial_year.canonical for p in selected}
        if len(distinct) > 1:
            return _not_checked(
                check,
                "Multiple turnover years are present but required_financial_years is "
                "absent; cannot select a period.",
            )

    distinct_years = {p.financial_year.canonical for p in selected}
    mode = TurnoverMode.parse(params.turnover_mode)
    if len(distinct_years) > 1 and mode is None:
        return _unverifiable(
            check,
            "turnover_mode is required when multiple financial years are evaluated "
            "but is absent.",
        )
    if len(distinct_years) == 1 and mode is None:
        mode = TurnoverMode.AVERAGE_ANNUAL

    value = aggregate_turnover(selected, mode)
    if value is None:
        return _missing_turnover(check, required_years)

    years = tuple(sorted(distinct_years))
    expected = {
        "threshold_inr_cr": threshold,
        "money_unit": "INR_CRORE",
        "operator": op.value,
        "mode": mode.value,
        "financial_years": required_years or years,
    }
    actual = {
        "value_inr_cr": value,
        "money_unit": "INR_CRORE",
        "mode": mode.value,
        "financial_years": years,
    }
    passed = evaluate_threshold(value, params.turnover_operator, threshold)
    if passed:
        return FinancialOutcome(
            check=check,
            status=ComplianceStatus.PASS,
            reason=_turnover_reason(op, value, threshold, years, mode, passed=True),
            expected=expected,
            actual=actual,
            financial_years=years,
            evidence_refs=_refs(selected),
        )
    return FinancialOutcome(
        check=check,
        status=ComplianceStatus.FAIL,
        reason=_turnover_reason(op, value, threshold, years, mode, passed=False),
        expected=expected,
        actual=actual,
        flags=(F.TURNOVER_BELOW_THRESHOLD,),
        financial_years=years,
        evidence_refs=_refs(selected),
    )


def _evaluate_net_worth(params, profile):
    check = FinancialCheck.NET_WORTH
    threshold = params.minimum_net_worth_inr_cr
    if threshold is None:
        return _not_checked(check, "minimum_net_worth_inr_cr is required but absent.")

    required_years, problem = _normalize_required_years(params.required_financial_years)
    if problem is not None:
        return _unverifiable(check, f"Required financial year(s) invalid: {problem}")

    entries = list(profile.net_worth)
    if required_years:
        chosen = [e for e in entries if e.financial_year.canonical in required_years]
        if not chosen:
            if entries:
                years = sorted({e.financial_year.canonical for e in entries})
                return FinancialOutcome(
                    check=check,
                    status=ComplianceStatus.FAIL,
                    reason=(
                        f"Net worth evidence is for financial year(s) {years} but "
                        f"the requirement needs {required_years}."
                    ),
                    flags=(F.FINANCIAL_YEAR_MISMATCH,),
                    expected={"financial_years": required_years, "threshold_inr_cr": threshold},
                    actual={"financial_years": years},
                    financial_years=required_years,
                    evidence_refs=_refs(entries),
                )
            return _missing(check, "No net worth evidence is available.")
    else:
        chosen = entries
        if not chosen:
            return _missing(check, "No net worth evidence is available.")
        if len({e.financial_year.canonical for e in chosen}) > 1:
            return _not_checked(
                check,
                "Multiple net-worth years are present but required_financial_years "
                "is absent; cannot select a year.",
            )

    entry = chosen[0]
    passed = entry.value_inr_cr >= threshold
    status = ComplianceStatus.PASS if passed else ComplianceStatus.FAIL
    relation = "meets" if passed else "falls below"
    return FinancialOutcome(
        check=check,
        status=status,
        reason=(
            f"The tender requires net worth >= ₹{threshold:g} crore for "
            f"{entry.financial_year.canonical}. The available net worth evidence "
            f"records ₹{entry.value_inr_cr:g} crore, which {relation} the requirement."
        ),
        expected={
            "threshold_inr_cr": threshold,
            "operator": ">=",
            "financial_years": required_years or (entry.financial_year.canonical,),
        },
        actual={"value_inr_cr": entry.value_inr_cr, "financial_year": entry.financial_year.canonical},
        flags=(F.NET_WORTH_BELOW_THRESHOLD,) if not passed else (),
        financial_years=(entry.financial_year.canonical,),
        evidence_refs=_refs([entry]),
    )


def _evaluate_solvency(params, profile):
    check = FinancialCheck.SOLVENCY
    if params.require_positive_solvency is None:
        return _not_checked(check, "require_positive_solvency is not specified.")
    if params.require_positive_solvency is False:
        return FinancialOutcome(
            check=check,
            status=ComplianceStatus.NOT_APPLICABLE,
            reason="Positive solvency is not required by this tender.",
        )

    required_years, problem = _normalize_required_years(params.required_financial_years)
    if problem is not None:
        return _unverifiable(check, f"Required financial year(s) invalid: {problem}")

    entries = list(profile.solvency)
    if required_years:
        chosen = [e for e in entries if e.financial_year.canonical in required_years]
        if not chosen:
            if entries:
                years = sorted({e.financial_year.canonical for e in entries})
                return FinancialOutcome(
                    check=check,
                    status=ComplianceStatus.FAIL,
                    reason=(
                        f"Solvency evidence is for financial year(s) {years} but "
                        f"the requirement needs {required_years}."
                    ),
                    flags=(F.FINANCIAL_YEAR_MISMATCH,),
                    financial_years=required_years,
                    evidence_refs=_refs(entries),
                )
            return _missing(check, "No solvency evidence is available.")
    else:
        chosen = entries
        if not chosen:
            return _missing(check, "No solvency evidence is available.")
        if len({e.financial_year.canonical for e in chosen}) > 1:
            return _not_checked(
                check,
                "Multiple solvency years are present but required_financial_years "
                "is absent; cannot select a year.",
            )

    entry = chosen[0]
    if entry.is_solvency_positive:
        return FinancialOutcome(
            check=check,
            status=ComplianceStatus.PASS,
            reason=(
                "The tender requires positive solvency; the submitted evidence for "
                f"{entry.financial_year.canonical} indicates positive solvency."
            ),
            expected={"require_positive_solvency": True},
            actual={"is_solvency_positive": True},
            financial_years=(entry.financial_year.canonical,),
            evidence_refs=_refs([entry]),
        )
    return FinancialOutcome(
        check=check,
        status=ComplianceStatus.FAIL,
        reason=(
            "The tender requires positive solvency, but the submitted evidence for "
            f"{entry.financial_year.canonical} indicates the bidder is not positively "
            "solvent."
        ),
        expected={"require_positive_solvency": True},
        actual={"is_solvency_positive": False},
        flags=(F.SOLVENCY_REQUIREMENT_FAILED,),
        financial_years=(entry.financial_year.canonical,),
        evidence_refs=_refs([entry]),
    )


def _evaluate_audit(params, profile):
    check = FinancialCheck.AUDIT
    require_audited = params.require_audited is True
    require_ca = params.require_ca_udin is True
    if not require_audited and not require_ca:
        return FinancialOutcome(
            check=check,
            status=ComplianceStatus.NOT_APPLICABLE,
            reason="Audited financials are not required by this tender.",
        )

    audit = profile.audit
    if audit is None:
        return _missing(check, "No audit evidence is available.")

    refs = _refs([audit])

    if require_audited:
        if audit.audited is False:
            return FinancialOutcome(
                check=check,
                status=ComplianceStatus.FAIL,
                reason=(
                    "The tender requires audited financials, but the submitted "
                    "evidence indicates the financials are not audited."
                ),
                expected={"require_audited": True},
                actual={"audited": False},
                flags=(F.AUDIT_EVIDENCE_MISSING,),
                evidence_refs=refs,
            )
        if audit.audited is None:
            return _missing(
                check,
                "Audit evidence is present but the audited status is unavailable.",
            )

    if require_ca and not audit.ca_udin:
        return FinancialOutcome(
            check=check,
            status=ComplianceStatus.FAIL,
            reason=(
                "The tender requires CA certification with a UDIN, but no CA UDIN "
                "is present on the audit evidence."
            ),
            expected={"require_ca_udin": True},
            actual={"ca_udin": audit.ca_udin},
            flags=(F.AUDIT_EVIDENCE_MISSING,),
            evidence_refs=refs,
        )

    return FinancialOutcome(
        check=check,
        status=ComplianceStatus.PASS,
        reason="The submitted financials are audited as required.",
        expected={"require_audited": require_audited, "require_ca_udin": require_ca},
        actual={"audited": audit.audited, "ca_udin": audit.ca_udin},
        evidence_refs=refs,
    )


def _evaluate_balance_sheet(params, profile):
    check = FinancialCheck.BALANCE_SHEET
    required_fields = params.required_balance_sheet_fields
    if not required_fields:
        return _not_checked(
            check,
            "required_balance_sheet_fields is absent; cannot evaluate balance-sheet "
            "completeness.",
        )

    required_years, problem = _normalize_required_years(params.required_financial_years)
    if problem is not None:
        return _unverifiable(check, f"Required financial year(s) invalid: {problem}")

    entries = list(profile.balance_sheets)
    if required_years:
        chosen = [e for e in entries if e.financial_year.canonical in required_years]
        if not chosen:
            return _missing(check, "No balance-sheet evidence for the required year(s).")
    else:
        chosen = entries
        if not chosen:
            return _missing(check, "No balance-sheet evidence is available.")
        if len({e.financial_year.canonical for e in chosen}) > 1:
            return _not_checked(
                check,
                "Multiple balance-sheet years are present but required_financial_years "
                "is absent; cannot select a year.",
            )

    sheet = chosen[0]
    refs = _refs([sheet])
    year = sheet.financial_year.canonical

    missing_fields = [f for f in required_fields if getattr(sheet, f, None) is None]
    if missing_fields:
        return FinancialOutcome(
            check=check,
            status=ComplianceStatus.FAIL,
            reason=(
                f"Balance-sheet evidence for {year} is missing required field(s): "
                f"{', '.join(missing_fields)}."
            ),
            expected={"required_fields": tuple(required_fields)},
            actual={"missing_fields": tuple(missing_fields)},
            flags=(F.BALANCE_SHEET_INCOMPLETE,),
            financial_years=(year,),
            evidence_refs=refs,
        )

    derived = derived_working_capital(sheet)
    if sheet.working_capital_inr_cr is not None and derived is not None:
        if abs(sheet.working_capital_inr_cr - derived) > FINANCIAL_NUMERIC_TOLERANCE:
            return FinancialOutcome(
                check=check,
                status=ComplianceStatus.FAIL,
                reason=(
                    "Balance-sheet arithmetic is inconsistent: supplied working "
                    f"capital ₹{sheet.working_capital_inr_cr:g} crore does not equal "
                    f"current_assets − current_liabilities = ₹{derived:g} crore."
                ),
                expected={"working_capital_inr_cr": derived},
                actual={"working_capital_inr_cr": sheet.working_capital_inr_cr},
                flags=(F.FINANCIAL_DATA_INCONSISTENCY,),
                financial_years=(year,),
                evidence_refs=refs,
            )

    return FinancialOutcome(
        check=check,
        status=ComplianceStatus.PASS,
        reason=f"Balance-sheet evidence for {year} is complete.",
        expected={"required_fields": tuple(required_fields)},
        actual={"financial_year": year},
        financial_years=(year,),
        evidence_refs=refs,
    )


__all__ = ["determine_focus", "evaluate"]
