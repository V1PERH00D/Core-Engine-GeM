"""Engine integration tests for Financial Capacity."""

import pytest

from compliance_engine.engine import ComplianceEngine
from compliance_engine.models import (
    Applicability,
    ComplianceStatus,
    Evidence,
    Requirement,
)
from compliance_engine.rules import FinancialCapacityRule as RuleCls


def _ev(doc, field, value, bidder="b1", doc_type="FIN_STMT"):
    return Evidence(
        evidence_id=f"{doc}:{field}",
        bidder_id=bidder,
        document_id=doc,
        document_type=doc_type,
        field_name=field,
        value=value,
    )


def _req(req_id, params):
    return Requirement(
        requirement_id=req_id,
        capability="Financial Capacity",
        description="Financial capacity check",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected=None,
        parameters=params,
        rule_id="FINANCIAL_CAPACITY_001",
    )


def test_engine_runs_provider_free_financial_rule():
    rule = RuleCls()
    engine = ComplianceEngine(rules={rule.rule_id: rule}, providers={})
    evidence = [
        _ev("BS", "financial_year", "2023-24"),
        _ev("BS", "turnover_inr_cr", 30.0),
    ]
    result = engine.run(
        evidence=evidence,
        requirements=[_req("r1", {
            "minimum_turnover_inr_cr": 25.0,
            "turnover_operator": ">=",
            "turnover_mode": "AVERAGE_ANNUAL",
            "required_financial_years": ["2023-24"],
        })],
    )
    assert len(result.compliance_results) == 1
    assert result.compliance_results[0].status is ComplianceStatus.PASS


def test_engine_records_no_verification_refs_for_financial():
    rule = RuleCls()
    engine = ComplianceEngine(rules={rule.rule_id: rule}, providers={})
    result = engine.run(
        evidence=[_ev("BS", "turnover_inr_cr", 10.0)],
        requirements=[_req("r1", {"minimum_turnover_inr_cr": 1.0, "turnover_operator": ">="})],
    )
    assert result.compliance_results[0].verification_refs == []


def test_engine_routes_financial_to_executor_even_without_provider():
    rule = RuleCls()
    engine = ComplianceEngine(rules={rule.rule_id: rule}, providers={})
    result = engine.run(
        evidence=[],
        requirements=[_req("r1", {"minimum_turnover_inr_cr": 5.0, "turnover_operator": ">="})],
    )
    assert result.compliance_results[0].status is ComplianceStatus.MISSING


def test_engine_preserves_not_applicable_for_financial():
    rule = RuleCls()
    engine = ComplianceEngine(rules={rule.rule_id: rule}, providers={})
    result = engine.run(
        evidence=[],
        requirements=[_req("r1", {"focus": "SOLVENCY", "require_positive_solvency": False})],
    )
    assert result.compliance_results[0].status is ComplianceStatus.NOT_APPLICABLE


def test_engine_preserves_not_checked_for_financial():
    rule = RuleCls()
    engine = ComplianceEngine(rules={rule.rule_id: rule}, providers={})
    result = engine.run(evidence=[], requirements=[_req("r1", {})])
    assert result.compliance_results[0].status is ComplianceStatus.NOT_CHECKED


def test_engine_handles_unknown_focus():
    rule = RuleCls()
    engine = ComplianceEngine(rules={rule.rule_id: rule}, providers={})
    result = engine.run(
        evidence=[],
        requirements=[_req("r1", {"focus": "NONSENSE"})],
    )
    assert result.compliance_results[0].status is ComplianceStatus.NOT_CHECKED


def test_engine_bidder_id_derived_from_evidence():
    rule = RuleCls()
    engine = ComplianceEngine(rules={rule.rule_id: rule}, providers={})
    result = engine.run(
        evidence=[_ev("BS", "turnover_inr_cr", 5.0, bidder="acme")],
        requirements=[_req("r1", {"minimum_turnover_inr_cr": 1.0, "turnover_operator": ">="})],
    )
    assert result.bidder_id == "acme"


def test_run_extra_checks_returns_consistency_and_trend_findings():
    rule = RuleCls()
    evidence = [
        _ev("BS1", "financial_year", "2023-24"),
        _ev("BS1", "total_assets_inr_cr", 100.0, doc_type="BALANCE_SHEET"),
        _ev("BS2", "financial_year", "2023-24"),
        _ev("BS2", "total_assets_inr_cr", 80.0, doc_type="BALANCE_SHEET"),
    ]
    findings = rule.run_extra_checks("acme", evidence)
    assert any(f.flag_id == "FINANCIAL_DATA_INCONSISTENCY" for f in findings)


def test_run_extra_checks_trend_anomaly_when_present():
    rule = RuleCls()
    evidence = [
        _ev("BS1", "financial_year", "2021-22"),
        _ev("BS1", "turnover_inr_cr", 1.0),
        _ev("BS2", "financial_year", "2022-23"),
        _ev("BS2", "turnover_inr_cr", 100.0),
        _ev("BS3", "financial_year", "2023-24"),
        _ev("BS3", "turnover_inr_cr", 200.0),
    ]
    findings = rule.run_extra_checks("acme", evidence)
    assert any(f.flag_id == "TURNOVER_TREND_ANOMALY" for f in findings)


def test_run_extra_checks_no_findings_for_clean_history():
    rule = RuleCls()
    evidence = [
        _ev("BS1", "financial_year", "2021-22"),
        _ev("BS1", "turnover_inr_cr", 10.0),
        _ev("BS2", "financial_year", "2022-23"),
        _ev("BS2", "turnover_inr_cr", 11.0),
        _ev("BS3", "financial_year", "2023-24"),
        _ev("BS3", "turnover_inr_cr", 12.0),
    ]
    findings = rule.run_extra_checks("acme", evidence)
    assert findings == []


def test_consistency_findings_flow_to_verification_finding():
    rule = RuleCls()
    evidence = [
        _ev("BS1", "financial_year", "2023-24"),
        _ev("BS1", "total_assets_inr_cr", 100.0, doc_type="BALANCE_SHEET"),
        _ev("BS2", "financial_year", "2023-24"),
        _ev("BS2", "total_assets_inr_cr", 200.0, doc_type="BALANCE_SHEET"),
    ]
    findings = rule.run_extra_checks("acme", evidence)
    vf = findings[0]
    assert vf.bidder_id == "acme"
    assert "FINANCIAL_DATA_INCONSISTENCY" in vf.flag_id
    assert vf.evidence_refs


def test_engine_with_mixed_capability_requirements():
    """Financial alongside a provider-requiring capability still runs."""
    rule = RuleCls()
    engine = ComplianceEngine(rules={rule.rule_id: rule}, providers={})
    evidence = [
        _ev("BS", "financial_year", "2023-24"),
        _ev("BS", "turnover_inr_cr", 30.0),
    ]
    result = engine.run(
        evidence=evidence,
        requirements=[_req("r1", {"minimum_turnover_inr_cr": 10.0, "turnover_operator": ">="})],
    )
    assert len(result.compliance_results) == 1
    assert result.compliance_results[0].status is ComplianceStatus.PASS
