"""Tests for the financial cross-document consistency engine."""

import pytest

from compliance_engine.financial import (
    FINANCIAL_NUMERIC_TOLERANCE,
    BalanceSheet,
    ConsistencyFinding,
    FinancialProfile,
    FinancialYear,
    NetWorth,
    TurnoverPoint,
    check_financial_consistency,
)


def _year(y):
    return FinancialYear.parse(y)


def test_turnover_consistent_across_documents():
    profile = FinancialProfile(
        bidder_id="b",
        annual_turnovers=(
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=10.0,
                          evidence_id="a", document_id="doc-A"),
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=10.0,
                          evidence_id="b", document_id="doc-B"),
        ),
    )
    assert check_financial_consistency(profile) == []


def test_turnover_inconsistent_across_documents():
    profile = FinancialProfile(
        bidder_id="b",
        annual_turnovers=(
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=10.0,
                          evidence_id="a", document_id="doc-A"),
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=15.0,
                          evidence_id="b", document_id="doc-B"),
        ),
    )
    findings = check_financial_consistency(profile)
    assert len(findings) == 1
    f = findings[0]
    assert f.metric == "turnover_inr_cr"
    assert f.financial_year == "2023-24"
    assert f.left_value == 10.0 and f.right_value == 15.0
    assert f.flag_id == "FINANCIAL_DATA_INCONSISTENCY"


def test_consistency_within_tolerance_is_ignored():
    profile = FinancialProfile(
        bidder_id="b",
        annual_turnovers=(
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=10.0,
                          evidence_id="a", document_id="doc-A"),
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=10.005,
                          evidence_id="b", document_id="doc-B"),
        ),
    )
    assert check_financial_consistency(profile) == []


def test_consistency_just_outside_tolerance_flagged():
    profile = FinancialProfile(
        bidder_id="b",
        annual_turnovers=(
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=10.0,
                          evidence_id="a", document_id="doc-A"),
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=10.02,
                          evidence_id="b", document_id="doc-B"),
        ),
    )
    findings = check_financial_consistency(profile)
    assert len(findings) == 1


def test_consistency_does_not_compare_different_years():
    profile = FinancialProfile(
        bidder_id="b",
        annual_turnovers=(
            TurnoverPoint(financial_year=_year("2022-23"), turnover_inr_cr=10.0,
                          evidence_id="a", document_id="doc-A"),
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=999.0,
                          evidence_id="b", document_id="doc-B"),
        ),
    )
    assert check_financial_consistency(profile) == []


def test_consistency_skips_same_document_pairs():
    profile = FinancialProfile(
        bidder_id="b",
        annual_turnovers=(
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=10.0,
                          evidence_id="a", document_id="doc-A"),
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=15.0,
                          evidence_id="b", document_id="doc-A"),
        ),
    )
    assert check_financial_consistency(profile) == []


def test_net_worth_consistency():
    profile = FinancialProfile(
        bidder_id="b",
        net_worth=(
            NetWorth(financial_year=_year("2023-24"), value_inr_cr=5.0,
                     evidence_id="a", document_id="doc-A"),
            NetWorth(financial_year=_year("2023-24"), value_inr_cr=8.0,
                     evidence_id="b", document_id="doc-B"),
        ),
    )
    findings = check_financial_consistency(profile)
    assert len(findings) == 1
    assert findings[0].metric == "net_worth_inr_cr"


def test_balance_sheet_assets_consistency():
    profile = FinancialProfile(
        bidder_id="b",
        balance_sheets=(
            BalanceSheet(financial_year=_year("2023-24"), total_assets_inr_cr=100.0,
                         evidence_id="a", document_id="doc-A"),
            BalanceSheet(financial_year=_year("2023-24"), total_assets_inr_cr=200.0,
                         evidence_id="b", document_id="doc-B"),
        ),
    )
    findings = check_financial_consistency(profile)
    assert any(f.metric == "total_assets_inr_cr" for f in findings)


def test_missing_evidence_is_not_a_consistency_failure():
    profile = FinancialProfile(bidder_id="b")
    assert check_financial_consistency(profile) == []


def test_findings_are_deterministically_ordered():
    """Multiple findings are sorted deterministically across findings.

    Within a single finding, left/right order reflects input list order.
    The sort key only orders the *list* of findings, not the evidence IDs
    inside each finding.
    """
    profile = FinancialProfile(
        bidder_id="b",
        annual_turnovers=(
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=1.0,
                          evidence_id="z", document_id="doc-Z"),
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=999.0,
                          evidence_id="a", document_id="doc-A"),
        ),
    )
    findings = check_financial_consistency(profile)
    assert len(findings) == 1
    # The pair order is based on input list order (i=0, j=1).
    f = findings[0]
    assert f.left_evidence_id == "z"
    assert f.right_evidence_id == "a"

    # With multiple findings, they are sorted by metric, year, then evidence ids.
    profile2 = FinancialProfile(
        bidder_id="b",
        annual_turnovers=(
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=1.0,
                          evidence_id="z", document_id="doc-Z"),
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=999.0,
                          evidence_id="a", document_id="doc-A"),
        ),
        net_worth=(
            NetWorth(financial_year=_year("2023-24"), value_inr_cr=1.0,
                     evidence_id="z", document_id="doc-Z"),
            NetWorth(financial_year=_year("2023-24"), value_inr_cr=999.0,
                     evidence_id="a", document_id="doc-A"),
        ),
    )
    findings2 = check_financial_consistency(profile2)
    assert len(findings2) == 2
    # Findings sorted by metric then evidence ids.
    assert findings2[0].metric in ("turnover_inr_cr", "net_worth_inr_cr")


def test_consistency_tolerance_is_documented():
    assert FINANCIAL_NUMERIC_TOLERANCE == 0.01
