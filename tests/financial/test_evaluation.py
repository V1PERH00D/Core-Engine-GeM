"""Tests for the deterministic financial evaluation functions."""

import pytest

from compliance_engine.financial import (
    FinancialCheck,
    FinancialProfile,
    FinancialRequirementParams,
    FinancialYear,
    NetWorth,
    Solvency,
    TurnoverPoint,
    determine_focus,
    evaluate,
)
from compliance_engine.financial.models import (
    AuditInfo,
    BalanceSheet,
)
from compliance_engine.models import ComplianceStatus


def _year(y):
    return FinancialYear.parse(y)


def _turnover(y, v, ev="ev"):
    return TurnoverPoint(financial_year=_year(y), turnover_inr_cr=v, evidence_id=ev)


def _net_worth(y, v, ev="ev-nw"):
    return NetWorth(financial_year=_year(y), value_inr_cr=v, evidence_id=ev)


def _solvency(y, positive, ev="ev-s"):
    return Solvency(financial_year=_year(y), is_solvency_positive=positive, evidence_id=ev)


# --- focus resolution -------------------------------------------------------


def test_determine_focus_uses_explicit_field():
    assert determine_focus(FinancialRequirementParams(focus="TURNOVER")) is FinancialCheck.TURNOVER


def test_determine_focus_uses_inferred_from_threshold():
    assert determine_focus(FinancialRequirementParams(minimum_turnover_inr_cr=10.0)) is FinancialCheck.TURNOVER


def test_determine_focus_ambiguous_when_multiple_present():
    assert determine_focus(
        FinancialRequirementParams(
            minimum_turnover_inr_cr=10.0,
            minimum_net_worth_inr_cr=5.0,
        )
    ) is None


def test_determine_focus_unknown_explicit_value():
    assert determine_focus(FinancialRequirementParams(focus="NOPE")) is None


# --- turnover ---------------------------------------------------------------

def test_turnover_pass_with_average_annual():
    params = FinancialRequirementParams(
        minimum_turnover_inr_cr=20.0,
        turnover_operator=">=",
        turnover_mode="AVERAGE_ANNUAL",
        required_financial_years=("2021-22", "2022-23", "2023-24"),
    )
    profile = FinancialProfile(
        bidder_id="b",
        annual_turnovers=(
            _turnover("2021-22", 20.0),
            _turnover("2022-23", 30.0),
            _turnover("2023-24", 40.0),
        ),
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.PASS
    assert out.actual["value_inr_cr"] == 30.0
    assert out.financial_years == ("2021-22", "2022-23", "2023-24")


def test_turnover_fail_with_below_threshold():
    params = FinancialRequirementParams(
        minimum_turnover_inr_cr=25.0,
        turnover_operator=">=",
        turnover_mode="AVERAGE_ANNUAL",
        required_financial_years=("2021-22", "2022-23", "2023-24"),
    )
    profile = FinancialProfile(
        bidder_id="b",
        annual_turnovers=(
            _turnover("2021-22", 10.0),
            _turnover("2022-23", 20.0),
            _turnover("2023-24", 25.0),
        ),
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.FAIL
    assert "TURNOVER_BELOW_THRESHOLD" in out.flags


def test_turnover_exact_threshold_passes_with_ge():
    params = FinancialRequirementParams(
        minimum_turnover_inr_cr=10.0,
        turnover_operator=">=",
        turnover_mode="AVERAGE_ANNUAL",
        required_financial_years=("2023-24",),
    )
    profile = FinancialProfile(
        bidder_id="b", annual_turnovers=(_turnover("2023-24", 10.0),)
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.PASS


def test_turnover_above_threshold_passes():
    params = FinancialRequirementParams(
        minimum_turnover_inr_cr=10.0,
        turnover_operator=">",
        turnover_mode="AVERAGE_ANNUAL",
        required_financial_years=("2023-24",),
    )
    profile = FinancialProfile(
        bidder_id="b", annual_turnovers=(_turnover("2023-24", 10.001),)
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.PASS


def test_turnover_period_mismatch_when_no_required_year_match():
    params = FinancialRequirementParams(
        minimum_turnover_inr_cr=10.0,
        turnover_operator=">=",
        turnover_mode="AVERAGE_ANNUAL",
        required_financial_years=("2020-21",),
    )
    profile = FinancialProfile(
        bidder_id="b", annual_turnovers=(_turnover("2023-24", 50.0),)
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.FAIL
    assert "TURNOVER_PERIOD_MISMATCH" in out.flags


def test_turnover_data_missing_when_some_required_years_absent():
    params = FinancialRequirementParams(
        minimum_turnover_inr_cr=10.0,
        turnover_operator=">=",
        turnover_mode="AVERAGE_ANNUAL",
        required_financial_years=("2021-22", "2022-23", "2023-24"),
    )
    profile = FinancialProfile(
        bidder_id="b",
        annual_turnovers=(_turnover("2021-22", 20.0), _turnover("2023-24", 25.0)),
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.MISSING
    assert "TURNOVER_DATA_MISSING" in out.flags


def test_turnover_missing_when_no_evidence():
    params = FinancialRequirementParams(
        minimum_turnover_inr_cr=10.0,
        turnover_operator=">=",
        turnover_mode="AVERAGE_ANNUAL",
    )
    out = evaluate(params, FinancialProfile(bidder_id="b"))
    assert out.status is ComplianceStatus.MISSING
    assert "TURNOVER_DATA_MISSING" in out.flags


def test_turnover_not_checked_when_threshold_missing():
    params = FinancialRequirementParams(
        turnover_operator=">=",
        turnover_mode="AVERAGE_ANNUAL",
        required_financial_years=("2023-24",),
    )
    profile = FinancialProfile(
        bidder_id="b", annual_turnovers=(_turnover("2023-24", 25.0),)
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.NOT_CHECKED


def test_turnover_unverifiable_for_unknown_operator():
    params = FinancialRequirementParams(
        minimum_turnover_inr_cr=10.0,
        turnover_operator="==",
        turnover_mode="AVERAGE_ANNUAL",
        required_financial_years=("2023-24",),
    )
    profile = FinancialProfile(
        bidder_id="b", annual_turnovers=(_turnover("2023-24", 10.0),)
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.UNVERIFIABLE


def test_turnover_unverifiable_when_multi_year_without_mode():
    params = FinancialRequirementParams(
        minimum_turnover_inr_cr=10.0,
        turnover_operator=">=",
        required_financial_years=("2021-22", "2022-23", "2023-24"),
    )
    profile = FinancialProfile(
        bidder_id="b",
        annual_turnovers=(
            _turnover("2021-22", 10.0),
            _turnover("2022-23", 10.0),
            _turnover("2023-24", 10.0),
        ),
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.UNVERIFIABLE


def test_turnover_minimum_year_mode():
    params = FinancialRequirementParams(
        minimum_turnover_inr_cr=15.0,
        turnover_operator=">=",
        turnover_mode="MINIMUM_YEAR",
        required_financial_years=("2021-22", "2022-23", "2023-24"),
    )
    profile = FinancialProfile(
        bidder_id="b",
        annual_turnovers=(
            _turnover("2021-22", 30.0),
            _turnover("2022-23", 12.0),
            _turnover("2023-24", 20.0),
        ),
    )
    out = evaluate(params, profile)
    assert out.actual["value_inr_cr"] == 12.0
    assert out.status is ComplianceStatus.FAIL
    assert "TURNOVER_BELOW_THRESHOLD" in out.flags


def test_turnover_unparseable_required_year_is_unverifiable():
    params = FinancialRequirementParams(
        minimum_turnover_inr_cr=10.0,
        turnover_operator=">=",
        turnover_mode="AVERAGE_ANNUAL",
        required_financial_years=("bogus",),
    )
    profile = FinancialProfile(
        bidder_id="b", annual_turnovers=(_turnover("2023-24", 50.0),)
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.UNVERIFIABLE


# --- net worth --------------------------------------------------------------

def test_net_worth_pass():
    params = FinancialRequirementParams(
        minimum_net_worth_inr_cr=5.0,
        required_financial_years=("2023-24",),
    )
    profile = FinancialProfile(bidder_id="b", net_worth=(_net_worth("2023-24", 8.0),))
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.PASS


def test_net_worth_fail():
    params = FinancialRequirementParams(
        minimum_net_worth_inr_cr=10.0,
        required_financial_years=("2023-24",),
    )
    profile = FinancialProfile(bidder_id="b", net_worth=(_net_worth("2023-24", 5.0),))
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.FAIL
    assert "NET_WORTH_BELOW_THRESHOLD" in out.flags


def test_net_worth_missing():
    params = FinancialRequirementParams(
        minimum_net_worth_inr_cr=10.0,
        required_financial_years=("2023-24",),
    )
    out = evaluate(params, FinancialProfile(bidder_id="b"))
    assert out.status is ComplianceStatus.MISSING


def test_net_worth_year_mismatch():
    params = FinancialRequirementParams(
        minimum_net_worth_inr_cr=10.0,
        required_financial_years=("2020-21",),
    )
    profile = FinancialProfile(bidder_id="b", net_worth=(_net_worth("2023-24", 50.0),))
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.FAIL
    assert "FINANCIAL_YEAR_MISMATCH" in out.flags


def test_net_worth_missing_threshold():
    params = FinancialRequirementParams(required_financial_years=("2023-24",))
    profile = FinancialProfile(bidder_id="b", net_worth=(_net_worth("2023-24", 5.0),))
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.NOT_CHECKED


# --- solvency ---------------------------------------------------------------

def test_solvency_pass():
    params = FinancialRequirementParams(
        require_positive_solvency=True, required_financial_years=("2023-24",),
    )
    profile = FinancialProfile(bidder_id="b", solvency=(_solvency("2023-24", True),))
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.PASS


def test_solvency_fail():
    params = FinancialRequirementParams(
        require_positive_solvency=True, required_financial_years=("2023-24",),
    )
    profile = FinancialProfile(bidder_id="b", solvency=(_solvency("2023-24", False),))
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.FAIL
    assert "SOLVENCY_REQUIREMENT_FAILED" in out.flags


def test_solvency_not_applicable_when_not_required():
    params = FinancialRequirementParams(
        require_positive_solvency=False, required_financial_years=("2023-24",),
    )
    out = evaluate(params, FinancialProfile(bidder_id="b"))
    assert out.status is ComplianceStatus.NOT_APPLICABLE


def test_solvency_missing():
    params = FinancialRequirementParams(
        require_positive_solvency=True, required_financial_years=("2023-24",),
    )
    out = evaluate(params, FinancialProfile(bidder_id="b"))
    assert out.status is ComplianceStatus.MISSING


# --- audit ------------------------------------------------------------------

def test_audit_pass_when_audited():
    params = FinancialRequirementParams(require_audited=True)
    profile = FinancialProfile(
        bidder_id="b", audit=AuditInfo(audited=True, evidence_id="ev-audit"),
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.PASS


def test_audit_fail_when_not_audited():
    params = FinancialRequirementParams(require_audited=True)
    profile = FinancialProfile(
        bidder_id="b", audit=AuditInfo(audited=False, evidence_id="ev-audit"),
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.FAIL
    assert "AUDIT_EVIDENCE_MISSING" in out.flags


def test_audit_missing_evidence():
    params = FinancialRequirementParams(require_audited=True)
    out = evaluate(params, FinancialProfile(bidder_id="b"))
    assert out.status is ComplianceStatus.MISSING


def test_audit_not_applicable_when_not_required():
    # Empty params: focus cannot be determined -> NOT_CHECKED.
    out = evaluate(FinancialRequirementParams(), FinancialProfile(bidder_id="b"))
    assert out.status is ComplianceStatus.NOT_CHECKED

    # With explicit focus=AUDIT and no requirement on audited/CA -> NOT_APPLICABLE.
    out = evaluate(
        FinancialRequirementParams(focus="AUDIT"),
        FinancialProfile(bidder_id="b"),
    )
    assert out.status is ComplianceStatus.NOT_APPLICABLE


def test_audit_requires_ca_udin_when_requested():
    params = FinancialRequirementParams(require_ca_udin=True, require_audited=True)
    profile = FinancialProfile(
        bidder_id="b",
        audit=AuditInfo(audited=True, ca_udin="UDIN0001", evidence_id="ev-a"),
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.PASS


def test_audit_fails_when_ca_udin_missing():
    params = FinancialRequirementParams(require_ca_udin=True, require_audited=True)
    profile = FinancialProfile(
        bidder_id="b", audit=AuditInfo(audited=True, evidence_id="ev-a"),
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.FAIL
    assert "AUDIT_EVIDENCE_MISSING" in out.flags


# --- balance sheet ----------------------------------------------------------

def test_balance_sheet_complete():
    params = FinancialRequirementParams(
        required_balance_sheet_fields=("total_assets_inr_cr", "current_assets_inr_cr", "current_liabilities_inr_cr"),
        required_financial_years=("2023-24",),
    )
    profile = FinancialProfile(
        bidder_id="b",
        balance_sheets=(BalanceSheet(
            financial_year=_year("2023-24"),
            total_assets_inr_cr=100.0,
            current_assets_inr_cr=50.0,
            current_liabilities_inr_cr=20.0,
        ),),
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.PASS


def test_balance_sheet_incomplete():
    params = FinancialRequirementParams(
        required_balance_sheet_fields=("total_assets_inr_cr", "profit_after_tax_inr_cr"),
        required_financial_years=("2023-24",),
    )
    profile = FinancialProfile(
        bidder_id="b",
        balance_sheets=(BalanceSheet(financial_year=_year("2023-24"), total_assets_inr_cr=100.0),),
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.FAIL
    assert "BALANCE_SHEET_INCOMPLETE" in out.flags


def test_balance_sheet_arithmetic_inconsistency():
    params = FinancialRequirementParams(
        required_balance_sheet_fields=("current_assets_inr_cr", "current_liabilities_inr_cr", "working_capital_inr_cr"),
        required_financial_years=("2023-24",),
    )
    profile = FinancialProfile(
        bidder_id="b",
        balance_sheets=(BalanceSheet(
            financial_year=_year("2023-24"),
            current_assets_inr_cr=50.0,
            current_liabilities_inr_cr=20.0,
            working_capital_inr_cr=999.0,
        ),),
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.FAIL
    assert "FINANCIAL_DATA_INCONSISTENCY" in out.flags


def test_balance_sheet_not_checked_without_required_fields():
    params = FinancialRequirementParams(required_financial_years=("2023-24",))
    profile = FinancialProfile(
        bidder_id="b",
        balance_sheets=(BalanceSheet(financial_year=_year("2023-24"), total_assets_inr_cr=10.0),),
    )
    out = evaluate(params, profile)
    assert out.status is ComplianceStatus.NOT_CHECKED


def test_balance_sheet_missing():
    params = FinancialRequirementParams(
        required_balance_sheet_fields=("total_assets_inr_cr",),
        required_financial_years=("2023-24",),
    )
    out = evaluate(params, FinancialProfile(bidder_id="b"))
    assert out.status is ComplianceStatus.MISSING
