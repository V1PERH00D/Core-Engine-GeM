
from ai_verification.cross_bidder import (
    CorroborationSignals,
    QualitySignals,
    SimilarityLayer,
    SimilarityTrace,
    TemplateGate,
    TemplateGateStatus,
)
from ai_verification.models import VerificationFinding
from compliance_engine.flags import FLAG_REGISTRY


VALID_FLAG_ID = next(iter(FLAG_REGISTRY))
VALID_SEVERITY = FLAG_REGISTRY[VALID_FLAG_ID].severity


def make_trace() -> SimilarityTrace:
    return SimilarityTrace(
        layer=SimilarityLayer.LEXICAL,
        left_document_id="doc-a",
        right_document_id="doc-b",
        left_bidder_id="bidder-a",
        right_bidder_id="bidder-b",
        doc_type="OEM_AUTH",
        left_file_hash="hash-a",
        right_file_hash="hash-b",
        left_norm_text_hash="norm-a",
        right_norm_text_hash="norm-b",
        normalization_version="v1",
        similarity_score=0.93,
        threshold=0.80,
        corroboration=CorroborationSignals(
            same_issuer=True,
            same_authorization_number=True,
            same_issue_date=True,
            validity_overlap=True,
        ),
        quality=QualitySignals(
            ocr_confidence=0.97,
            field_confidence=0.95,
            quality_score=0.95,
        ),
        template_gate=TemplateGate(
            status=TemplateGateStatus.MATCH,
            score=1.0,
            matched_fields=["authorization_number", "issue_date"],
        ),
        confidence=0.94,
    )


def test_similarity_trace_constructs() -> None:
    trace = make_trace()

    assert trace.layer is SimilarityLayer.LEXICAL
    assert trace.left_document_id == "doc-a"
    assert trace.right_document_id == "doc-b"
    assert trace.similarity_score == 0.93
    assert trace.confidence == 0.94


def test_similarity_trace_rejects_invalid_scores() -> None:
    trace_data = make_trace().model_dump()
    trace_data["confidence"] = 1.5

    try:
        SimilarityTrace(**trace_data)
    except ValueError:
        return

    raise AssertionError("Expected invalid confidence to be rejected")


def test_verification_finding_trace_is_optional() -> None:
    finding = VerificationFinding(
        finding_id="finding-1",
        bidder_id="bidder-a",
        flag_id=VALID_FLAG_ID,
        severity=VALID_SEVERITY,
        confidence=0.8,
        explanation="Test",
    )

    assert finding.trace is None


def test_verification_finding_preserves_trace() -> None:
    trace = make_trace()

    finding = VerificationFinding(
        finding_id="finding-1",
        bidder_id="bidder-a",
        flag_id=VALID_FLAG_ID,
        severity=VALID_SEVERITY,
        confidence=0.94,
        explanation="Documents are highly similar.",
        evidence_refs=["ev-a", "ev-b"],
        related_bidder_ids=["bidder-b"],
        trace=trace,
    )

    assert finding.trace == trace
    assert finding.trace is not None
    assert finding.trace.left_document_id == "doc-a"
