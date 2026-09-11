"""Tests for the typed financial evidence models."""

import math

import pydantic
import pytest

from compliance_engine.financial.models import (
    AuditInfo,
    BalanceSheet,
    ComparisonOperator,
    FinancialCheck,
    FinancialProfile,
    FinancialYear,
    MoneyUnit,
    NetWorth,
    Solvency,
    TurnoverMode,
    TurnoverPoint,
)


def _year(y):
    return FinancialYear.parse(y)


def test_money_unit_has_only_inr_crore():
    assert set(MoneyUnit) == {MoneyUnit.INR_CRORE}


@pytest.mark.parametrize("op_str,op", [
    (">=", ComparisonOperator.GE),
    (">", ComparisonOperator.GT),
    ("=", ComparisonOperator.EQ),
    ("<=", ComparisonOperator.LE),
    ("<", ComparisonOperator.LT),
])
def test_comparison_operator_parse_supported(op_str, op):
    assert ComparisonOperator.parse(op_str) is op


@pytest.mark.parametrize("bad", [None, "", "==", "**", "eq", "=>", "  "])
def test_comparison_operator_parse_unsupported(bad):
    assert ComparisonOperator.parse(bad) is None


def test_comparison_operator_parse_strips_whitespace():
    assert ComparisonOperator.parse("  >=  ") is ComparisonOperator.GE


@pytest.mark.parametrize("mode_str,mode", [
    ("AVERAGE_ANNUAL", TurnoverMode.AVERAGE_ANNUAL),
    ("MINIMUM_YEAR", TurnoverMode.MINIMUM_YEAR),
])
def test_turnover_mode_parse_supported(mode_str, mode):
    assert TurnoverMode.parse(mode_str) is mode


@pytest.mark.parametrize("bad", [None, "", "average", "MIN", "yearly"])
def test_turnover_mode_parse_unsupported(bad):
    assert TurnoverMode.parse(bad) is None


def test_financial_check_enum_covers_known_checks():
    assert {c.value for c in FinancialCheck} == {
        "TURNOVER", "NET_WORTH", "SOLVENCY", "AUDIT", "BALANCE_SHEET"
    }


def test_turnover_point_rejects_negative_value():
    with pytest.raises(pydantic.ValidationError):
        TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=-1.0)


def test_turnover_point_rejects_nan():
    with pytest.raises(pydantic.ValidationError):
        TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=math.nan)


def test_turnover_point_rejects_infinity():
    with pytest.raises(pydantic.ValidationError):
        TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=math.inf)


def test_turnover_point_is_frozen():
    point = TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=10.0)
    with pytest.raises(Exception):
        point.turnover_inr_cr = 99.0  # type: ignore[misc]


def test_turnover_point_rejects_extra_fields():
    with pytest.raises(pydantic.ValidationError):
        TurnoverPoint(  # type: ignore[call-arg]
            financial_year=_year("2023-24"),
            turnover_inr_cr=10.0,
            unknown="x",
        )


def test_net_worth_allows_negative():
    nw = NetWorth(financial_year=_year("2023-24"), value_inr_cr=-1.5)
    assert nw.value_inr_cr == -1.5


def test_balance_sheet_partial_is_allowed():
    bs = BalanceSheet(financial_year=_year("2023-24"))
    assert bs.total_assets_inr_cr is None
    assert bs.current_liabilities_inr_cr is None


def test_balance_sheet_rejects_negative_assets():
    with pytest.raises(pydantic.ValidationError):
        BalanceSheet(financial_year=_year("2023-24"), total_assets_inr_cr=-1.0)


def test_solvency_rejects_non_boolean():
    # Pydantic v2 coerces truthy strings, so use a clearly invalid value.
    with pytest.raises(pydantic.ValidationError):
        Solvency(financial_year=_year("2023-24"), is_solvency_positive=object())  # type: ignore[arg-type]


def test_audit_info_preserves_udin_fields():
    audit = AuditInfo(
        financial_year=_year("2023-24"),
        audited=True,
        auditor_name="X & Associates",
        ca_udin="1234567890ABCDE",
        ca_membership_number="ICA0101",
        certificate_subject="Financial statements as at 31-03-2024",
    )
    assert audit.ca_udin == "1234567890ABCDE"
    assert audit.certificate_subject.startswith("Financial statements")


def test_audit_info_rejects_extra_fields():
    with pytest.raises(pydantic.ValidationError):
        AuditInfo(audited=True, surprise="x")  # type: ignore[call-arg]


def test_financial_profile_lookup_methods_match_year():
    fy = _year("2023-24")
    profile = FinancialProfile(
        bidder_id="b1",
        annual_turnovers=(TurnoverPoint(financial_year=fy, turnover_inr_cr=10.0, evidence_id="e1"),),
        net_worth=(NetWorth(financial_year=fy, value_inr_cr=5.0, evidence_id="e2"),),
        solvency=(Solvency(financial_year=fy, is_solvency_positive=True, evidence_id="e3"),),
        balance_sheets=(BalanceSheet(financial_year=fy, total_assets_inr_cr=10.0, evidence_id="e4"),),
    )
    assert profile.turnover_for_year(fy) is not None
    assert profile.net_worth_for_year(fy) is not None
    assert profile.solvency_for_year(fy) is not None
    assert profile.balance_sheet_for_year(fy) is not None
    other = _year("2024-25")
    assert profile.turnover_for_year(other) is None
    assert profile.net_worth_for_year(other) is None


def test_financial_profile_is_frozen():
    fy = _year("2023-24")
    profile = FinancialProfile(
        bidder_id="b1",
        annual_turnovers=(TurnoverPoint(financial_year=fy, turnover_inr_cr=10.0),),
    )
    with pytest.raises(Exception):
        profile.bidder_id = "other"  # type: ignore[misc]
