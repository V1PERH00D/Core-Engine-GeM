"""Tests for threshold evaluation and turnover aggregation."""

import pytest

from compliance_engine.financial import (
    FinancialYear,
    TurnoverMode,
    TurnoverPoint,
    aggregate_turnover,
    evaluate_threshold,
    select_turnover_by_years,
)


def _t(year, value):
    return TurnoverPoint(financial_year=FinancialYear.parse(year), turnover_inr_cr=value)


@pytest.mark.parametrize(
    "value,op,thr,expected",
    [
        (10.0, ">=", 5.0, True),
        (5.0, ">=", 5.0, True),
        (4.999, ">=", 5.0, False),
        (5.0, ">", 5.0, False),
        (5.0001, ">", 5.0, True),
        (5.0, "=", 5.0, True),
        (5.0 + 1e-12, "=", 5.0, True),
        (5.001, "=", 5.0, False),
        (5.0, "<=", 5.0, True),
        (4.999, "<=", 5.0, True),
        (5.001, "<=", 5.0, False),
        (5.0, "<", 5.0, False),
        (4.999, "<", 5.0, True),
    ],
)
def test_evaluate_threshold_supported_operators(value, op, thr, expected):
    assert evaluate_threshold(value, op, thr) is expected


@pytest.mark.parametrize("op", [None, "", "==", "?", "==="])
def test_evaluate_threshold_unsupported_operator(op):
    assert evaluate_threshold(5.0, op, 5.0) is None


def test_evaluate_threshold_missing_value():
    assert evaluate_threshold(None, ">=", 5.0) is None


def test_evaluate_threshold_missing_threshold():
    assert evaluate_threshold(5.0, ">=", None) is None


def test_aggregate_turnover_average_annual():
    points = [_t("2021-22", 30.0), _t("2022-23", 40.0), _t("2023-24", 50.0)]
    assert aggregate_turnover(points, TurnoverMode.AVERAGE_ANNUAL) == 40.0


def test_aggregate_turnover_minimum_year():
    points = [_t("2021-22", 30.0), _t("2022-23", 40.0), _t("2023-24", 50.0)]
    assert aggregate_turnover(points, TurnoverMode.MINIMUM_YEAR) == 30.0


def test_aggregate_turnover_single_year_average_is_value():
    points = [_t("2023-24", 25.0)]
    assert aggregate_turnover(points, TurnoverMode.AVERAGE_ANNUAL) == 25.0


def test_aggregate_turnover_no_points_returns_none():
    assert aggregate_turnover([], TurnoverMode.AVERAGE_ANNUAL) is None


def test_aggregate_turnover_missing_mode_returns_none():
    points = [_t("2023-24", 25.0)]
    assert aggregate_turnover(points, None) is None


def test_aggregate_turnover_unknown_mode_returns_none():
    points = [_t("2023-24", 25.0)]
    assert aggregate_turnover(points, "nope") is None  # type: ignore[arg-type]


def test_select_turnover_by_years_filters_correctly():
    points = [_t("2021-22", 30.0), _t("2022-23", 40.0), _t("2023-24", 50.0)]
    selected = select_turnover_by_years(
        points, ["2021-22", "2023-24"]
    )
    canonical = [p.financial_year.canonical for p in selected]
    assert canonical == ["2021-22", "2023-24"]


def test_select_turnover_by_years_with_none_returns_all():
    points = [_t("2021-22", 30.0), _t("2022-23", 40.0)]
    assert select_turnover_by_years(points, None) == list(points)
    assert select_turnover_by_years(points, []) == list(points)
