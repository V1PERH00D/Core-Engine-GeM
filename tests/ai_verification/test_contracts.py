import pytest
from pydantic import ValidationError

from ai_verification.models import (
    BidderSummary,
    VerificationFinding,
    VerificationInput,
    VerificationResult,
)
from compliance_engine.flags import FLAG_REGISTRY
from compliance_engine.models import ComplianceResult, IdentityFinding


VALID_FLAG_ID = next(iter(FLAG_REGISTRY))


def test_valid_verification_finding() -> None:
    definition = FLAG_REGISTRY[VALID_FLAG_ID]

    finding = VerificationFinding(
        finding_id="finding-1",
        bidder_id="bidder-1",
        flag_id=VALID_FLAG_ID,
        severity=definition.severity,
        confidence=0.5,
        explanation="Test finding",
        evidence_refs=["ev-1", "ev-2"],
        verification_refs=["ver-1"],
        related_bidder_ids=["bidder-2"],
    )

    assert finding.finding_id == "finding-1"
    assert finding.bidder_id == "bidder-1"
    assert finding.flag_id == VALID_FLAG_ID
    assert finding.severity == definition.severity
    assert finding.confidence == 0.5
    assert finding.explanation == "Test finding"
    assert finding.evidence_refs == ["ev-1", "ev-2"]
    assert finding.verification_refs == ["ver-1"]
    assert finding.related_bidder_ids == ["bidder-2"]


def test_unknown_flag_rejected() -> None:
    with pytest.raises(Exception):
        VerificationFinding(
            finding_id="finding-1",
            bidder_id="bidder-1",
            flag_id="THIS_FLAG_DOES_NOT_EXIST",
            severity="HIGH",
            confidence=0.5,
            explanation="Test",
        )


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_out_of_range_rejected(confidence: float) -> None:
    with pytest.raises(ValidationError):
        VerificationFinding(
            finding_id="finding-1",
            bidder_id="bidder-1",
            flag_id=VALID_FLAG_ID,
            severity=FLAG_REGISTRY[VALID_FLAG_ID].severity,
            confidence=confidence,
            explanation="Test",
        )


def test_reference_lists_are_preserved() -> None:
    finding = VerificationFinding(
        finding_id="finding-1",
        bidder_id="bidder-1",
        flag_id=VALID_FLAG_ID,
        severity=FLAG_REGISTRY[VALID_FLAG_ID].severity,
        confidence=0.9,
        explanation="Test",
        evidence_refs=["ev-1", "ev-2"],
        verification_refs=["ver-1", "ver-2"],
        related_bidder_ids=["bidder-2", "bidder-3"],
    )

    assert finding.evidence_refs == ["ev-1", "ev-2"]
    assert finding.verification_refs == ["ver-1", "ver-2"]
    assert finding.related_bidder_ids == ["bidder-2", "bidder-3"]


def test_bidder_summary() -> None:
    summary = BidderSummary(bidder_id="bidder-2")

    assert summary.bidder_id == "bidder-2"
    assert summary.evidence == []
    assert summary.compliance_results == []
    assert summary.identity_findings == []
    assert summary.verification_records == []


def test_bidder_summary_preserves_verification_records() -> None:
    from compliance_engine.models.verification import Verification, VerificationStatus

    verification = Verification(
        verification_id="ver-1",
        bidder_id="bidder-1",
        capability="GST",
        source="GSTN_MOCK",
        queried_identifier="27AAACI1234F1Z5",
        status=VerificationStatus.VERIFIED,
        data={"registration_status": "ACTIVE"},
    )
    summary = BidderSummary(
        bidder_id="bidder-2",
        verification_records=[verification],
    )

    assert summary.verification_records == [verification]


def test_verification_input_defaults() -> None:
    input_data = VerificationInput(
        bidder_id="bidder-1",
        evidence=[],
        compliance_results=[],
        identity_findings=[],
    )

    assert input_data.verification_records == []


def test_verification_input_preserves_verification_records() -> None:
    from compliance_engine.models.verification import Verification, VerificationStatus

    verification = Verification(
        verification_id="ver-1",
        bidder_id="bidder-1",
        capability="GST",
        source="GSTN_MOCK",
        queried_identifier="27AAACI1234F1Z5",
        status=VerificationStatus.VERIFIED,
        data={"registration_status": "ACTIVE"},
    )
    input_data = VerificationInput(
        bidder_id="bidder-1",
        evidence=[],
        compliance_results=[],
        identity_findings=[],
        verification_records=[verification],
    )

    assert input_data.verification_records == [verification]


def test_engine_inputs_accept_actual_public_models() -> None:
    evidence = []
    compliance_results: list[ComplianceResult] = []
    identity_findings: list[IdentityFinding] = []

    input_data = VerificationInput(
        bidder_id="bidder-1",
        evidence=evidence,
        compliance_results=compliance_results,
        identity_findings=identity_findings,
    )

    assert input_data.evidence is not None
    assert input_data.compliance_results is not None
    assert input_data.identity_findings is not None
    assert input_data.verification_records == []


def test_bidder_summary_verification_records_default() -> None:
    """Test that BidderSummary verification_records defaults to empty list."""
    summary = BidderSummary(bidder_id="bidder-2")
    assert summary.verification_records == []


def test_verification_input_verification_records_default() -> None:
    """Test that VerificationInput verification_records defaults to empty list."""
    input_data = VerificationInput(
        bidder_id="bidder-1",
        evidence=[],
        compliance_results=[],
        identity_findings=[],
    )
    assert input_data.verification_records == []


def test_verification_input_accepts_verification_records() -> None:
    """Test that VerificationInput preserves supplied verification_records."""
    from compliance_engine.models.verification import Verification
    verification = Verification(
        verification_id="ver-1",
        bidder_id="bidder-1",
        capability="GST",
        source="GSTN_MOCK",
        status="VERIFIED",
        data={},
    )
    input_data = VerificationInput(
        bidder_id="bidder-1",
        evidence=[],
        compliance_results=[],
        identity_findings=[],
        verification_records=[verification],
    )
    assert input_data.verification_records == [verification]


def test_bidder_summary_accepts_verification_records() -> None:
    """Test that BidderSummary preserves supplied verification_records."""
    from compliance_engine.models.verification import Verification
    verification = Verification(
        verification_id="ver-1",
        bidder_id="bidder-1",
        capability="GST",
        source="GSTN_MOCK",
        status="VERIFIED",
        data={},
    )
    summary = BidderSummary(
        bidder_id="bidder-2",
        verification_records=[verification],
    )
    assert summary.verification_records == [verification]


def test_verification_input() -> None:
    input_data = VerificationInput(
        bidder_id="bidder-1",
        evidence=[],
        compliance_results=[],
        identity_findings=[],
        bidder_corpus=[BidderSummary(bidder_id="bidder-2")],
    )

    assert input_data.bidder_id == "bidder-1"
    assert input_data.evidence == []
    assert input_data.compliance_results == []
    assert input_data.identity_findings == []
    assert input_data.bidder_corpus[0].bidder_id == "bidder-2"


def test_verification_result_empty() -> None:
    result = VerificationResult(bidder_id="bidder-1")

    assert result.bidder_id == "bidder-1"
    assert result.findings == []
    assert result.generated_at.tzinfo is not None


def test_engine_inputs_accept_actual_public_models() -> None:
    evidence = []
    compliance_results: list[ComplianceResult] = []
    identity_findings: list[IdentityFinding] = []

    input_data = VerificationInput(
        bidder_id="bidder-1",
        evidence=evidence,
        compliance_results=compliance_results,
        identity_findings=identity_findings,
    )

    assert input_data.evidence is not None
    assert input_data.compliance_results is not None
    assert input_data.identity_findings is not None
