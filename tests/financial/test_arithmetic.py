"""Tests for deterministic financial arithmetic."""

import pytest

from compliance_engine.financial import (
    BalanceSheet,
    FinancialYear,
    derived_working_capital,
    working_capital,
)


def _year():
    return FinancialYear.parse("2023-24")


def test_working_capital_subtracts_inputs():
    assert working_capital(100.0, 40.0) == 60.0


def test_working_capital_allows_negative_result():
    assert working_capital(10.0, 25.0) == -15.0


def test_working_capital_returns_none_when_either_input_missing():
    assert working_capital(None, 10.0) is None
    assert working_capital(10.0, None) is None
    assert working_capital(None, None) is None


def test_derived_working_capital_uses_balance_sheet():
    bs = BalanceSheet(
        financial_year=_year(),
        current_assets_inr_cr=80.0,
        current_liabilities_inr_cr=30.0,
    )
    assert derived_working_capital(bs) == 50.0


def test_derived_working_capital_none_when_inputs_missing():
    bs = BalanceSheet(financial_year=_year(), current_assets_inr_cr=80.0)
    assert derived_working_capital(bs) is None
