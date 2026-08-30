from compliance_engine.models import (
    Applicability,
    Capability,
    ComplianceResult,
    Evidence,
    Requirement,
)
from compliance_engine.rules import GSTRegistrationRule
from compliance_engine.rules.base import Rule
from compliance_engine.verification import MockGSTProvider


class _ConcreteRule(Rule):
    rule_id = "TEST_RULE_001"
    name = "Test rule"

    def evaluate(
        self,
        evidence,
        *args,
        requirement=None,
        provider=None,
        **kwargs,
    ) -> ComplianceResult:
        return ComplianceResult(
            requirement_id=requirement.requirement_id,
            capability=requirement.capability,
            status="PASS",
            reason="ok",
            evidence_refs=[item.evidence_id for item in evidence],
            verification_refs=[],
            flags=[],
            rule_id=self.rule_id,
        )


def test_minimal_concrete_rule_satisfies_interface() -> None:
    rule = _ConcreteRule()
    requirement = Requirement(
        requirement_id="req-test-001",
        capability="TEST",
        description="Test requirement",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        rule_id=rule.rule_id,
    )
    evidence = [
        Evidence(
            evidence_id="ev-001",
            bidder_id="bidder-001",
            document_id="doc-001",
            document_type="GST",
            field_name="gstin",
            value="27AAACI1234F1Z5",
        )
    ]
    result = rule.evaluate(evidence, requirement=requirement)
    assert result.rule_id == rule.rule_id
    assert result.capability == "TEST"
    assert result.evidence_refs == ["ev-001"]


def test_gst_rule_satisfies_interface() -> None:
    rule = GSTRegistrationRule()
    assert isinstance(rule, Rule)
    assert rule.rule_id == "GST_REGISTRATION_001"
    assert rule.name == "GST registration validity"


def test_evaluate_returns_compliance_result() -> None:
    rule = GSTRegistrationRule()
    requirement = Requirement(
        requirement_id="req-gst-registration-001",
        capability=Capability.GST,
        description="GST registration must be valid and active.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="ACTIVE",
        required_evidence=["gstin"],
        required_source="GSTN",
        rule_id="GST_REGISTRATION_001",
    )
    evidence = [
        Evidence(
            evidence_id="doc-uuid-gst-001:gstin",
            bidder_id="bidder_acme_01",
            document_id="doc-uuid-gst-001",
            document_type="GST",
            field_name="gstin",
            value="27AAACI1234F1Z5",
            confidence=0.99,
            page=1,
            bbox=[50.0, 100.0, 250.0, 120.0],
        )
    ]
    result = rule.evaluate(evidence, MockGSTProvider(), requirement)
    assert result.rule_id == requirement.rule_id
    assert result.capability == requirement.capability
    assert result.requirement_id == requirement.requirement_id
    assert result.status in {"PASS", "FAIL", "MISSING", "UNVERIFIABLE"}
