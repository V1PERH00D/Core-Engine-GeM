from compliance_engine.models import Applicability, ComplianceStatus, Evidence, Requirement
from compliance_engine.rules import PANValidationRule
from compliance_engine.verification import MockPANProvider


def _requirement() -> Requirement:
    return Requirement(
        requirement_id="req-pan-validation-001",
        capability="PAN",
        description="PAN must be valid and active.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="ACTIVE",
        required_evidence=["pan_number"],
        required_source="PAN",
        rule_id="PAN_VALIDATION_001",
    )


def _pan_evidence(value: str | None, evidence_id: str = "doc-uuid-pan-001:pan_number") -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        bidder_id="bidder_acme_01",
        document_id="doc-uuid-pan-001",
        document_type="PAN",
        field_name="pan_number",
        value=value,
        confidence=0.99 if value is not None else 0.0,
        page=1 if value is not None else None,
        bbox=[40.0, 80.0, 200.0, 100.0] if value is not None else None,
    )


def test_verified_pan_passes() -> None:
    result = PANValidationRule().evaluate(
        [_pan_evidence(MockPANProvider.PAN_VERIFIED)],
        MockPANProvider(),
        _requirement(),
    )
    assert result.status is ComplianceStatus.PASS
    assert result.flags == []
    assert result.evidence_refs == ["doc-uuid-pan-001:pan_number"]
    assert result.verification_refs == [f"PAN_MOCK:{MockPANProvider.PAN_VERIFIED}"]
    assert result.rule_id == "PAN_VALIDATION_001"


def test_not_found_pan_is_unverifiable() -> None:
    result = PANValidationRule().evaluate(
        [_pan_evidence(MockPANProvider.PAN_NOT_FOUND)],
        MockPANProvider(),
        _requirement(),
    )
    assert result.status is ComplianceStatus.UNVERIFIABLE
    assert result.flags == ["PAN_NOT_FOUND"]
    assert result.verification_refs == [f"PAN_MOCK:{MockPANProvider.PAN_NOT_FOUND}"]


def test_invalid_pan_fails() -> None:
    result = PANValidationRule().evaluate(
        [_pan_evidence(MockPANProvider.PAN_INVALID)],
        MockPANProvider(),
        _requirement(),
    )
    assert result.status is ComplianceStatus.FAIL
    assert result.flags == ["PAN_INVALID"]


def test_inactive_pan_fails() -> None:
    result = PANValidationRule().evaluate(
        [_pan_evidence(MockPANProvider.PAN_INACTIVE)],
        MockPANProvider(),
        _requirement(),
    )
    assert result.status is ComplianceStatus.FAIL
    assert result.flags == ["PAN_INACTIVE"]


def test_missing_pan_evidence_is_missing() -> None:
    result = PANValidationRule().evaluate([], MockPANProvider(), _requirement())
    assert result.status is ComplianceStatus.MISSING
    assert result.flags == ["REQUIRED_FIELD_MISSING"]
    assert result.evidence_refs == []


def test_null_pan_evidence_is_missing() -> None:
    result = PANValidationRule().evaluate(
        [_pan_evidence(None)],
        MockPANProvider(),
        _requirement(),
    )
    assert result.status is ComplianceStatus.MISSING
    assert result.flags == ["REQUIRED_FIELD_MISSING"]
    assert result.evidence_refs == ["doc-uuid-pan-001:pan_number"]


def test_evidence_and_verification_refs_are_preserved() -> None:
    evidence = _pan_evidence(MockPANProvider.PAN_VERIFIED)
    result = PANValidationRule().evaluate([evidence], MockPANProvider(), _requirement())
    assert result.evidence_refs == [evidence.evidence_id]
    assert result.verification_refs == [f"PAN_MOCK:{MockPANProvider.PAN_VERIFIED}"]


def test_rule_id_and_requirement_id_are_preserved() -> None:
    result = PANValidationRule().evaluate(
        [_pan_evidence(MockPANProvider.PAN_VERIFIED)],
        MockPANProvider(),
        _requirement(),
    )
    assert result.requirement_id == "req-pan-validation-001"
    assert result.rule_id == "PAN_VALIDATION_001"
    assert result.expected == "ACTIVE"


def test_rule_does_not_perform_identity_comparison() -> None:
    evidence = _pan_evidence(MockPANProvider.PAN_NAME_MISMATCH)
    result = PANValidationRule().evaluate([evidence], MockPANProvider(), _requirement())
    assert result.status is ComplianceStatus.PASS
    assert result.flags == []
    assert "OTHER BIDDER" not in result.reason
