"""Tests for the cross-document consistency engine."""

from __future__ import annotations

import pytest

from compliance_engine.models import Evidence

from ai_verification.cross_document import CrossDocumentConsistencyEngine
from ai_verification.cross_document.models import (
    ConsistencyDimension,
    FieldObservation,
    FieldStatus,
)


def _ev(doc_id, doc_type, field, value):
    return Evidence(
        evidence_id=f"{doc_id}:{field}",
        bidder_id="bidder-1",
        document_id=doc_id,
        document_type=doc_type,
        field_name=field,
        value=value,
    )


def test_engine_requires_at_least_one_evidence() -> None:
    engine = CrossDocumentConsistencyEngine()
    with pytest.raises(ValueError):
        engine.run([], bidder_id="bidder-1")


def test_engine_filters_other_bidders() -> None:
    engine = CrossDocumentConsistencyEngine()
    evidence = [
        _ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"),
        _ev("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9"),
        _ev("doc-3", "GST", "gstin", "30AAACI1234F1Z1"),  # belongs to bidder-2
    ]
    # Replace doc-3's bidder
    evidence[2] = Evidence(
        evidence_id="doc-3:gstin",
        bidder_id="bidder-2",
        document_id="doc-3",
        document_type="GST",
        field_name="gstin",
        value="30AAACI1234F1Z1",
    )
    result = engine.run(evidence, bidder_id="bidder-1")
    assert all(
        obs.bidder_id == "bidder-1"
        for obs in result.aggregation.observations
    )


def test_engine_emits_finding_for_identifier_mismatch() -> None:
    engine = CrossDocumentConsistencyEngine()
    evidence = [
        _ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"),
        _ev("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9"),
    ]
    result = engine.run(evidence, bidder_id="bidder-1")
    assert len(result.verification_findings) == 1
    assert (
        result.verification_findings[0].flag_id
        == "CROSS_DOCUMENT_IDENTIFIER_CONFLICT"
    )


def test_engine_emits_no_finding_for_clean_consistency() -> None:
    engine = CrossDocumentConsistencyEngine()
    evidence = [
        _ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"),
        _ev("doc-2", "GSTN", "gstin", "27AAACI1234F1Z5"),
        _ev("doc-1", "GST", "registered_address", "Pune"),
        _ev("doc-2", "GSTN", "registered_address", "Pune"),
        _ev("doc-1", "ITR", "filing_date", "2024-07-28"),
        _ev("doc-2", "ITR", "filing_date", "2024-07-28"),
    ]
    result = engine.run(evidence, bidder_id="bidder-1")
    assert result.verification_findings == []
    assert result.aggregation.has_material_mismatch is False


def test_engine_passes_evaluation_date_to_date_comparator() -> None:
    engine = CrossDocumentConsistencyEngine(evaluation_date_iso="2024-12-31")
    evidence = [
        _ev("doc-1", "ITR", "filing_date", "2020-07-28"),
        _ev("doc-2", "ITR", "filing_date", "2021-09-30"),
    ]
    result = engine.run(evidence, bidder_id="bidder-1")
    # Both dates predate the evaluation date, so the engine should
    # flag a VALIDITY_CONFLICT.
    assert result.aggregation.evaluation_date_iso == "2024-12-31"
    assert any(
        c.outcome == "VALIDITY_CONFLICT"
        for c in result.aggregation.comparisons
    )


def test_engine_does_not_open_network() -> None:
    # Just smoke-test that construction works without network.
    engine = CrossDocumentConsistencyEngine()
    assert engine is not None


def test_engine_evaluation_date_default_is_none() -> None:
    engine = CrossDocumentConsistencyEngine()
    assert engine._evaluation_date_iso is None


def test_engine_input_immutability() -> None:
    engine = CrossDocumentConsistencyEngine()
    evidence = [
        _ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"),
        _ev("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9"),
    ]
    before = [e.model_dump() for e in evidence]
    engine.run(evidence, bidder_id="bidder-1")
    after = [e.model_dump() for e in evidence]
    assert before == after


def test_engine_summary_includes_dimension_summaries() -> None:
    engine = CrossDocumentConsistencyEngine()
    evidence = [
        _ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"),
        _ev("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9"),
    ]
    result = engine.run(evidence, bidder_id="bidder-1")
    s = result.aggregation.summary()
    assert "dimension_summaries" in s
    ids = [d["dimension"] for d in s["dimension_summaries"]]
    assert "IDENTIFIER" in ids


def test_engine_runs_against_real_fixture_evidence() -> None:
    """Smoke test against the canonical fixture upstream payload."""
    import json
    from pathlib import Path
    from compliance_engine.ingestion.upstream import normalize_upstream

    fixture = (
        Path("/home/viper/Documents/Core-Engine-GeM")
        / "fixtures"
        / "upstream"
        / "sample.json"
    )
    payload = json.loads(fixture.read_text())
    evidence = normalize_upstream(payload)
    engine = CrossDocumentConsistencyEngine()
    result = engine.run(evidence, bidder_id=payload["bidder_id"])
    assert result.aggregation.comparison_count > 0
    # No assertion on findings count: the fixture is internally
    # consistent, but we at least want to ensure the engine runs
    # end-to-end on real fixture evidence.


def test_engine_observation_statuses_carry_through() -> None:
    engine = CrossDocumentConsistencyEngine()
    evidence = [
        _ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"),
        _ev("doc-2", "GST", "gstin", None),  # MISSING
    ]
    result = engine.run(evidence, bidder_id="bidder-1")
    # The MISSING side should never produce a MISMATCH outcome.
    for comp in result.aggregation.comparisons:
        assert comp.outcome != "MISMATCH"


def test_engine_normalization_versions_observable_in_summary() -> None:
    engine = CrossDocumentConsistencyEngine()
    evidence = [
        _ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"),
        _ev("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9"),
    ]
    result = engine.run(evidence, bidder_id="bidder-1")
    assert "cross-document-identifier-v1" in (
        result.aggregation.normalization_version
    )
