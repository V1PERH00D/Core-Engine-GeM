from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from compliance_engine.models import (
    Applicability,
    Capability,
    ComplianceResult,
    ComplianceStatus,
    Evidence,
    Requirement,
    Verification,
    VerificationStatus,
)


def _valid_evidence_kwargs() -> dict:
    return {
        "evidence_id": "ev-gstin-001",
        "bidder_id": "bidder_acme_01",
        "document_id": "doc-uuid-gst-001",
        "document_type": "GST",
        "field_name": "gstin",
        "value": "27AAACI1234F1Z5",
        "confidence": 0.99,
        "page": 1,
        "bbox": [50.0, 100.0, 250.0, 120.0],
    }


def test_evidence_valid_construction() -> None:
    evidence = Evidence.model_validate(_valid_evidence_kwargs())
    assert evidence.field_name == "gstin"
    assert evidence.confidence == 0.99
    assert evidence.page == 1
    assert evidence.bbox == [50.0, 100.0, 250.0, 120.0]


def test_evidence_optional_provenance_may_be_absent() -> None:
    kwargs = _valid_evidence_kwargs()
    kwargs.pop("confidence")
    kwargs.pop("page")
    kwargs.pop("bbox")
    evidence = Evidence.model_validate(kwargs)
    assert evidence.confidence is None
    assert evidence.page is None
    assert evidence.bbox is None


def test_evidence_confidence_must_be_between_zero_and_one() -> None:
    Evidence.model_validate({**_valid_evidence_kwargs(), "confidence": 0.0})
    Evidence.model_validate({**_valid_evidence_kwargs(), "confidence": 1.0})
    with pytest.raises(ValidationError):
        Evidence.model_validate({**_valid_evidence_kwargs(), "confidence": -0.01})
    with pytest.raises(ValidationError):
        Evidence.model_validate({**_valid_evidence_kwargs(), "confidence": 1.01})


def test_evidence_bbox_must_contain_exactly_four_numbers() -> None:
    with pytest.raises(ValidationError):
        Evidence.model_validate({**_valid_evidence_kwargs(), "bbox": [50.0, 100.0, 250.0]})
    with pytest.raises(ValidationError):
        Evidence.model_validate(
            {**_valid_evidence_kwargs(), "bbox": [50.0, 100.0, 250.0, 120.0, 1.0]}
        )


def test_evidence_page_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Evidence.model_validate({**_valid_evidence_kwargs(), "page": 0})
    with pytest.raises(ValidationError):
        Evidence.model_validate({**_valid_evidence_kwargs(), "page": -1})


def test_verification_valid_construction() -> None:
    record = Verification(
        verification_id="ver-gst-001",
        bidder_id="bidder_acme_01",
        capability=Capability.GST,
        source="GSTN",
        queried_identifier="27AAACI1234F1Z5",
        status=VerificationStatus.VERIFIED,
        data={"legal_name": "ACME ENTERPRISES PRIVATE LIMITED"},
        retrieved_at=datetime(2026, 8, 29, tzinfo=UTC),
    )
    assert record.status is VerificationStatus.VERIFIED
    assert "legal_name" in record.data


def test_verification_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        Verification.model_validate(
            {
                "verification_id": "ver-gst-001",
                "bidder_id": "bidder_acme_01",
                "capability": Capability.GST,
                "source": "GSTN",
                "status": "PASS",
                "data": {},
                "retrieved_at": datetime(2026, 8, 29, tzinfo=UTC),
            }
        )


def test_requirement_basic_construction() -> None:
    requirement = Requirement(
        requirement_id="req-turnover-001",
        capability=Capability.FINANCIAL,
        description="Minimum average annual turnover for specified financial years.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        operator=">=",
        expected=25,
        parameters={"unit": "INR_CRORE"},
        required_evidence=["annual_turnovers"],
        required_source=None,
        rule_id="FIN_TURNOVER_001",
    )
    assert requirement.mandatory is True
    assert requirement.applicability is Applicability.APPLICABLE
    assert requirement.rule_id == "FIN_TURNOVER_001"
    assert requirement.capability == Capability.FINANCIAL


def test_requirement_rejects_invalid_applicability() -> None:
    with pytest.raises(ValidationError):
        Requirement.model_validate(
            {
                "requirement_id": "req-turnover-001",
                "capability": Capability.FINANCIAL,
                "description": "Minimum turnover.",
                "mandatory": True,
                "applicability": "MAYBE",
                "rule_id": "FIN_TURNOVER_001",
            }
        )


def test_compliance_result_basic_construction() -> None:
    result = ComplianceResult(
        requirement_id="req-turnover-001",
        capability=Capability.FINANCIAL,
        status=ComplianceStatus.FAIL,
        reason="Extracted turnover is below the tender threshold.",
        expected=25,
        actual=15.8,
        evidence_refs=["ev-turnover-001"],
        verification_refs=[],
        flags=["TURNOVER_BELOW_THRESHOLD"],
        rule_id="FIN_TURNOVER_001",
    )
    assert result.status is ComplianceStatus.FAIL
    assert result.evidence_refs == ["ev-turnover-001"]
    assert result.capability == Capability.FINANCIAL


def test_compliance_result_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        ComplianceResult.model_validate(
            {
                "requirement_id": "req-turnover-001",
                "capability": Capability.FINANCIAL,
                "status": "VERIFIED",
                "reason": "not a compliance status",
                "rule_id": "FIN_TURNOVER_001",
            }
        )
