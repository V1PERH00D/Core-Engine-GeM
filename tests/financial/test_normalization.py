"""Tests for Evidence -> FinancialProfile normalization."""

import pytest

from compliance_engine.financial import FinancialProfile, normalize_financial_profile
from compliance_engine.models import Evidence


def _ev(doc, field, value, bidder="b1", doc_type="FIN_STMT", conf=0.9):
    return Evidence(
        evidence_id=f"{doc}:{field}",
        bidder_id=bidder,
        document_id=doc,
        document_type=doc_type,
        field_name=field,
        value=value,
        confidence=conf,
    )


def test_list_rows_produce_turnover_points():
    evidence = [
        _ev("BS", "financial_year", "2023-24"),
        _ev("BS", "annual_turnovers", [
            {"financial_year": "2021-22", "turnover_inr_cr": 10.0, "confidence": 0.9},
            {"financial_year": "2022-23", "turnover_inr_cr": 12.0},
        ]),
    ]
    profile = normalize_financial_profile(evidence)
    assert len(profile.annual_turnovers) == 2
    assert {p.financial_year.canonical for p in profile.annual_turnovers} == {
        "2021-22", "2022-23"
    }


def test_scalar_turnover_uses_document_year():
    evidence = [
        _ev("BS", "financial_year", "2023-24"),
        _ev("BS", "turnover_inr_cr", 20.0),
    ]
    profile = normalize_financial_profile(evidence)
    assert len(profile.annual_turnovers) == 1
    assert profile.annual_turnovers[0].financial_year.canonical == "2023-24"


def test_scalar_turnover_without_year_is_dropped():
    evidence = [_ev("BS", "turnover_inr_cr", 20.0)]
    profile = normalize_financial_profile(evidence)
    assert profile.annual_turnovers == ()


def test_net_worth_scalar_and_list():
    evidence = [
        _ev("BS1", "financial_year", "2023-24"),
        _ev("BS1", "net_worth_inr_cr", 5.0),
        _ev("BS2", "net_worth", [
            {"financial_year": "2022-23", "value_inr_cr": 3.0},
        ]),
    ]
    profile = normalize_financial_profile(evidence)
    years = sorted(p.financial_year.canonical for p in profile.net_worth)
    assert years == ["2022-23", "2023-24"]


def test_solvency_boolean_coercion():
    evidence = [
        _ev("BS", "financial_year", "2023-24"),
        _ev("BS", "is_solvency_positive", True),
        _ev("BS2", "financial_year", "2022-23"),
        _ev("BS2", "solvency_indicator", "yes"),
    ]
    profile = normalize_financial_profile(evidence)
    flags = [s.is_solvency_positive for s in profile.solvency]
    assert True in flags
    # "yes" string is truthy; truthy -> True (deterministic bool()).
    assert all(isinstance(f, bool) for f in flags)


def test_balance_sheet_list_rows():
    evidence = [
        _ev("BS", "balance_sheets", [
            {
                "financial_year": "2023-24",
                "total_assets_inr_cr": 100.0,
                "current_assets_inr_cr": 50.0,
                "current_liabilities_inr_cr": 20.0,
            }
        ])
    ]
    profile = normalize_financial_profile(evidence)
    assert len(profile.balance_sheets) == 1
    bs = profile.balance_sheets[0]
    assert bs.total_assets_inr_cr == 100.0
    assert bs.working_capital_inr_cr is None  # not in row


def test_balance_sheet_scalar_fields_merged():
    evidence = [
        _ev("BS", "financial_year", "2023-24"),
        _ev("BS", "total_assets_inr_cr", 200.0),
        _ev("BS", "current_assets_inr_cr", 100.0),
        _ev("BS", "current_liabilities_inr_cr", 40.0),
    ]
    profile = normalize_financial_profile(evidence)
    assert len(profile.balance_sheets) == 1
    bs = profile.balance_sheets[0]
    assert bs.total_assets_inr_cr == 200.0
    assert bs.current_assets_inr_cr == 100.0


def test_audit_dict_value_is_parsed():
    evidence = [
        _ev("AUDIT", "audit", {
            "audited": True,
            "ca_udin": "ABCDE12345",
            "auditor_firm": "Test & Co",
        }),
    ]
    profile = normalize_financial_profile(evidence)
    assert profile.audit is not None
    assert profile.audit.audited is True
    assert profile.audit.ca_udin == "ABCDE12345"
    assert profile.audit.auditor_firm == "Test & Co"


def test_audit_scalar_fields_merged():
    evidence = [
        _ev("AUDIT", "audited", True),
        _ev("AUDIT", "auditor_name", "X & Associates"),
        _ev("AUDIT", "ca_udin", "ZZZ0001"),
    ]
    profile = normalize_financial_profile(evidence)
    assert profile.audit is not None
    assert profile.audit.audited is True
    assert profile.audit.auditor_name == "X & Associates"
    assert profile.audit.ca_udin == "ZZZ0001"


def test_unparseable_years_are_skipped():
    evidence = [
        _ev("BS", "financial_year", "not-a-year"),
        _ev("BS", "turnover_inr_cr", 25.0),
    ]
    profile = normalize_financial_profile(evidence)
    assert profile.annual_turnovers == ()


def test_empty_evidence_produces_empty_profile():
    profile = normalize_financial_profile([])
    assert profile.bidder_id == ""
    assert profile.annual_turnovers == ()
    assert profile.net_worth == ()
    assert profile.solvency == ()
    assert profile.balance_sheets == ()
    assert profile.audit is None
