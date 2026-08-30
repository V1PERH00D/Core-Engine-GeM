from compliance_engine.models import Applicability, ComplianceStatus, Evidence, Requirement
from compliance_engine.rules import UdyamRegistrationRule
from compliance_engine.verification import MockUdyamProvider


def _requirement() -> Requirement:
    return Requirement(
        requirement_id="req-udyam-registration-001",
        capability="UDYAM",
        description="Udyam registration must be valid and active.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="ACTIVE",
        required_evidence=["udyam_registration_number"],
        required_source="UDYAM",
        rule_id="UDYAM_REGISTRATION_001",
    )


def _udyam_evidence(value: str | None, evidence_id: str = "doc-uuid-udyam-001:udyam_registration_number") -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        bidder_id="bidder_acme_01",
        document_id="doc-uuid-udyam-001",
        document_type="UDYAM",
        field_name="udyam_registration_number",
        value=value,
        confidence=0.99 if value is not None else 0.0,
        page=1 if value is not None else None,
        bbox=[40.0, 80.0, 260.0, 100.0] if value is not None else None,
    )


def test_verified_udyam_passes() -> None:
    result = UdyamRegistrationRule().evaluate(
        [_udyam_evidence(MockUdyamProvider.UDYAM_VERIFIED)],
        MockUdyamProvider(),
        _requirement(),
    )
    assert result.status is ComplianceStatus.PASS
    assert result.flags == []
    assert result.evidence_refs == ["doc-uuid-udyam-001:udyam_registration_number"]
    assert result.verification_refs == [f"UDYAM_MOCK:{MockUdyamProvider.UDYAM_VERIFIED}"]
    assert result.requirement_id == "req-udyam-registration-001"
    assert result.rule_id == "UDYAM_REGISTRATION_001"


def test_not_found_udyam_is_unverifiable() -> None:
    result = UdyamRegistrationRule().evaluate(
        [_udyam_evidence(MockUdyamProvider.UDYAM_NOT_FOUND)],
        MockUdyamProvider(),
        _requirement(),
    )
    assert result.status is ComplianceStatus.UNVERIFIABLE
    assert result.flags == ["UDYAM_NOT_FOUND"]
    assert result.verification_refs == [f"UDYAM_MOCK:{MockUdyamProvider.UDYAM_NOT_FOUND}"]


def test_invalid_udyam_fails() -> None:
    result = UdyamRegistrationRule().evaluate(
        [_udyam_evidence(MockUdyamProvider.UDYAM_INVALID)],
        MockUdyamProvider(),
        _requirement(),
    )
    assert result.status is ComplianceStatus.FAIL
    assert result.flags == ["UDYAM_INVALID"]


def test_inactive_udyam_fails() -> None:
    result = UdyamRegistrationRule().evaluate(
        [_udyam_evidence(MockUdyamProvider.UDYAM_INACTIVE)],
        MockUdyamProvider(),
        _requirement(),
    )
    assert result.status is ComplianceStatus.FAIL
    assert result.flags == ["UDYAM_INACTIVE"]


def test_missing_udyam_evidence_returns_required_field_missing() -> None:
    result = UdyamRegistrationRule().evaluate([], MockUdyamProvider(), _requirement())
    assert result.status is ComplianceStatus.MISSING
    assert result.flags == ["REQUIRED_FIELD_MISSING"]
    assert result.evidence_refs == []


def test_null_udyam_value_returns_required_field_missing() -> None:
    result = UdyamRegistrationRule().evaluate(
        [_udyam_evidence(None)],
        MockUdyamProvider(),
        _requirement(),
    )
    assert result.status is ComplianceStatus.MISSING
    assert result.flags == ["REQUIRED_FIELD_MISSING"]
    assert result.evidence_refs == ["doc-uuid-udyam-001:udyam_registration_number"]


def test_unavailable_or_error_provider_is_unverifiable() -> None:
    class _UnavailableProvider:
        def verify(self, bidder_id: str, identifier: str, **kwargs):
            return type(
                "V",
                (),
                {"verification_id": "UDYAM_MOCK:UNAVAILABLE", "status": "UNAVAILABLE", "data": {}, "verification_id": "UDYAM_MOCK:UNAVAILABLE"},
            )()

    result = UdyamRegistrationRule().evaluate(
        [_udyam_evidence(MockUdyamProvider.UDYAM_VERIFIED)],
        _UnavailableProvider(),
        _requirement(),
    )
    assert result.status is ComplianceStatus.UNVERIFIABLE
    assert result.flags == ["UDYAM_VERIFICATION_UNAVAILABLE"]


def test_verified_category_data_is_preserved_in_actual() -> None:
    result = UdyamRegistrationRule().evaluate(
        [_udyam_evidence(MockUdyamProvider.UDYAM_CATEGORY_MISMATCH)],
        MockUdyamProvider(),
        _requirement(),
    )
    assert result.actual["status"].value == "VERIFIED"
    assert result.actual["data"]["enterprise_category"] == "Micro"


def test_registration_rule_does_not_compare_identity_or_category() -> None:
    result = UdyamRegistrationRule().evaluate(
        [_udyam_evidence(MockUdyamProvider.UDYAM_NAME_MISMATCH)],
        MockUdyamProvider(),
        _requirement(),
    )
    assert result.status is ComplianceStatus.PASS
    assert result.flags == []
    assert "OTHER BIDDER" not in result.reason
