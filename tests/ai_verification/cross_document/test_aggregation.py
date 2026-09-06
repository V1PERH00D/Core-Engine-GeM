"""Tests for per-bidder aggregation."""

from __future__ import annotations

import pytest

from compliance_engine.models import Evidence

from ai_verification.cross_document import extraction as _extraction
from ai_verification.cross_document.aggregation import aggregate
from ai_verification.cross_document.comparison import compare_all
from ai_verification.cross_document.models import (
    ConsistencyDimension,
    DimensionSummary,
    FieldObservation,
)


extract_observation = _extraction.extract_observation


def _obs(doc_id: str, doc_type: str, field: str, value):
    return extract_observation(
        Evidence(
            evidence_id=f"{doc_id}:{field}",
            bidder_id="bidder-1",
            document_id=doc_id,
            document_type=doc_type,
            field_name=field,
            value=value,
        )
    )


def test_aggregate_requires_at_least_one_observation() -> None:
    with pytest.raises(ValueError):
        aggregate("bidder-1", [], [])


def test_aggregate_rejects_mixed_bidder_ids() -> None:
    obs1 = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    obs2 = _obs("doc-2", "GST", "gstin", "29AAACI1234F1Z9")
    obs2_with_wrong_bidder = FieldObservation(
        bidder_id="bidder-2",
        document_id=obs2.document_id,
        document_type=obs2.document_type,
        field_name=obs2.field_name,
        evidence_id=obs2.evidence_id,
        original_value=obs2.original_value,
        normalized_value=obs2.normalized_value,
        dimension=obs2.dimension,
        identifier_kind=obs2.identifier_kind,
        date_role=obs2.date_role,
        status=obs2.status,
    )
    with pytest.raises(ValueError):
        aggregate("bidder-1", [obs1, obs2_with_wrong_bidder], [])


def test_aggregate_summary_counts() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9")  # mismatch
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    assert isinstance(agg, object)
    assert agg.bidder_id == "bidder-1"
    assert agg.comparison_count == 1
    assert agg.mismatch_count == 1
    assert agg.has_material_mismatch is True


def test_aggregate_dimension_summary_present_for_each_dimension() -> None:
    obs = [
        _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5"),
        _obs("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9"),
        _obs("doc-3", "PAN", "pan_number", "AAACI1234F"),
    ]
    comparisons = compare_all(obs)
    agg = aggregate("bidder-1", obs, comparisons)
    dims = [s.dimension for s in agg.dimension_summaries]
    assert dims == [
        ConsistencyDimension.IDENTIFIER,
        ConsistencyDimension.ADDRESS,
        ConsistencyDimension.DATE,
        ConsistencyDimension.PRODUCT,
        ConsistencyDimension.MANUFACTURER,
    ]


def test_aggregate_summary_returns_dict() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9")
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    s = agg.summary()
    assert s["bidder_id"] == "bidder-1"
    assert s["has_material_mismatch"] is True
    assert s["comparison_count"] == 1
    assert s["mismatch_count"] == 1
    assert isinstance(s["dimension_summaries"], list)


def test_aggregate_no_mismatches() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "GSTN", "gstin", "27AAACI1234F1Z5")
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    assert agg.has_material_mismatch is False
    assert agg.mismatch_count == 0


def test_aggregate_normalization_version_stamped() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "GSTN", "gstin", "27AAACI1234F1Z5")
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    assert "+" in agg.normalization_version
    assert "cross-document-identifier-v1" in agg.normalization_version
