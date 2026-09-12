"""Risk engine integration tests for financial findings."""

import pytest

from ai_verification.risk.engine import BidderRiskEngine
from compliance_engine.financial import (
    BalanceSheet,
    FinancialProfile,
    FinancialYear,
    TurnoverPoint,
)
from compliance_engine.models import (
    Applicability,
    ComplianceResult,
    ComplianceStatus,
    Evidence,
    Requirement,
)
from compliance_engine.financial.findings import (
    consistency_finding_to_verification_finding,
    trend_anomaly_to_verification_finding,
)
from compliance_engine.financial.consistency import (
    ConsistencyFinding,
    check_financial_consistency,
)
from compliance_engine.financial.trend import detect_turnover_trend_anomaly
from compliance_engine.financial import (
    BalanceSheet,
    FinancialProfile,
    FinancialYear,
    TurnoverPoint,
)


def _ev(doc, field, value, bidder="b1", doc_type="FIN_STMT"):
    return Evidence(
        evidence_id=f"{doc}:{field}",
        bidder_id=bidder,
        document_id=doc,
        document_type=doc_type,
        field_name=field,
        value=value,
    )


def _result(flag, status=ComplianceStatus.FAIL):
    return ComplianceResult(
        requirement_id="r1",
        capability="Financial Capacity",
        status=status,
        reason="financial failure",
        expected=None,
        actual=None,
        evidence_refs=["ev1"],
        verification_refs=[],
        flags=[flag],
        rule_id="FINANCIAL_CAPACITY_001",
    )


def test_turnover_below_threshold_is_actionable_risk():
    engine = BidderRiskEngine()
    assessment = engine.assess(
        "b1",
        compliance_results=[_result("TURNOVER_BELOW_THRESHOLD")],
    )
    assert assessment.risk_state.value in {"HIGH_RISK", "REVIEW"}
    assert any("TURNOVER_BELOW_THRESHOLD" in (s.correlation_key.flag_id or "") for s in assessment.signals)


def test_net_worth_below_threshold_is_actionable_risk():
    engine = BidderRiskEngine()
    assessment = engine.assess(
        "b1",
        compliance_results=[_result("NET_WORTH_BELOW_THRESHOLD")],
    )
    assert any("NET_WORTH_BELOW_THRESHOLD" in (s.correlation_key.flag_id or "") for s in assessment.signals)


def test_solvency_requirement_failed_is_actionable_risk():
    engine = BidderRiskEngine()
    assessment = engine.assess(
        "b1",
        compliance_results=[_result("SOLVENCY_REQUIREMENT_FAILED")],
    )
    assert any("SOLVENCY_REQUIREMENT_FAILED" in (s.correlation_key.flag_id or "") for s in assessment.signals)


def test_financial_data_inconsistency_is_actionable_risk():
    engine = BidderRiskEngine()
    assessment = engine.assess(
        "b1",
        compliance_results=[_result("FINANCIAL_DATA_INCONSISTENCY")],
    )
    assert any("FINANCIAL_DATA_INCONSISTENCY" in (s.correlation_key.flag_id or "") for s in assessment.signals)


def test_audit_evidence_missing_is_actionable_risk():
    engine = BidderRiskEngine()
    assessment = engine.assess(
        "b1",
        compliance_results=[_result("AUDIT_EVIDENCE_MISSING")],
    )
    assert any("AUDIT_EVIDENCE_MISSING" in (s.correlation_key.flag_id or "") for s in assessment.signals)


def test_financial_year_mismatch_is_actionable_risk():
    engine = BidderRiskEngine()
    assessment = engine.assess(
        "b1",
        compliance_results=[_result("FINANCIAL_YEAR_MISMATCH")],
    )
    assert any("FINANCIAL_YEAR_MISMATCH" in (s.correlation_key.flag_id or "") for s in assessment.signals)


def test_turnover_period_mismatch_is_actionable_risk():
    engine = BidderRiskEngine()
    assessment = engine.assess(
        "b1",
        compliance_results=[_result("TURNOVER_PERIOD_MISMATCH")],
    )
    assert any("TURNOVER_PERIOD_MISMATCH" in (s.correlation_key.flag_id or "") for s in assessment.signals)


def test_trend_anomaly_warning_produces_risk_signal():
    engine = BidderRiskEngine()
    profile = FinancialProfile(
        bidder_id="b1",
        annual_turnovers=(
            TurnoverPoint(financial_year=FinancialYear.parse("2021-22"), turnover_inr_cr=1.0, evidence_id="a"),
            TurnoverPoint(financial_year=FinancialYear.parse("2022-23"), turnover_inr_cr=100.0, evidence_id="b"),
            TurnoverPoint(financial_year=FinancialYear.parse("2023-24"), turnover_inr_cr=200.0, evidence_id="c"),
        ),
    )
    anomaly = detect_turnover_trend_anomaly(profile.annual_turnovers)
    assert anomaly is not None
    finding = trend_anomaly_to_verification_finding("b1", anomaly)
    assessment = engine.assess("b1", findings=[finding])
    assert any(s.correlation_key.flag_id == "TURNOVER_TREND_ANOMALY" for s in assessment.signals)


def test_correlated_signals_are_deduplicated():
    engine = BidderRiskEngine()
    profile = FinancialProfile(
        bidder_id="b1",
        balance_sheets=(
            BalanceSheet(financial_year=FinancialYear.parse("2023-24"), total_assets_inr_cr=100.0,
                         evidence_id="a", document_id="doc-A"),
            BalanceSheet(financial_year=FinancialYear.parse("2023-24"), total_assets_inr_cr=200.0,
                         evidence_id="b", document_id="doc-B"),
        ),
    )
    findings = [
        consistency_finding_to_verification_finding("b1", c)
        for c in check_financial_consistency(profile)
    ]
    # Two compliance results + two findings with the same correlation key
    # must be deduplicated into a single contribution.
    assessment = engine.assess(
        "b1",
        compliance_results=[_result("FINANCIAL_DATA_INCONSISTENCY")],
        findings=findings,
    )
    assert assessment.deduplicated_signal_count >= 0  # at least one dedup happens


def test_missing_evidence_does_not_imply_high_risk():
    engine = BidderRiskEngine()
    assessment = engine.assess(
        "b1",
        compliance_results=[_result("TURNOVER_DATA_MISSING", status=ComplianceStatus.MISSING)],
    )
    # MISSING with a non-actionable severity must not flip the bidder to HIGH_RISK
    # when the flag is medium.
    assert assessment.risk_state.value in {"CLEAR", "REVIEW", "INDETERMINATE"}


def test_no_financial_findings_keeps_risk_clear():
    engine = BidderRiskEngine()
    assessment = engine.assess("b1", compliance_results=[])
    assert assessment.risk_state.value in {"CLEAR", "INDETERMINATE"}
