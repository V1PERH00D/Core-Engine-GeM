"""Stable JSON-safe serialization of engine artefacts."""

import json

import pytest

from infrastructure.serialization import (
    SERIALIZATION_SCHEMA_VERSION,
    UnknownArtifactTypeError,
    deserialize_artifact,
    serialize_artifact,
)


def _roundtrip(obj, expected_type: str):
    envelope = serialize_artifact(obj)
    assert envelope.artifact_type == expected_type
    assert envelope.schema_version == SERIALIZATION_SCHEMA_VERSION
    json.dumps(envelope.model_dump(mode="json"))
    restored = deserialize_artifact(envelope)
    assert type(restored) is type(obj)
    return restored


def test_evidence_roundtrip():
    from compliance_engine.models.evidence import Evidence

    ev = Evidence(
        evidence_id="e1",
        bidder_id="b1",
        document_id="d1",
        document_type="GST",
        field_name="gstin",
        value="29ABCDE1234F1Z5",
        confidence=0.9,
    )
    _roundtrip(ev, "evidence")


def test_verification_roundtrip():
    from compliance_engine.models.verification import (
        Verification,
        VerificationStatus,
    )

    v = Verification(
        verification_id="v1",
        bidder_id="b1",
        capability="GST",
        source="GSTN_MOCK",
        queried_identifier="29ABCDE1234F1Z5",
        status=VerificationStatus.VERIFIED,
        data={"legal_name": "Acme"},
    )
    _roundtrip(v, "verification")


def test_compliance_result_roundtrip():
    from compliance_engine.models.result import (
        ComplianceResult,
        ComplianceStatus,
    )

    r = ComplianceResult(
        requirement_id="req-1",
        capability="GST",
        status=ComplianceStatus.PASS,
        reason="ok",
        rule_id="gst",
        evidence_refs=["e1"],
        verification_refs=["v1"],
    )
    _roundtrip(r, "compliance_result")


def test_identity_finding_roundtrip():
    from compliance_engine.models.finding import IdentityFinding

    f = IdentityFinding(
        flag_id="ADDRESS_MISMATCH",
        capability="Bidder Identity",
        message="address differs",
        evidence_refs=["e1", "e2"],
        compared_values=["A", "B"],
        normalized_values=["a", "b"],
        left_document_id="d1",
        right_document_id="d2",
    )
    _roundtrip(f, "identity_finding")


def test_verification_finding_roundtrip():
    from compliance_engine.flags import FlagSeverity
    from ai_verification.models.contracts import VerificationFinding

    f = VerificationFinding(
        finding_id="f1",
        bidder_id="b1",
        flag_id="ADDRESS_MISMATCH",
        severity=FlagSeverity.MEDIUM,
        confidence=0.8,
        explanation="address mismatch",
        evidence_refs=["e1"],
    )
    _roundtrip(f, "verification_finding")


def test_similarity_trace_roundtrip():
    from ai_verification.cross_bidder.trace import (
        CorroborationSignals,
        QualitySignals,
        SimilarityLayer,
        SimilarityTrace,
        TemplateGate,
        TemplateGateStatus,
    )

    t = SimilarityTrace(
        layer=SimilarityLayer.NORMALIZED,
        left_document_id="d1",
        right_document_id="d2",
        left_bidder_id="b1",
        right_bidder_id="b2",
        doc_type="GST",
        normalization_version="1",
        similarity_score=0.9,
        threshold=0.8,
        corroboration=CorroborationSignals(),
        quality=QualitySignals(
            ocr_confidence=0.9, field_confidence=0.9, quality_score=0.9
        ),
        template_gate=TemplateGate(status=TemplateGateStatus.UNKNOWN, score=0.0),
        confidence=0.9,
    )
    _roundtrip(t, "similarity_trace")


def test_financial_outcome_roundtrip():
    from compliance_engine.models.result import ComplianceStatus
    from compliance_engine.financial.models import FinancialCheck
    from compliance_engine.financial.outcome import FinancialOutcome

    o = FinancialOutcome(
        check=FinancialCheck.TURNOVER,
        status=ComplianceStatus.PASS,
        reason="sufficient",
    )
    _roundtrip(o, "financial_outcome")


def test_debarment_roundtrip():
    from compliance_engine.verification.debarment_models import (
        DebarmentRestrictionStatus,
        NormalizedDebarmentData,
    )

    d = NormalizedDebarmentData(
        restriction_status=DebarmentRestrictionStatus.CLEAR,
    )
    _roundtrip(d, "normalized_debarment_data")


def test_evidence_quality_roundtrip():
    from ai_verification.evidence_quality.assessment import (
        EvidenceQualityAssessment,
        QualityComponentScores,
    )
    from ai_verification.evidence_quality.state import QualityState

    a = EvidenceQualityAssessment(
        state=QualityState.GOOD,
        quality_score=0.9,
        components=QualityComponentScores(
            ocr_quality=0.9,
            field_quality=0.9,
            completeness=0.9,
            metadata_reliability=0.9,
        ),
    )
    _roundtrip(a, "evidence_quality_assessment")
def test_identity_aggregation_roundtrip():
    from ai_verification.identity.models import IdentityAggregation

    agg = IdentityAggregation(
        bidder_id="b1",
        observations=(),
        comparisons=(),
        verified_sources=(),
        insufficient_sources=(),
        disagreeing_pairs=(),
        normalization_version="1",
    )
    _roundtrip(agg, "identity_aggregation")


def test_cross_document_aggregation_roundtrip():
    from ai_verification.cross_document.models import CrossDocumentAggregation

    agg = CrossDocumentAggregation(
        bidder_id="b1",
        observations=(),
        comparisons=(),
        dimension_summaries=(),
        mismatching_comparisons=(),
        insufficient_evidence_comparisons=(),
        normalization_version="1",
    )
    _roundtrip(agg, "cross_document_aggregation")


def test_document_meta_roundtrip():
    from ai_verification.cross_bidder.document_artifact_store import DocumentMeta

    m = DocumentMeta(
        document_type="GST",
        ocr_confidence=0.9,
        document_type_confidence=0.9,
    )
    _roundtrip(m, "document_meta")


def test_unknown_artifact_type_raises():
    from infrastructure.serialization import SerializedArtifact

    env = SerializedArtifact(artifact_type="nope", schema_version=1, data={})
    with pytest.raises(UnknownArtifactTypeError):
        deserialize_artifact(env)