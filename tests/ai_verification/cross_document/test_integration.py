"""Integration tests with VerificationEngine and the bidder risk engine."""

from __future__ import annotations

from compliance_engine.models import Evidence

from ai_verification.cross_document import CrossDocumentConsistencyEngine
from ai_verification.engine import VerificationEngine
from ai_verification.models.contracts import VerificationInput


def _ev(doc_id, doc_type, field, value, bidder="bidder-1"):
    return Evidence(
        evidence_id=f"{doc_id}:{field}",
        bidder_id=bidder,
        document_id=doc_id,
        document_type=doc_type,
        field_name=field,
        value=value,
    )


def test_verification_engine_without_cross_document_unchanged() -> None:
    """Default VerificationEngine must not change behaviour."""
    engine = VerificationEngine()
    evidence = [
        _ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"),
        _ev("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9"),
    ]
    result = engine.run(
        VerificationInput(bidder_id="bidder-1", evidence=evidence)
    )
    # No cross-document engine, no findings.
    assert result.findings == []


def test_verification_engine_with_cross_document_component() -> None:
    engine = VerificationEngine(
        cross_document_consistency_engine=CrossDocumentConsistencyEngine(),
    )
    evidence = [
        _ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"),
        _ev("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9"),
    ]
    result = engine.run(
        VerificationInput(bidder_id="bidder-1", evidence=evidence)
    )
    flag_ids = {f.flag_id for f in result.findings}
    assert "CROSS_DOCUMENT_IDENTIFIER_CONFLICT" in flag_ids


def test_verification_engine_handles_empty_evidence() -> None:
    engine = VerificationEngine(
        cross_document_consistency_engine=CrossDocumentConsistencyEngine(),
    )
    result = engine.run(
        VerificationInput(bidder_id="bidder-1", evidence=[])
    )
    # Empty evidence yields no findings (the component is gracefully
    # skipped when there is nothing to compare).
    assert result.findings == []


def test_verification_engine_does_not_mutate_input() -> None:
    engine = VerificationEngine(
        cross_document_consistency_engine=CrossDocumentConsistencyEngine(),
    )
    evidence = [
        _ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"),
        _ev("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9"),
    ]
    before = [e.model_dump() for e in evidence]
    engine.run(VerificationInput(bidder_id="bidder-1", evidence=evidence))
    after = [e.model_dump() for e in evidence]
    assert before == after


def test_verification_engine_with_clean_consistency_no_findings() -> None:
    engine = VerificationEngine(
        cross_document_consistency_engine=CrossDocumentConsistencyEngine(),
    )
    evidence = [
        _ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"),
        _ev("doc-2", "GSTN", "gstin", "27AAACI1234F1Z5"),
        _ev("doc-1", "GST", "registered_address", "Pune"),
        _ev("doc-2", "GSTN", "registered_address", "Pune"),
        _ev("doc-1", "ITR", "filing_date", "2024-07-28"),
        _ev("doc-2", "ITR", "filing_date", "2024-07-28"),
    ]
    result = engine.run(
        VerificationInput(bidder_id="bidder-1", evidence=evidence)
    )
    assert result.findings == []


def test_verification_engine_finding_carries_evidence_refs() -> None:
    engine = VerificationEngine(
        cross_document_consistency_engine=CrossDocumentConsistencyEngine(),
    )
    evidence = [
        _ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"),
        _ev("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9"),
    ]
    result = engine.run(
        VerificationInput(bidder_id="bidder-1", evidence=evidence)
    )
    # Find the cross-document finding.
    cd_finding = next(
        f
        for f in result.findings
        if f.flag_id == "CROSS_DOCUMENT_IDENTIFIER_CONFLICT"
    )
    assert cd_finding.bidder_id == "bidder-1"
    assert "doc-1:gstin" in cd_finding.evidence_refs
    assert "doc-2:gstin" in cd_finding.evidence_refs


def test_cross_document_findings_flow_into_risk_engine() -> None:
    """Cross-document findings should be picked up by the risk engine."""
    from ai_verification.risk import BidderRiskEngine

    engine = VerificationEngine(
        cross_document_consistency_engine=CrossDocumentConsistencyEngine(),
    )
    evidence = [
        _ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"),
        _ev("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9"),
    ]
    result = engine.run(
        VerificationInput(bidder_id="bidder-1", evidence=evidence)
    )
    # Feed the findings into the risk engine.
    risk_engine = BidderRiskEngine()
    risk = risk_engine.assess(
        bidder_id="bidder-1",
        findings=result.findings,
    )
    # The risk engine should emit a signal for the CRITICAL flag.
    # RiskSignal exposes ``correlation_key`` rather than a flat
    # ``flag_id``; check the correlation key.
    assert any(
        s.correlation_key.flag_id == "CROSS_DOCUMENT_IDENTIFIER_CONFLICT"
        for s in risk.signals
    )
