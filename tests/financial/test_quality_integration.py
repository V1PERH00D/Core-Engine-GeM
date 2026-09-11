"""Evidence quality integration tests for financial evidence."""

import pytest

from ai_verification.evidence_quality import QualityState
from compliance_engine.financial import (
    BalanceSheet,
    FinancialProfile,
    FinancialYear,
    TurnoverPoint,
)
from compliance_engine.financial.consistency import (
    FINANCIAL_NUMERIC_TOLERANCE,
    check_financial_consistency,
)
from compliance_engine.financial.trend import detect_turnover_trend_anomaly


def _year(y):
    return FinancialYear.parse(y)


def test_high_confidence_evidence_does_not_degrade_findings():
    profile = FinancialProfile(
        bidder_id="b",
        annual_turnovers=(
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=10.0,
                          evidence_id="a", document_id="doc-A", confidence=0.99),
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=15.0,
                          evidence_id="b", document_id="doc-B", confidence=0.98),
        ),
    )
    findings = check_financial_consistency(profile)
    assert len(findings) == 1
    # The flag is still FINANCIAL_DATA_INCONSISTENCY at HIGH severity.
    assert findings[0].flag_id == "FINANCIAL_DATA_INCONSISTENCY"


def test_degraded_confidence_preserved_on_records():
    p = TurnoverPoint(
        financial_year=_year("2023-24"),
        turnover_inr_cr=10.0,
        evidence_id="a",
        confidence=0.4,  # low confidence
    )
    assert p.confidence == 0.4


def test_missing_confidence_is_none_not_zero():
    p = TurnoverPoint(
        financial_year=_year("2023-24"),
        turnover_inr_cr=10.0,
        evidence_id="a",
    )
    assert p.confidence is None


def test_unknown_quality_state_does_not_block_consistency():
    profile = FinancialProfile(
        bidder_id="b",
        annual_turnovers=(
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=10.0,
                          evidence_id="a", document_id="doc-A", confidence=None),
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=15.0,
                          evidence_id="b", document_id="doc-B", confidence=None),
        ),
    )
    findings = check_financial_consistency(profile)
    assert len(findings) == 1


def test_no_ocr_metadata_is_not_a_financial_failure():
    # The financial rule only consumes values; it doesn't depend on OCR
    # metadata. A successful evaluation with no confidence is a PASS.
    profile = FinancialProfile(
        bidder_id="b",
        annual_turnovers=(
            TurnoverPoint(financial_year=_year("2023-24"), turnover_inr_cr=25.0,
                          evidence_id="a", confidence=None),
        ),
    )
    assert profile.annual_turnovers[0].confidence is None


def test_balance_sheet_with_partial_confidence_passes():
    bs = BalanceSheet(
        financial_year=_year("2023-24"),
        total_assets_inr_cr=100.0,
        confidence=0.5,
    )
    assert bs.confidence == 0.5
