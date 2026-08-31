"""Tests for the Financial Capacity rule against the Section 7 contract."""

import pytest

from compliance_engine.models import (
    Applicability,
    Capability,
    ComplianceStatus,
    Evidence,
    Requirement,
)
from compliance_engine.rules.financial import FinancialCapacityRule
from compliance_engine.verification.financial import MockFinancialProvider


@pytest.fixture
def rule():
    """Return a financial capacity rule instance."""
    return FinancialCapacityRule()


@pytest.fixture
def provider():
    """Return a deterministic mock financial provider."""
    return MockFinancialProvider()


@pytest.fixture
def bidder_id():
    """Return a bidder identifier for the test fixtures."""
    return "BIDDER_001"


@pytest.fixture
def financial_requirement():
    """Return a tender requirement covering the supported Section 7 checks."""
    return Requirement(
        requirement_id="FIN_REQ_001",
        capability=Capability.FINANCIAL,
        description="Bidder must meet minimum financial capacity conditions.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected={
            "turnover_threshold": 1000000,
            "net_worth_threshold": 500000,
            "solvency_threshold": 1.0,
            "audited_required": True,
            "assessment_period_years": 1,
        },
        parameters={
            "assessment_period_years": 1,
            "solvency_threshold": 1.0,
        },
        rule_id="FINANCIAL_CAPACITY_001",
    )


@pytest.fixture
def compliant_evidence(bidder_id):
    """Return a compliant set of financial evidence for a single year."""
    return [
        Evidence(
            evidence_id="FIN:year",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="financial_year",
            value=2023,
        ),
        Evidence(
            evidence_id="FIN:turnover",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="ITR",
            field_name="turnover",
            value=5000000,
        ),
        Evidence(
            evidence_id="FIN:net_worth",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="net_worth",
            value=2000000,
        ),
        Evidence(
            evidence_id="FIN:audited",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="AUDIT_REPORT",
            field_name="audited_status",
            value="AUDITED",
        ),
        Evidence(
            evidence_id="FIN:solvency",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="solvency_indicator",
            value=2.0,
        ),
        Evidence(
            evidence_id="FIN:assets",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="total_assets",
            value=3000000,
        ),
        Evidence(
            evidence_id="FIN:liabilities",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="total_liabilities",
            value=1000000,
        ),
        Evidence(
            evidence_id="FIN:current_assets",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="current_assets",
            value=1500000,
        ),
        Evidence(
            evidence_id="FIN:current_liabilities",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="current_liabilities",
            value=500000,
        ),
    ]


def test_financial_result_contract_fields_are_preserved(
    rule, provider, financial_requirement, compliant_evidence
):
    """The rule must preserve the key ComplianceResult contract fields required by callers."""
    result = rule.evaluate(
        compliant_evidence,
        provider=provider,
        requirement=financial_requirement,
    )

    assert result.requirement_id == financial_requirement.requirement_id
    assert result.rule_id == financial_requirement.rule_id
    assert "FIN:turnover" in result.evidence_refs
    assert "FIN:net_worth" in result.evidence_refs
    assert "FIN:audited" in result.evidence_refs
    assert len(result.verification_refs) > 0
    assert isinstance(result.reason, str)
    assert len(result.reason) > 0


def test_financial_capacity_passes_when_all_required_checks_are_met(
    rule, provider, financial_requirement, compliant_evidence
):
    """A compliant record should pass the core and conditional checks."""
    result = rule.evaluate(
        compliant_evidence,
        provider=provider,
        requirement=financial_requirement,
    )
    assert result.status is ComplianceStatus.PASS
    assert "FIN:turnover" in result.evidence_refs
    assert len(result.verification_refs) > 0


def test_financial_capacity_fails_when_turnover_is_below_threshold(
    rule, provider, financial_requirement, bidder_id
):
    """Turnover below the tender threshold should fail the requirement."""
    evidence = [
        Evidence(
            evidence_id="FIN:year",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="financial_year",
            value=2023,
        ),
        Evidence(
            evidence_id="FIN:turnover",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="ITR",
            field_name="turnover",
            value=500000,
        ),
        Evidence(
            evidence_id="FIN:net_worth",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="net_worth",
            value=2000000,
        ),
        Evidence(
            evidence_id="FIN:audited",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="AUDIT_REPORT",
            field_name="audited_status",
            value="AUDITED",
        ),
        Evidence(
            evidence_id="FIN:solvency",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="solvency_indicator",
            value=2.0,
        ),
    ]

    result = rule.evaluate(evidence, provider=provider, requirement=financial_requirement)

    assert result.status is ComplianceStatus.FAIL
    assert any(flag == "TURNOVER_BELOW_THRESHOLD" for flag in result.flags)


def test_financial_capacity_fails_when_net_worth_is_below_threshold(
    rule, provider, financial_requirement, bidder_id
):
    """Net worth below the tender threshold should fail the requirement."""
    evidence = [
        Evidence(
            evidence_id="FIN:year",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="financial_year",
            value=2023,
        ),
        Evidence(
            evidence_id="FIN:turnover",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="ITR",
            field_name="turnover",
            value=5000000,
        ),
        Evidence(
            evidence_id="FIN:net_worth",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="net_worth",
            value=100000,
        ),
        Evidence(
            evidence_id="FIN:audited",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="AUDIT_REPORT",
            field_name="audited_status",
            value="AUDITED",
        ),
        Evidence(
            evidence_id="FIN:solvency",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="solvency_indicator",
            value=2.0,
        ),
    ]

    result = rule.evaluate(evidence, provider=provider, requirement=financial_requirement)

    assert result.status is ComplianceStatus.FAIL
    assert any(flag == "NET_WORTH_BELOW_THRESHOLD" for flag in result.flags)


def test_financial_capacity_requires_audited_status_when_tender_requires_it(
    rule, provider, financial_requirement, bidder_id
):
    """If audited status is required, a missing value should fail the requirement."""
    evidence = [
        Evidence(
            evidence_id="FIN:year",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="financial_year",
            value=2023,
        ),
        Evidence(
            evidence_id="FIN:turnover",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="ITR",
            field_name="turnover",
            value=5000000,
        ),
        Evidence(
            evidence_id="FIN:net_worth",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="net_worth",
            value=2000000,
        ),
        Evidence(
            evidence_id="FIN:solvency",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="solvency_indicator",
            value=2.0,
        ),
    ]

    result = rule.evaluate(evidence, provider=provider, requirement=financial_requirement)

    assert result.status is ComplianceStatus.FAIL
    assert any(flag == "AUDITED_STATUS_MISSING" for flag in result.flags)


def test_financial_capacity_requires_financial_year_for_each_assessment_record(
    rule, provider, financial_requirement, bidder_id
):
    """A missing financial year should cause a missing-data result."""
    evidence = [
        Evidence(
            evidence_id="FIN:turnover",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="ITR",
            field_name="turnover",
            value=5000000,
        ),
        Evidence(
            evidence_id="FIN:net_worth",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="net_worth",
            value=2000000,
        ),
        Evidence(
            evidence_id="FIN:audited",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="AUDIT_REPORT",
            field_name="audited_status",
            value="AUDITED",
        ),
    ]

    result = rule.evaluate(evidence, provider=provider, requirement=financial_requirement)

    assert result.status is ComplianceStatus.MISSING
    assert any(flag == "FINANCIAL_YEAR_MISSING" for flag in result.flags)


def test_financial_capacity_fails_when_metrics_are_inconsistent(
    rule, provider, financial_requirement, bidder_id
):
    """Inconsistent total-assets/liabilities data should fail the requirement."""
    evidence = [
        Evidence(
            evidence_id="FIN:year",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="financial_year",
            value=2023,
        ),
        Evidence(
            evidence_id="FIN:turnover",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="ITR",
            field_name="turnover",
            value=5000000,
        ),
        Evidence(
            evidence_id="FIN:net_worth",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="net_worth",
            value=2000000,
        ),
        Evidence(
            evidence_id="FIN:audited",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="AUDIT_REPORT",
            field_name="audited_status",
            value="AUDITED",
        ),
        Evidence(
            evidence_id="FIN:assets",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="total_assets",
            value=1000000,
        ),
        Evidence(
            evidence_id="FIN:liabilities",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="total_liabilities",
            value=1000000,
        ),
    ]

    result = rule.evaluate(evidence, provider=provider, requirement=financial_requirement)

    assert result.status is ComplianceStatus.FAIL
    assert any(flag == "FINANCIAL_DATA_INCONSISTENCY" for flag in result.flags)


def test_financial_capacity_fails_when_solvency_threshold_is_not_met(
    rule, provider, financial_requirement, bidder_id
):
    """If a solvency threshold is specified, the actual ratio must meet it."""
    evidence = [
        Evidence(
            evidence_id="FIN:year",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="financial_year",
            value=2023,
        ),
        Evidence(
            evidence_id="FIN:turnover",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="ITR",
            field_name="turnover",
            value=5000000,
        ),
        Evidence(
            evidence_id="FIN:net_worth",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="net_worth",
            value=2000000,
        ),
        Evidence(
            evidence_id="FIN:audited",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="AUDIT_REPORT",
            field_name="audited_status",
            value="AUDITED",
        ),
        Evidence(
            evidence_id="FIN:solvency",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="solvency_indicator",
            value=0.5,
        ),
    ]

    result = rule.evaluate(evidence, provider=provider, requirement=financial_requirement)

    assert result.status is ComplianceStatus.FAIL
    assert any(flag == "SOLVENCY_THRESHOLD_NOT_MET" for flag in result.flags)


def test_financial_capacity_requires_multiple_years_when_assessment_period_requires_them(
    rule, provider, financial_requirement, bidder_id
):
    """When multiple assessment years are required, missing years should be reported."""
    financial_requirement.parameters["assessment_period_years"] = 2
    financial_requirement.expected["assessment_period_years"] = 2

    evidence = [
        Evidence(
            evidence_id="FIN:year_2023",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="financial_year",
            value=2023,
        ),
        Evidence(
            evidence_id="FIN:turnover_2023",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="ITR",
            field_name="turnover",
            value=5000000,
        ),
        Evidence(
            evidence_id="FIN:net_worth_2023",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="net_worth",
            value=2000000,
        ),
        Evidence(
            evidence_id="FIN:audited_2023",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="AUDIT_REPORT",
            field_name="audited_status",
            value="AUDITED",
        ),
    ]

    result = rule.evaluate(evidence, provider=provider, requirement=financial_requirement)

    assert result.status is ComplianceStatus.MISSING
    assert any(flag == "FINANCIAL_YEAR_MISSING" for flag in result.flags)


def test_financial_capacity_is_unverifiable_when_source_reports_not_found(
    rule, provider, financial_requirement, bidder_id
):
    """A not-found verification result should remain UNVERIFIABLE."""
    evidence = [
        Evidence(
            evidence_id="FIN:year",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="BALANCE_SHEET",
            field_name="financial_year",
            value=2023,
        ),
        Evidence(
            evidence_id="FIN:turnover",
            bidder_id=bidder_id,
            document_id="FIN_2023",
            document_type="ITR",
            field_name="turnover",
            value=0,
        ),
    ]

    result = rule.evaluate(evidence, provider=provider, requirement=financial_requirement)

    assert result.status is ComplianceStatus.UNVERIFIABLE
    assert any(flag == "FINANCIAL_CAPACITY_MISSING" for flag in result.flags)


def test_provider_required_for_evaluation(rule, financial_requirement, bidder_id):
    """The rule requires an authoritative provider to evaluate financial capacity."""
    with pytest.raises(ValueError, match="provider is required"):
        rule.evaluate(
            [
                Evidence(
                    evidence_id="FIN:turnover",
                    bidder_id=bidder_id,
                    document_id="FIN_2023",
                    document_type="ITR",
                    field_name="turnover",
                    value=5000000,
                )
            ],
            provider=None,
            requirement=financial_requirement,
        )


def test_requirement_required_for_evaluation(rule, provider, bidder_id):
    """The rule requires a tender requirement object to evaluate against."""
    with pytest.raises(ValueError, match="requirement is required"):
        rule.evaluate(
            [
                Evidence(
                    evidence_id="FIN:turnover",
                    bidder_id=bidder_id,
                    document_id="FIN_2023",
                    document_type="ITR",
                    field_name="turnover",
                    value=5000000,
                )
            ],
            provider=provider,
            requirement=None,
        )
