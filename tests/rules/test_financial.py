"""Tests for the Financial Capacity rule against the Section 7 contract.

The rule is provider-free: tender parameters are the source of every
threshold. Values are in INR crore, financial years are canonical, and
no external government lookup is performed.
"""

import pytest

from compliance_engine.models import (
    Applicability,
    ComplianceStatus,
    Evidence,
    Requirement,
)
from compliance_engine.rules import FinancialCapacityRule


def _ev(doc, field, value, *, bidder="BIDDER_001", doc_type="FIN_STMT",
        confidence=0.9, evidence_id=None):
    return Evidence(
        evidence_id=evidence_id or f"{doc}:{field}",
        bidder_id=bidder,
        document_id=doc,
        document_type=doc_type,
        field_name=field,
        value=value,
        confidence=confidence,
    )


@pytest.fixture
def rule() -> FinancialCapacityRule:
    return FinancialCapacityRule()


def _turnover_requirement(**params):
    return Requirement(
        requirement_id="FIN_REQ_001",
        capability="Financial Capacity",
        description="Bidder must meet minimum financial capacity conditions.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected=None,
        parameters={"focus": "TURNOVER", **params},
        rule_id="FINANCIAL_CAPACITY_001",
    )


def _audit_requirement(**params):
    return Requirement(
        requirement_id="FIN_REQ_AUDIT",
        capability="Financial Capacity",
        description="Audit requirement.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected=None,
        parameters={"focus": "AUDIT", **params},
        rule_id="FINANCIAL_CAPACITY_001",
    )


def _net_worth_requirement(**params):
    return Requirement(
        requirement_id="FIN_REQ_NW",
        capability="Financial Capacity",
        description="Net worth requirement.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected=None,
        parameters={"focus": "NET_WORTH", **params},
        rule_id="FINANCIAL_CAPACITY_001",
    )


def _solvency_requirement(**params):
    return Requirement(
        requirement_id="FIN_REQ_SOL",
        capability="Financial Capacity",
        description="Solvency requirement.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected=None,
        parameters={"focus": "SOLVENCY", **params},
        rule_id="FINANCIAL_CAPACITY_001",
    )


def _compliant_turnover_evidence(bidder="BIDDER_001"):
    return [
        _ev("FIN_2021", "financial_year", "2021-22", bidder=bidder, doc_type="ITR"),
        _ev("FIN_2021", "turnover_inr_cr", 30.0, bidder=bidder, doc_type="ITR"),
        _ev("FIN_2022", "financial_year", "2022-23", bidder=bidder, doc_type="ITR"),
        _ev("FIN_2022", "turnover_inr_cr", 32.0, bidder=bidder, doc_type="ITR"),
        _ev("FIN_2023", "financial_year", "2023-24", bidder=bidder, doc_type="ITR"),
        _ev("FIN_2023", "turnover_inr_cr", 35.0, bidder=bidder, doc_type="ITR"),
    ]


def test_financial_result_contract_fields_are_preserved(rule):
    requirement = _turnover_requirement(
        minimum_turnover_inr_cr=20.0,
        turnover_operator=">=",
        turnover_mode="AVERAGE_ANNUAL",
        required_financial_years=["2021-22", "2022-23", "2023-24"],
    )
    result = rule.evaluate(_compliant_turnover_evidence(), requirement=requirement)
    assert result.requirement_id == requirement.requirement_id
    assert result.rule_id == requirement.rule_id
    assert "FIN_2021:turnover_inr_cr" in result.evidence_refs
    assert "FIN_2023:turnover_inr_cr" in result.evidence_refs
    assert isinstance(result.reason, str) and result.reason
    # Provider-free: no verification refs.
    assert result.verification_refs == []


def test_financial_capacity_passes_when_all_required_checks_are_met(rule):
    requirement = _turnover_requirement(
        minimum_turnover_inr_cr=20.0,
        turnover_operator=">=",
        turnover_mode="AVERAGE_ANNUAL",
        required_financial_years=["2021-22", "2022-23", "2023-24"],
    )
    result = rule.evaluate(_compliant_turnover_evidence(), requirement=requirement)
    assert result.status is ComplianceStatus.PASS
    assert "FIN_2021:turnover_inr_cr" in result.evidence_refs


def test_financial_capacity_fails_when_turnover_is_below_threshold(rule):
    requirement = _turnover_requirement(
        minimum_turnover_inr_cr=50.0,
        turnover_operator=">=",
        turnover_mode="AVERAGE_ANNUAL",
        required_financial_years=["2023-24"],
    )
    evidence = [
        _ev("FIN_2023", "financial_year", "2023-24", doc_type="ITR"),
        _ev("FIN_2023", "turnover_inr_cr", 5.0, doc_type="ITR"),
    ]
    result = rule.evaluate(evidence, requirement=requirement)
    assert result.status is ComplianceStatus.FAIL
    assert "TURNOVER_BELOW_THRESHOLD" in result.flags


def test_financial_capacity_fails_when_net_worth_is_below_threshold(rule):
    requirement = _net_worth_requirement(
        minimum_net_worth_inr_cr=10.0,
        required_financial_years=["2023-24"],
    )
    evidence = [
        _ev("FIN_2023", "financial_year", "2023-24", doc_type="BALANCE_SHEET"),
        _ev("FIN_2023", "net_worth_inr_cr", 2.0, doc_type="BALANCE_SHEET"),
    ]
    result = rule.evaluate(evidence, requirement=requirement)
    assert result.status is ComplianceStatus.FAIL
    assert "NET_WORTH_BELOW_THRESHOLD" in result.flags


def test_financial_capacity_requires_audited_status_when_tender_requires_it(rule):
    requirement = _audit_requirement(require_audited=True)
    evidence = [
        _ev("AUDIT", "audited", False, doc_type="AUDIT_REPORT"),
    ]
    result = rule.evaluate(evidence, requirement=requirement)
    assert result.status is ComplianceStatus.FAIL
    assert "AUDIT_EVIDENCE_MISSING" in result.flags


def test_financial_capacity_requires_financial_year_for_each_assessment_record(rule):
    """Without a financial year, the rule cannot locate the period."""
    requirement = _turnover_requirement(
        minimum_turnover_inr_cr=10.0,
        turnover_operator=">=",
        turnover_mode="AVERAGE_ANNUAL",
    )
    evidence = [_ev("X", "turnover_inr_cr", 50.0)]
    result = rule.evaluate(evidence, requirement=requirement)
    # Year missing -> rule cannot pick a period -> NOT_CHECKED.
    assert result.status in (ComplianceStatus.NOT_CHECKED, ComplianceStatus.MISSING)


def test_financial_capacity_fails_when_metrics_are_inconsistent(rule):
    """Two balance sheets for the same year with different totals -> FAIL.

    The per-document rule reports PASS for each sheet individually. The
    cross-document inconsistency is detected by
    :func:`check_financial_consistency`, which the orchestrator runs
    separately and feeds into the risk engine as
    ``FINANCIAL_DATA_INCONSISTENCY``.
    """
    from compliance_engine.financial import check_financial_consistency

    requirement = Requirement(
        requirement_id="FIN_REQ_BS",
        capability="Financial Capacity",
        description="balance sheet check",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected=None,
        parameters={
            "focus": "BALANCE_SHEET",
            "required_balance_sheet_fields": ["total_assets_inr_cr"],
            "required_financial_years": ["2023-24"],
        },
        rule_id="FINANCIAL_CAPACITY_001",
    )
    evidence = [
        _ev("BS1", "financial_year", "2023-24", doc_type="BALANCE_SHEET"),
        _ev("BS1", "total_assets_inr_cr", 100.0, doc_type="BALANCE_SHEET"),
        _ev("BS2", "financial_year", "2023-24", doc_type="BALANCE_SHEET"),
        _ev("BS2", "total_assets_inr_cr", 80.0, doc_type="BALANCE_SHEET"),
    ]
    # Per-document rule: each balance sheet alone is complete -> PASS.
    per_doc = rule.evaluate(evidence[:2], requirement=requirement)
    assert per_doc.status is ComplianceStatus.PASS

    # Cross-document consistency: the two sheets differ -> inconsistency.
    profile = rule.run_extra_checks("BIDDER_001", evidence)
    assert any(f.flag_id == "FINANCIAL_DATA_INCONSISTENCY" for f in profile)


def test_financial_capacity_fails_when_solvency_threshold_is_not_met(rule):
    requirement = _solvency_requirement(
        require_positive_solvency=True,
        required_financial_years=["2023-24"],
    )
    evidence = [
        _ev("BS_2023", "financial_year", "2023-24", doc_type="BALANCE_SHEET"),
        _ev("BS_2023", "is_solvency_positive", False, doc_type="BALANCE_SHEET"),
    ]
    result = rule.evaluate(evidence, requirement=requirement)
    assert result.status is ComplianceStatus.FAIL
    assert "SOLVENCY_REQUIREMENT_FAILED" in result.flags


def test_financial_capacity_requires_multiple_years_when_assessment_period_requires_them(rule):
    requirement = _turnover_requirement(
        minimum_turnover_inr_cr=10.0,
        turnover_operator=">=",
        turnover_mode="AVERAGE_ANNUAL",
        required_financial_years=["2021-22", "2022-23", "2023-24"],
    )
    evidence = [
        _ev("FIN_2021", "financial_year", "2021-22", doc_type="ITR"),
        _ev("FIN_2021", "turnover_inr_cr", 30.0, doc_type="ITR"),
        _ev("FIN_2023", "financial_year", "2023-24", doc_type="ITR"),
        _ev("FIN_2023", "turnover_inr_cr", 40.0, doc_type="ITR"),
    ]
    result = rule.evaluate(evidence, requirement=requirement)
    assert result.status is ComplianceStatus.MISSING
    assert "TURNOVER_DATA_MISSING" in result.flags


def test_financial_capacity_is_unverifiable_when_source_reports_not_found(rule):
    """Missing threshold -> NOT_CHECKED. Missing year -> MISSING/UNVERIFIABLE."""
    requirement = Requirement(
        requirement_id="FIN_REQ_NO_THR",
        capability="Financial Capacity",
        description="missing threshold",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected=None,
        parameters={"focus": "TURNOVER"},  # no threshold
        rule_id="FINANCIAL_CAPACITY_001",
    )
    result = rule.evaluate([], requirement=requirement)
    assert result.status in (ComplianceStatus.NOT_CHECKED, ComplianceStatus.MISSING)


def test_provider_required_for_evaluation_is_no_longer_required(rule):
    """The financial rule is provider-free; provider is accepted but unused."""
    requirement = _turnover_requirement(
        minimum_turnover_inr_cr=10.0,
        turnover_operator=">=",
        turnover_mode="AVERAGE_ANNUAL",
    )
    evidence = [
        _ev("FIN_2023", "financial_year", "2023-24", doc_type="ITR"),
        _ev("FIN_2023", "turnover_inr_cr", 25.0, doc_type="ITR"),
    ]
    # Does not raise even with provider=None.
    result = rule.evaluate(evidence, provider=None, requirement=requirement)
    assert result.status is ComplianceStatus.PASS


def test_requirement_required_for_evaluation(rule):
    """The rule requires a tender requirement object to evaluate against."""
    import pytest as _pytest
    with _pytest.raises(ValueError, match="requirement is required"):
        rule.evaluate(
            [_ev("FIN_2023", "turnover_inr_cr", 25.0)],
            provider=None,
            requirement=None,
        )
