"""Tests for the RequirementExecutor."""

from typing import Any

from compliance_engine.models import (
    Applicability,
    Capability,
    ComplianceStatus,
    Evidence,
    Requirement,
    Verification,
    VerificationStatus,
)
from compliance_engine.rules import (
    GSTRegistrationRule,
    PANValidationRule,
    UdyamRegistrationRule,
)
from compliance_engine.rules.executor import RequirementExecutor
from compliance_engine.verification import (
    MockGSTProvider,
    MockPANProvider,
    MockUdyamProvider,
    VerificationProvider,
)


def _gst_requirement() -> Requirement:
    return Requirement(
        requirement_id="req-gst-001",
        capability=Capability.GST,
        description="GST registration must be valid.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="ACTIVE",
        rule_id="GST_REGISTRATION_001",
    )


def _pan_requirement() -> Requirement:
    return Requirement(
        requirement_id="req-pan-001",
        capability=Capability.PAN_INCOME_TAX,
        description="PAN must be valid.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="ACTIVE",
        rule_id="PAN_VALIDATION_001",
    )


def _udyam_requirement() -> Requirement:
    return Requirement(
        requirement_id="req-udyam-001",
        capability=Capability.UDYAM,
        description="Udyam registration must be valid.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="ACTIVE",
        rule_id="UDYAM_REGISTRATION_001",
    )


def _gst_evidence(value: str | None = None) -> Evidence:
    if value is None:
        value = MockGSTProvider.GSTIN_VERIFIED
    return Evidence(
        evidence_id="doc-gst-001:gstin",
        bidder_id="bidder_1",
        document_id="doc-gst-001",
        document_type="GST",
        field_name="gstin",
        value=value,
    )


def _pan_evidence(value: str | None = None) -> Evidence:
    if value is None:
        value = MockPANProvider.PAN_VERIFIED
    return Evidence(
        evidence_id="doc-pan-001:pan",
        bidder_id="bidder_1",
        document_id="doc-pan-001",
        document_type="PAN",
        field_name="pan_number",
        value=value,
    )


def _udyam_evidence(value: str | None = None) -> Evidence:
    if value is None:
        value = MockUdyamProvider.UDYAM_VERIFIED
    return Evidence(
        evidence_id="doc-udyam-001:udyam",
        bidder_id="bidder_1",
        document_id="doc-udyam-001",
        document_type="UDYAM",
        field_name="udyam_registration_number",
        value=value,
    )


def test_single_applicable_gst_requirement_executes_rule() -> None:
    """Verify that one applicable requirement executes its rule."""
    executor = RequirementExecutor()
    requirements = [_gst_requirement()]
    evidence = [_gst_evidence()]
    rules = {"GST_REGISTRATION_001": GSTRegistrationRule()}

    results = executor.execute(requirements, evidence, rules, MockGSTProvider())

    assert len(results) == 1
    result = results[0]
    assert result.requirement_id == "req-gst-001"
    assert result.status == ComplianceStatus.PASS
    assert result.rule_id == "GST_REGISTRATION_001"


def test_multiple_requirements_execute_their_rules() -> None:
    """Verify that multiple requirements execute their corresponding rules."""
    # Create a composite provider to handle multiple rule types
    class CompositeProvider:
        def __init__(self):
            self._gst = MockGSTProvider()
            self._pan = MockPANProvider()
            self._udyam = MockUdyamProvider()

        def verify(self, bidder_id: str, identifier: str, **kwargs):
            if identifier.startswith("UDYAM"):
                return self._udyam.verify(bidder_id, identifier, **kwargs)
            elif len(identifier) == 10:  # PAN format
                return self._pan.verify(bidder_id, identifier, **kwargs)
            else:  # GST format
                return self._gst.verify(bidder_id, identifier, **kwargs)

    executor = RequirementExecutor()
    requirements = [_gst_requirement(), _pan_requirement(), _udyam_requirement()]
    evidence = [_gst_evidence(), _pan_evidence(), _udyam_evidence()]
    rules = {
        "GST_REGISTRATION_001": GSTRegistrationRule(),
        "PAN_VALIDATION_001": PANValidationRule(),
        "UDYAM_REGISTRATION_001": UdyamRegistrationRule(),
    }

    results = executor.execute(requirements, evidence, rules, provider=CompositeProvider())

    assert len(results) == 3
    assert results[0].requirement_id == "req-gst-001"
    assert results[1].requirement_id == "req-pan-001"
    assert results[2].requirement_id == "req-udyam-001"


def test_not_applicable_requirement_does_not_execute_rule() -> None:
    """Verify that NOT_APPLICABLE requirements don't execute rules."""
    executor = RequirementExecutor()
    req = _gst_requirement()
    req.applicability = Applicability.NOT_APPLICABLE
    requirements = [req]
    evidence = [_gst_evidence()]
    rules = {"GST_REGISTRATION_001": GSTRegistrationRule()}

    results = executor.execute(requirements, evidence, rules, MockGSTProvider())

    assert len(results) == 1
    result = results[0]
    assert result.status == ComplianceStatus.NOT_APPLICABLE
    assert result.requirement_id == "req-gst-001"
    assert result.rule_id == "GST_REGISTRATION_001"


def test_unknown_applicability_does_not_produce_pass() -> None:
    """Verify UNKNOWN applicability produces UNVERIFIABLE, not PASS."""
    executor = RequirementExecutor()
    req = _gst_requirement()
    req.applicability = Applicability.UNKNOWN
    requirements = [req]
    evidence = [_gst_evidence()]
    rules = {"GST_REGISTRATION_001": GSTRegistrationRule()}

    results = executor.execute(requirements, evidence, rules, MockGSTProvider())

    assert len(results) == 1
    result = results[0]
    assert result.status == ComplianceStatus.UNVERIFIABLE
    assert result.requirement_id == "req-gst-001"
    # Verify the rule was not executed (the reason should be about unknown applicability)
    assert "unknown" in result.reason.lower()


def test_missing_rule_is_handled_deterministically() -> None:
    """Verify missing rule produces NOT_CHECKED deterministically."""
    executor = RequirementExecutor()
    requirements = [_gst_requirement()]
    evidence = [_gst_evidence()]
    rules = {}  # No rules provided

    results = executor.execute(requirements, evidence, rules, MockGSTProvider())

    assert len(results) == 1
    result = results[0]
    assert result.status == ComplianceStatus.NOT_CHECKED
    assert result.requirement_id == "req-gst-001"
    assert "no rule implementation" in result.reason.lower()
    assert "GST_REGISTRATION_001" in result.reason


def test_result_requirement_id_is_preserved() -> None:
    """Verify result preserves the original requirement_id."""
    executor = RequirementExecutor()
    requirements = [_gst_requirement()]
    evidence = [_gst_evidence()]
    rules = {"GST_REGISTRATION_001": GSTRegistrationRule()}

    results = executor.execute(requirements, evidence, rules, MockGSTProvider())

    assert results[0].requirement_id == "req-gst-001"


def test_result_rule_id_is_preserved() -> None:
    """Verify result preserves the original rule_id."""
    executor = RequirementExecutor()
    requirements = [_gst_requirement()]
    evidence = [_gst_evidence()]
    rules = {"GST_REGISTRATION_001": GSTRegistrationRule()}

    results = executor.execute(requirements, evidence, rules, MockGSTProvider())

    assert results[0].rule_id == "GST_REGISTRATION_001"


def test_evidence_references_survive_rule_execution() -> None:
    """Verify result preserves evidence references from rule execution."""
    executor = RequirementExecutor()
    evidence_item = _gst_evidence()
    requirements = [_gst_requirement()]
    evidence = [evidence_item]
    rules = {"GST_REGISTRATION_001": GSTRegistrationRule()}

    results = executor.execute(requirements, evidence, rules, MockGSTProvider())

    result = results[0]
    assert evidence_item.evidence_id in result.evidence_refs


def test_verification_references_survive_rule_execution() -> None:
    """Verify result preserves verification references from rule execution."""
    executor = RequirementExecutor()
    requirements = [_gst_requirement()]
    evidence = [_gst_evidence()]
    rules = {"GST_REGISTRATION_001": GSTRegistrationRule()}

    results = executor.execute(requirements, evidence, rules, MockGSTProvider())

    result = results[0]
    # GST rule should have verification_refs from the provider
    assert len(result.verification_refs) > 0


def test_rule_programming_error_propagates() -> None:
    """Verify unexpected rule exceptions propagate to expose bugs.
    
    Programming/invariant errors should not be silently caught.
    Provider/source unavailability is already handled through VerificationStatus.
    """
    import pytest

    class _FailingRule(GSTRegistrationRule):
        def evaluate(self, evidence, *args, **kwargs):
            raise ValueError("Programming error in rule")

    executor = RequirementExecutor()
    requirements = [_gst_requirement()]
    evidence = [_gst_evidence()]
    rules = {"GST_REGISTRATION_001": _FailingRule()}

    with pytest.raises(ValueError, match="Programming error in rule"):
        executor.execute(requirements, evidence, rules, MockGSTProvider())


def test_existing_gst_behavior_unchanged() -> None:
    """Verify GST rule behavior is not affected by executor."""
    executor = RequirementExecutor()
    requirements = [_gst_requirement()]
    evidence = [_gst_evidence()]
    rules = {"GST_REGISTRATION_001": GSTRegistrationRule()}

    results = executor.execute(requirements, evidence, rules, MockGSTProvider())

    result = results[0]
    assert result.status == ComplianceStatus.PASS


def test_existing_pan_behavior_unchanged() -> None:
    """Verify PAN rule behavior is not affected by executor."""
    executor = RequirementExecutor()
    requirements = [_pan_requirement()]
    evidence = [_pan_evidence()]
    rules = {"PAN_VALIDATION_001": PANValidationRule()}

    results = executor.execute(requirements, evidence, rules, provider=MockPANProvider())

    result = results[0]
    assert result.status == ComplianceStatus.PASS


def test_existing_udyam_behavior_unchanged() -> None:
    """Verify Udyam rule behavior is not affected by executor."""
    executor = RequirementExecutor()
    requirements = [_udyam_requirement()]
    evidence = [_udyam_evidence()]
    rules = {"UDYAM_REGISTRATION_001": UdyamRegistrationRule()}

    results = executor.execute(
        requirements, evidence, rules, provider=MockUdyamProvider()
    )

    result = results[0]
    assert result.status == ComplianceStatus.PASS


def test_not_applicable_requirement_does_not_mutate_requirement() -> None:
    """Verify the executor does not mutate requirement objects."""
    executor = RequirementExecutor()
    req = _gst_requirement()
    original_applicability = req.applicability
    req.applicability = Applicability.NOT_APPLICABLE
    requirements = [req]
    evidence = [_gst_evidence()]
    rules = {"GST_REGISTRATION_001": GSTRegistrationRule()}

    executor.execute(requirements, evidence, rules, MockGSTProvider())

    assert req.applicability == Applicability.NOT_APPLICABLE
    assert req.requirement_id == "req-gst-001"


def test_executor_does_not_mutate_evidence() -> None:
    """Verify the executor does not mutate evidence objects."""
    executor = RequirementExecutor()
    evidence_item = _gst_evidence()
    original_value = evidence_item.value
    requirements = [_gst_requirement()]
    evidence = [evidence_item]
    rules = {"GST_REGISTRATION_001": GSTRegistrationRule()}

    executor.execute(requirements, evidence, rules, MockGSTProvider())

    assert evidence_item.value == original_value
    assert evidence_item.evidence_id == "doc-gst-001:gstin"


def test_empty_requirements_produces_empty_results() -> None:
    """Verify executor handles empty requirements list."""
    executor = RequirementExecutor()
    results = executor.execute([], [], {})
    assert results == []


def test_context_passed_to_rule() -> None:
    """Verify additional context is passed to rule evaluation."""

    class _ContextAwareRule(GSTRegistrationRule):
        def evaluate(self, evidence, *args, custom_context=None, **kwargs):
            if custom_context is None:
                raise ValueError("custom_context not passed")
            return super().evaluate(evidence, *args, **kwargs)

    executor = RequirementExecutor()
    requirements = [_gst_requirement()]
    evidence = [_gst_evidence()]
    rules = {"GST_REGISTRATION_001": _ContextAwareRule()}

    # Without custom_context, the rule raises ValueError (programming error propagates)
    import pytest
    with pytest.raises(ValueError, match="custom_context not passed"):
        executor.execute(requirements, evidence, rules, provider=MockGSTProvider())

    # With custom_context, rule executes and returns PASS
    results = executor.execute(
        requirements,
        evidence,
        rules,
        provider=MockGSTProvider(),
        custom_context={"test": "value"},
    )
    assert results[0].status == ComplianceStatus.PASS
