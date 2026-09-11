"""Tests for the turnover trend anomaly detector."""

from compliance_engine.financial import (
    MAX_ANNUAL_TREND_RATIO,
    MIN_TREND_YEARS,
    FinancialYear,
    TrendAnomaly,
    TurnoverPoint,
    detect_turnover_trend_anomaly,
)


def _t(y, v, ev="ev"):
    return TurnoverPoint(financial_year=FinancialYear.parse(y), turnover_inr_cr=v, evidence_id=ev)


def test_no_anomaly_with_fewer_than_min_years():
    out = detect_turnover_trend_anomaly([_t("2022-23", 10.0), _t("2023-24", 11.0)])
    assert out is None


def test_no_anomaly_with_stable_history():
    out = detect_turnover_trend_anomaly([
        _t("2021-22", 10.0),
        _t("2022-23", 11.0),
        _t("2023-24", 12.0),
    ])
    assert out is None


def test_anomaly_when_year_gap_present():
    out = detect_turnover_trend_anomaly([
        _t("2020-21", 10.0),
        # Missing 2021-22
        _t("2022-23", 11.0),
        _t("2023-24", 12.0),
    ])
    assert out is not None
    assert out.flag_id == "TURNOVER_TREND_ANOMALY"
    assert "missing" in out.reason.lower() or "gap" in out.reason.lower()


def test_anomaly_for_implausible_ratio():
    out = detect_turnover_trend_anomaly([
        _t("2021-22", 1.0),
        _t("2022-23", 50.0),  # 50x jump
        _t("2023-24", 51.0),
    ])
    assert out is not None
    assert out.flag_id == "TURNOVER_TREND_ANOMALY"
    assert "abrupt" in out.reason.lower() or "warrants" in out.reason.lower()


def test_anomaly_words_never_imply_fraud():
    out = detect_turnover_trend_anomaly([
        _t("2021-22", 1.0),
        _t("2022-23", 100.0),
        _t("2023-24", 200.0),
    ])
    assert out is not None
    body = out.reason.lower()
    for forbidden in ("fraud", "manipulation", "falsification", "deliberate"):
        assert forbidden not in body


def test_trend_anomaly_preserves_year_span():
    out = detect_turnover_trend_anomaly([
        _t("2020-21", 1.0),
        _t("2022-23", 100.0),
        _t("2023-24", 200.0),
    ])
    assert out is not None
    assert "2020-21" in out.financial_years
    assert "2023-24" in out.financial_years


def test_constants_match_doc():
    assert MIN_TREND_YEARS == 3
    assert MAX_ANNUAL_TREND_RATIO == 10.0
