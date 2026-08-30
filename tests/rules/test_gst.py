from datetime import UTC, datetime
from typing import Any

from compliance_engine.models import (
    Applicability,
    ComplianceStatus,
    Evidence,
    Requirement,
    Verification,
    VerificationStatus,
)
from compliance_engine.rules import GSTRegistrationRule
from compliance_engine.verification import MockGSTProvider, VerificationProvider

RULE_ID = "GST_REGISTRATION_001"


def _requirement() -> Requirement:
    return Requirement(
        requirement_id="req-gst-registration-001",
        capability="GST",
        description="GST registration must be valid and active.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="ACTIVE",
        required_evidence=["gstin"],
        required_source="GSTN",
        rule_id=RULE_ID,
    )


def _gstin_evidence(value: str | None, evidence_id: str = "doc-uuid-gst-001:gstin") -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        bidder_id="bidder_acme_01",
        document_id="doc-uuid-gst-001",
        document_type="GST",
        field_name="gstin",
        value=value,
        confidence=0.99 if value is not None else 0.0,
        page=1 if value is not None else None,
        bbox=[50.0, 100.0, 250.0, 120.0] if value is not None else None,
    )


class _UnavailableGSTProvider(VerificationProvider):
    def verify(self, bidder_id: str, identifier: str, **kwargs: Any) -> Verification:
        return Verification(
            verification_id=f"GSTN_MOCK:{identifier}",
            bidder_id=bidder_id,
            capability="GST",
            source="GSTN_MOCK",
            queried_identifier=identifier,
            status=VerificationStatus.UNAVAILABLE,
            data={},
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_missing_gstin() -> None:
    result = GSTRegistrationRule().evaluate([], MockGSTProvider(), _requirement())
    assert result.status is ComplianceStatus.MISSING
    assert result.flags == ["GSTIN_MISSING"]
    assert result.evidence_refs == []
    assert result.verification_refs == []
    assert "missing" in result.reason.lower()
    assert result.rule_id == RULE_ID


def test_null_gstin() -> None:
    evidence = _gstin_evidence(None)
    result = GSTRegistrationRule().evaluate([evidence], MockGSTProvider(), _requirement())
    assert result.status is ComplianceStatus.MISSING
    assert result.flags == ["GSTIN_MISSING"]
    assert result.evidence_refs == [evidence.evidence_id]
    assert result.verification_refs == []
    assert "null" in result.reason.lower()
    assert result.rule_id == RULE_ID


def test_verified_active_gst() -> None:
    evidence = _gstin_evidence(MockGSTProvider.GSTIN_VERIFIED)
    result = GSTRegistrationRule().evaluate([evidence], MockGSTProvider(), _requirement())
    assert result.status is ComplianceStatus.PASS
    assert result.expected == "ACTIVE"
    assert result.actual["status"] is VerificationStatus.VERIFIED
    assert result.actual["data"]["registration_status"] == "ACTIVE"
    assert result.evidence_refs == [evidence.evidence_id]
    assert result.verification_refs == [
        f"{MockGSTProvider.SOURCE}:{MockGSTProvider.GSTIN_VERIFIED}"
    ]
    assert result.rule_id == RULE_ID
    assert result.reason


def test_inactive_gst() -> None:
    evidence = _gstin_evidence(MockGSTProvider.GSTIN_INACTIVE)
    result = GSTRegistrationRule().evaluate([evidence], MockGSTProvider(), _requirement())
    assert result.status is ComplianceStatus.FAIL
    assert result.actual["status"] is VerificationStatus.INACTIVE
    assert "inactive" in result.reason.lower()
    assert result.rule_id == RULE_ID


def test_invalid_gst() -> None:
    evidence = _gstin_evidence(MockGSTProvider.GSTIN_INVALID)
    result = GSTRegistrationRule().evaluate([evidence], MockGSTProvider(), _requirement())
    assert result.status is ComplianceStatus.FAIL
    assert result.actual["status"] is VerificationStatus.INVALID
    assert "invalid" in result.reason.lower()
    assert result.rule_id == RULE_ID


def test_not_found_gst() -> None:
    evidence = _gstin_evidence(MockGSTProvider.GSTIN_NOT_FOUND)
    result = GSTRegistrationRule().evaluate([evidence], MockGSTProvider(), _requirement())
    assert result.status is ComplianceStatus.UNVERIFIABLE
    assert result.actual["status"] is VerificationStatus.NOT_FOUND
    assert result.verification_refs == [
        f"{MockGSTProvider.SOURCE}:{MockGSTProvider.GSTIN_NOT_FOUND}"
    ]
    assert "not found" in result.reason.lower()
    assert result.rule_id == RULE_ID


def test_unavailable_provider() -> None:
    evidence = _gstin_evidence(MockGSTProvider.GSTIN_VERIFIED)
    result = GSTRegistrationRule().evaluate(
        [evidence], _UnavailableGSTProvider(), _requirement()
    )
    assert result.status is ComplianceStatus.UNVERIFIABLE
    assert result.actual["status"] is VerificationStatus.UNAVAILABLE
    assert result.verification_refs == [f"GSTN_MOCK:{MockGSTProvider.GSTIN_VERIFIED}"]
    assert "unavailable" in result.reason.lower()
    assert result.rule_id == RULE_ID


def test_reason_is_human_readable() -> None:
    result = GSTRegistrationRule().evaluate(
        [_gstin_evidence(MockGSTProvider.GSTIN_VERIFIED)],
        MockGSTProvider(),
        _requirement(),
    )
    assert "GST" in result.reason
    assert result.reason[0].isupper()
    assert not result.reason.startswith("{")
