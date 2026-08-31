"""Tests for engine provider validation."""

from typing import Any

from compliance_engine.engine import ComplianceEngine
from compliance_engine.models import (
    Applicability,
    Capability,
    ComplianceResult,
    ComplianceStatus,
    Evidence,
    Requirement,
)
from compliance_engine.rules.base import Rule
from compliance_engine.verification.base import VerificationProvider


def test_engine_validates_required_providers():
    """Test that engine validates required providers for applicable requirements."""

    # Create a mock rule with GST requirement
    class MockRuleWithGST(Rule):
        """Mock rule requiring GST provider."""

        rule_id = "MOCK_GST_RULE"
        name = "Mock GST Rule"
        required_providers = (Capability.GST,)

        def evaluate(
            self,
            evidence: list[Evidence],
            *args: Any,
            requirement: Requirement | None = None,
            provider: Any | None = None,
            **kwargs: Any,
        ) -> ComplianceResult:
            return ComplianceResult(
                requirement_id=(
                    requirement.requirement_id if requirement else "mock_req"
                ),
                capability=(
                    requirement.capability if requirement else Capability.GST
                ),
                status=ComplianceStatus.UNVERIFIABLE,
                reason="Mock GST rule placeholder",
                expected=requirement.expected if requirement else "ACTIVE",
                actual=None,
                evidence_refs=[],
                verification_refs=[],
                flags=[],
                rule_id=self.rule_id,
            )

    # Create an engine with no providers registered
    engine = ComplianceEngine(
        rules={
            "MOCK_GST_RULE": MockRuleWithGST(),
        },
        providers={},
    )

    # Create a requirement that requires GST provider
    requirement = Requirement(
        requirement_id="test_req",
        capability=Capability.GST,
        description="Test GST requirement",
        mandatory=True,
        rule_id="MOCK_GST_RULE",
        expected="ACTIVE",
        applicability=Applicability.APPLICABLE,
    )

    # Create evidence
    evidence = [
        Evidence(
            evidence_id="test_evidence",
            document_id="test_document",
            bidder_id="bidder1",
            document_type="GST",
            field_name="gst_number",
            value="1234567890",
        )
    ]

    # Run the engine
    result = engine.run(evidence, [requirement])

    # Should get a UNVERIFIABLE result because GST provider is not registered
    assert len(result.compliance_results) == 1
    assert result.compliance_results[0].status.name == "UNVERIFIABLE"
    assert (
        "No verification provider is registered for capability"
        in result.compliance_results[0].reason
    )


def test_engine_works_with_providers_registered():
    """Test that engine works normally when providers are registered."""

    # Create a mock rule with GST requirement
    class MockRuleWithGST(Rule):
        """Mock rule requiring GST provider."""

        rule_id = "MOCK_GST_RULE"
        name = "Mock GST Rule"
        required_providers = (Capability.GST,)

        def evaluate(
            self,
            evidence: list[Evidence],
            *args: Any,
            requirement: Requirement | None = None,
            provider: Any | None = None,
            **kwargs: Any,
        ) -> ComplianceResult:
            return ComplianceResult(
                requirement_id=(
                    requirement.requirement_id if requirement else "mock_req"
                ),
                capability=(
                    requirement.capability if requirement else Capability.GST
                ),
                status=ComplianceStatus.UNVERIFIABLE,
                reason="Mock GST rule placeholder",
                expected=requirement.expected if requirement else "ACTIVE",
                actual=None,
                evidence_refs=[],
                verification_refs=[],
                flags=[],
                rule_id=self.rule_id,
            )

    class MockProvider(VerificationProvider):
        """Mock provider for testing."""

        def verify(self, bidder_id: str, value: str) -> Any:
            pass

    # Create an engine with GST provider registered
    engine = ComplianceEngine(
        rules={
            "MOCK_GST_RULE": MockRuleWithGST(),
        },
        providers={
            Capability.GST: MockProvider(),
        },
    )

    # Create a requirement that requires GST provider
    requirement = Requirement(
        requirement_id="test_req",
        capability=Capability.GST,
        description="Test GST requirement",
        mandatory=True,
        rule_id="MOCK_GST_RULE",
        expected="ACTIVE",
        applicability=Applicability.APPLICABLE,
    )

    # Create evidence
    evidence = [
        Evidence(
            evidence_id="test_evidence",
            document_id="test_document",
            bidder_id="bidder1",
            document_type="GST",
            field_name="gst_number",
            value="1234567890",
        )
    ]

    # Run the engine - should not raise an exception
    result = engine.run(evidence, [requirement])

    # Should get a result
    assert len(result.compliance_results) == 1


def test_engine_handles_missing_rule_gracefully():
    """Test that engine handles missing rules gracefully."""

    # Create an engine with no providers registered and no rules for the requirement
    engine = ComplianceEngine(
        rules={},
        providers={},
    )

    # Create a requirement that requires GST provider but no rule exists
    requirement = Requirement(
        requirement_id="test_req",
        capability=Capability.GST,
        description="Test GST requirement",
        mandatory=True,
        rule_id="NONEXISTENT_RULE",
        expected="ACTIVE",
        applicability=Applicability.APPLICABLE,
    )

    # Create evidence
    evidence = [
        Evidence(
            evidence_id="test_evidence",
            document_id="test_document",
            bidder_id="bidder1",
            document_type="GST",
            field_name="gst_number",
            value="1234567890",
        )
    ]

    # Run the engine - should not raise an exception
    result = engine.run(evidence, [requirement])

    # Should get an UNVERIFIABLE result for missing rule
    assert len(result.compliance_results) == 1
    assert result.compliance_results[0].status.name == "UNVERIFIABLE"
    