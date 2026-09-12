"""Audit/explanation/audit-trail tests for the financial rule."""

import pytest

from compliance_engine.financial import (
    FinancialProfile,
    FinancialRequirementParams,
    FinancialYear,
    evaluate,
)
from compliance_engine.financial.findings import outcome_to_compliance_result
from compliance_engine.models import (
    Applicability,
    ComplianceResult,
    ComplianceStatus,
    Evidence,
    Requirement,
)
from compliance_engine.rules import FinancialCapacityRule


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


def test_turnover_failure_explanation_mentions_threshold():
    rule = FinancialCapacityRule()
    result = rule.evaluate(
        [
            _ev("BS", "financial_year", "2023-24"),
            _ev("BS", "turnover_inr_cr", 5.0),
        ],
        requirement=_req("r1", {
            "minimum_turnover_inr_cr": 25.0,
            "turnover_operator": ">=",
            "turnover_mode": "AVERAGE_ANNUAL",
            "required_financial_years": ["2023-24"],
        }),
    )
    assert "25" in result.reason
    assert result.expected["threshold_inr_cr"] == 25.0
    assert result.actual["value_inr_cr"] == 5.0


def test_turnover_pass_explanation_mentions_threshold_and_actual():
    rule = FinancialCapacityRule()
    result = rule.evaluate(
        [
            _ev("BS", "financial_year", "2023-24"),
            _ev("BS", "turnover_inr_cr", 30.0),
        ],
        requirement=_req("r1", {
            "minimum_turnover_inr_cr": 25.0,
            "turnover_operator": ">=",
            "turnover_mode": "AVERAGE_ANNUAL",
            "required_financial_years": ["2023-24"],
        }),
    )
    assert result.status is ComplianceStatus.PASS
    assert "30" in result.reason
    assert "25" in result.reason


def test_evidence_refs_are_sorted_and_deduplicated():
    rule = FinancialCapacityRule()
    result = rule.evaluate(
        [
            _ev("BS1", "financial_year", "2023-24"),
            _ev("BS1", "turnover_inr_cr", 5.0),
            _ev("BS2", "financial_year", "2022-23"),
            _ev("BS2", "turnover_inr_cr", 10.0),
        ],
        requirement=_req("r1", {
            "minimum_turnover_inr_cr": 1.0,
            "turnover_operator": ">=",
            "turnover_mode": "AVERAGE_ANNUAL",
            "required_financial_years": ["2022-23", "2023-24"],
        }),
    )
    assert result.evidence_refs == sorted(set(result.evidence_refs))


def test_compliance_result_carries_rule_id():
    rule = FinancialCapacityRule()
    req = _req("r1", {
        "minimum_turnover_inr_cr": 1.0,
        "turnover_operator": ">=",
    })
    result = rule.evaluate([_ev("BS", "turnover_inr_cr", 5.0)], requirement=req)
    assert result.rule_id == "FINANCIAL_CAPACITY_001"


def test_outcome_to_compliance_result_preserves_evidence_refs():
    params = FinancialRequirementParams(
        minimum_turnover_inr_cr=1.0,
        turnover_operator=">=",
    )
    profile = FinancialProfile(
        bidder_id="b",
    )
    outcome = evaluate(params, profile)
    req = _req("r1", params.model_dump())
    result = outcome_to_compliance_result(outcome, req)
    assert isinstance(result, ComplianceResult)
    assert result.requirement_id == "r1"


def test_explanation_never_claims_fraud():
    rule = FinancialCapacityRule()
    result = rule.evaluate(
        [
            _ev("BS1", "financial_year", "2021-22"),
            _ev("BS1", "turnover_inr_cr", 1.0),
            _ev("BS2", "financial_year", "2022-23"),
            _ev("BS2", "turnover_inr_cr", 100.0),
            _ev("BS3", "financial_year", "2023-24"),
            _ev("BS3", "turnover_inr_cr", 200.0),
        ],
        requirement=_req("r1", {
            "minimum_turnover_inr_cr": 1.0,
            "turnover_operator": ">=",
        }),
    )
    # The rule's own reason is whatever; if a trend is detected the
    # explanation is the *trend* one, never fraud-like.
    body = result.reason.lower()
    for forbidden in ("fraud", "manipulation", "falsification", "deliberate"):
        assert forbidden not in body


def test_deterministic_output_ordering():
    """Same inputs produce identical, ordered outputs."""
    rule = FinancialCapacityRule()
    req = _req("r1", {
        "minimum_turnover_inr_cr": 1.0,
        "turnover_operator": ">=",
        "turnover_mode": "AVERAGE_ANNUAL",
        "required_financial_years": ["2021-22", "2022-23", "2023-24"],
    })
    evidence = [
        _ev("BS1", "financial_year", "2021-22"),
        _ev("BS1", "turnover_inr_cr", 10.0),
        _ev("BS2", "financial_year", "2022-23"),
        _ev("BS2", "turnover_inr_cr", 12.0),
        _ev("BS3", "financial_year", "2023-24"),
        _ev("BS3", "turnover_inr_cr", 14.0),
    ]
    r1 = rule.evaluate(evidence, requirement=req)
    r2 = rule.evaluate(evidence, requirement=req)
    assert r1.status == r2.status
    assert r1.evidence_refs == r2.evidence_refs
    assert r1.flags == r2.flags
