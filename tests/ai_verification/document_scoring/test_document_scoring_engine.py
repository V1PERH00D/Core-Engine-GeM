"""Tests for deterministic document-priority scoring."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_verification.document_scoring import (
    DocumentInput,
    DocumentPriority,
    DocumentScoringEngine,
    DocumentScoringPolicy,
    DocumentScoreReason,
    TrafficLight,
)
from ai_verification.models.contracts import VerificationFinding
from compliance_engine.flags import get_flag_definition
from compliance_engine.models import ComplianceResult, Evidence, Requirement
from compliance_engine.models.requirement import Applicability
from compliance_engine.models.result import ComplianceStatus
from compliance_engine.models.verification import Verification, VerificationStatus


ENGINE = DocumentScoringEngine()


def _document(document_id: str, document_type: str) -> DocumentInput:
    return DocumentInput(document_id=document_id, document_type=document_type)


def _evidence(
    document_id: str,
    *,
    document_type: str,
    evidence_id: str | None = None,
    confidence: float = 0.99,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id or f"{document_id}:field",
        bidder_id="bidder-1",
        document_id=document_id,
        document_type=document_type,
        field_name="field",
        value="value",
        confidence=confidence,
    )


def _result(
    requirement_id: str,
    capability: str,
    status: ComplianceStatus,
    *,
    flags: list[str] | None = None,
) -> ComplianceResult:
    return ComplianceResult(
        requirement_id=requirement_id,
        capability=capability,
        status=status,
        reason="test result",
        flags=list(flags or []),
        rule_id="TEST_RULE",
    )


def test_clean_documents_are_green() -> None:
    documents = [_document("doc-gst", "GST"), _document("doc-pan", "PAN")]
    evidence = [
        _evidence("doc-gst", document_type="GST"),
        _evidence("doc-pan", document_type="PAN"),
    ]
    results = [
        _result("r-gst", "GST", ComplianceStatus.PASS),
        _result("r-pan", "PAN", ComplianceStatus.PASS),
    ]

    assessment = ENGINE.score(
        "bidder-1",
        documents=documents,
        evidence=evidence,
        compliance_results=results,
    )

    assert assessment.category is TrafficLight.GREEN
    assert assessment.score == 100.0
    assert all(item.score == 100.0 for item in assessment.documents)
    assert DocumentScoreReason.NO_MATERIAL_ISSUES in assessment.reason_codes


def test_medium_document_without_evidence_is_yellow() -> None:
    assessment = ENGINE.score(
        "bidder-1",
        documents=[_document("doc-epfo", "EPFO")],
    )

    assert assessment.category is TrafficLight.YELLOW
    assert 50.0 <= assessment.score < 80.0
    assert DocumentScoreReason.NO_EVIDENCE in assessment.reason_codes




def test_high_priority_compliance_failure_is_red() -> None:
    assessment = ENGINE.score(
        "bidder-1",
        documents=[_document("doc-bis", "BIS")],
        evidence=[_evidence("doc-bis", document_type="BIS")],
        compliance_results=[
            _result("req-bis", "BIS", ComplianceStatus.FAIL)
        ],
    )

    bis = assessment.documents[0]
    assert bis.priority is DocumentPriority.HIGH
    assert bis.score == 40.0
    assert assessment.category is TrafficLight.RED
    assert DocumentScoreReason.COMPLIANCE_FAILED in bis.reasons


def test_material_finding_is_red_even_on_unknown_document() -> None:
    definition = get_flag_definition("CROSS_BIDDER_DOCUMENT_REUSED")
    finding = VerificationFinding(
        finding_id="finding-reuse",
        bidder_id="bidder-1",
        flag_id=definition.flag_id,
        severity=definition.severity,
        confidence=0.99,
        explanation="Documents are reused",
        evidence_refs=["unknown:field"],
    )

    assessment = ENGINE.score(
        "bidder-1",
        documents=[_document("doc-pdf", "PDF")],
        evidence=[
            _evidence(
                "doc-pdf",
                document_type="PDF",
                evidence_id="unknown:field",
            )
        ],
        findings=[finding],
    )

    assert assessment.category is TrafficLight.RED
    assert assessment.documents[0].finding_flag_ids == (
        "CROSS_BIDDER_DOCUMENT_REUSED",
    )
    assert DocumentScoreReason.MATERIAL_FINDING in assessment.reason_codes


def test_aliases_are_normalized() -> None:
    assessment = ENGINE.score(
        "bidder-1",
        documents=[_document("doc-gstn", "GSTN")],
        evidence=[_evidence("doc-gstn", document_type="GSTN")],
    )

    assert assessment.documents[0].document_type == "GST"
    assert assessment.documents[0].priority is DocumentPriority.CRITICAL


def test_custom_thresholds_are_applied() -> None:
    policy = DocumentScoringPolicy(red_threshold=90.0, yellow_threshold=95.0)
    assessment = DocumentScoringEngine(policy).score(
        "bidder-1",
        documents=[_document("doc-epfo", "EPFO")],
    )

    assert assessment.category is TrafficLight.RED
    assert policy.red_threshold < policy.yellow_threshold


def test_scoring_does_not_mutate_inputs() -> None:
    document = _document("doc-gst", "GST")
    evidence = _evidence("doc-gst", document_type="GST")
    result = _result("req-gst", "GST", ComplianceStatus.PASS)
    before = (document.model_dump(), evidence.model_dump(), result.model_dump())

    ENGINE.score(
        "bidder-1",
        documents=[document],
        evidence=[evidence],
        compliance_results=[result],
    )

    after = (document.model_dump(), evidence.model_dump(), result.model_dump())
    assert before == after


def test_policy_rejects_invalid_thresholds() -> None:
    with pytest.raises(ValidationError):
        DocumentScoringPolicy(red_threshold=90.0, yellow_threshold=80.0)


def test_verified_record_does_not_override_failed_compliance() -> None:
    verification = Verification(
        verification_id="v-gst",
        bidder_id="bidder-1",
        capability="GST",
        source="TEST",
        status=VerificationStatus.VERIFIED,
    )
    assessment = ENGINE.score(
        "bidder-1",
        documents=[_document("doc-gst", "GST")],
        evidence=[_evidence("doc-gst", document_type="GST")],
        compliance_results=[
            _result("req-gst", "GST", ComplianceStatus.FAIL)
        ],
        verification_records=[verification],
    )

    assert assessment.category is TrafficLight.RED
    assert DocumentScoreReason.VERIFIED not in assessment.documents[0].reasons

def test_missing_critical_required_document_is_red() -> None:
    requirement = Requirement(
        requirement_id="req-gst",
        capability="GST",
        description="GST is required",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        rule_id="GST_RULE",
    )

    assessment = ENGINE.score(
        "bidder-1",
        documents=[_document("doc-pan", "PAN")],
        requirements=[requirement],
        evidence=[_evidence("doc-pan", document_type="PAN")],
    )

    assert assessment.category is TrafficLight.RED
    missing = next(item for item in assessment.documents if item.document_type == "GST")
    assert missing.present is False
    assert DocumentScoreReason.DOCUMENT_MISSING in missing.reasons
