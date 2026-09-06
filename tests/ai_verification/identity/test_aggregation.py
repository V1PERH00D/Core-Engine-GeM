"""Tests for the identity aggregation layer."""

from __future__ import annotations

import pytest

from ai_verification.identity import (
    ComparisonOutcome,
    IdentityObservation,
    IdentityReconciliationEngine,
    SourceAvailability,
    normalize_legal_name,
)
from ai_verification.identity.aggregation import aggregate


def _obs(
    *,
    source: str,
    verification_id: str,
    original: str | None,
    status: SourceAvailability = SourceAvailability.VERIFIED,
    bidder_id: str = "bidder-1",
) -> IdentityObservation:
    return IdentityObservation(
        source=source,
        bidder_id=bidder_id,
        verification_id=verification_id,
        original_name=original,
        normalized_name=normalize_legal_name(original),
        source_status=status,
        queried_identifier=None,
        evidence_ref=None,
        document_ref=None,
        normalization_version="identity-name-v1",
    )


def test_empty_observation_list_raises() -> None:
    with pytest.raises(ValueError):
        aggregate([])


def test_observations_from_different_bidders_raise() -> None:
    obs = [
        _obs(source="GST", verification_id="V1", original="A", bidder_id="b1"),
        _obs(source="PAN", verification_id="V2", original="A", bidder_id="b2"),
    ]
    with pytest.raises(ValueError):
        aggregate(obs)


def test_aggregation_summarizes_verified_and_insufficient_sources() -> None:
    obs = [
        _obs(source="GST", verification_id="V1", original="ACME"),
        _obs(
            source="PAN",
            verification_id="V2",
            original="ACME",
            status=SourceAvailability.UNAVAILABLE,
        ),
        _obs(source="UDYAM", verification_id="V3", original="ACME"),
        _obs(
            source="MCA",
            verification_id="V4",
            original=None,
            status=SourceAvailability.NOT_FOUND,
        ),
    ]
    agg = aggregate(obs)
    assert agg.verified_sources == ("GST", "UDYAM")
    assert agg.insufficient_sources == ("PAN", "MCA")
    assert agg.verified_count == 2
    assert agg.disagreeing_pair_count == 0


def test_aggregation_disagreeing_pairs_filter_correctly() -> None:
    obs = [
        _obs(
            source="GST",
            verification_id="V1",
            original="ACME ENTERPRISES PRIVATE LIMITED",
        ),
        _obs(
            source="PAN",
            verification_id="V2",
            original="ACME TRADING PRIVATE LIMITED",
        ),
        _obs(
            source="UDYAM",
            verification_id="V3",
            original="ACME ENTERPRISES PRIVATE LIMITED",
        ),
    ]
    agg = aggregate(obs)
    assert agg.disagreeing_pair_count == 2
    for pair in agg.disagreeing_pairs:
        assert pair.outcome == ComparisonOutcome.MISMATCH


def test_aggregation_has_material_mismatch_property() -> None:
    obs = [
        _obs(source="GST", verification_id="V1", original="A"),
        _obs(source="PAN", verification_id="V2", original="B"),
    ]
    agg = aggregate(obs)
    assert agg.has_material_mismatch is True

    obs_match = [
        _obs(source="GST", verification_id="V1", original="A"),
        _obs(source="PAN", verification_id="V2", original="a"),
    ]
    agg_match = aggregate(obs_match)
    assert agg_match.has_material_mismatch is False


def test_aggregation_summary_is_json_safe() -> None:
    obs = [
        _obs(source="GST", verification_id="V1", original="A"),
        _obs(source="PAN", verification_id="V2", original="A"),
    ]
    agg = aggregate(obs)
    summary = agg.summary()
    assert summary["bidder_id"] == "bidder-1"
    assert summary["verified_sources"] == ["GST", "PAN"]
    assert summary["has_material_mismatch"] is False
    assert "normalization_version" in summary


def test_aggregation_with_multiple_sources_all_matching() -> None:
    obs = [
        _obs(source="GST", verification_id="V1", original="ACME"),
        _obs(source="PAN", verification_id="V2", original="acme"),
        _obs(source="UDYAM", verification_id="V3", original="ACME."),
        _obs(source="MCA", verification_id="V4", original="ACME"),
    ]
    agg = aggregate(obs)
    assert agg.verified_count == 4
    assert agg.disagreeing_pair_count == 0
    for c in agg.comparisons:
        assert c.outcome in (
            ComparisonOutcome.MATCH_EXACT,
            ComparisonOutcome.MATCH_NORMALIZED,
        )


def test_aggregation_with_one_unavailable_source() -> None:
    obs = [
        _obs(source="GST", verification_id="V1", original="ACME"),
        _obs(
            source="PAN",
            verification_id="V2",
            original=None,
            status=SourceAvailability.UNAVAILABLE,
        ),
        _obs(source="UDYAM", verification_id="V3", original="acme."),
    ]
    agg = aggregate(obs)
    outcomes = {(c.left_source, c.right_source): c.outcome for c in agg.comparisons}
    assert outcomes[("GST", "UDYAM")] == ComparisonOutcome.MATCH_NORMALIZED
    assert outcomes[("GST", "PAN")] == ComparisonOutcome.INSUFFICIENT_EVIDENCE
    assert outcomes[("PAN", "UDYAM")] == ComparisonOutcome.INSUFFICIENT_EVIDENCE


def test_aggregation_handles_inactive_source_gracefully() -> None:
    obs = [
        _obs(source="GST", verification_id="V1", original="ACME"),
        _obs(
            source="MCA",
            verification_id="V2",
            original="OTHER BIDDER PRIVATE LIMITED",
            status=SourceAvailability.INACTIVE,
        ),
    ]
    agg = aggregate(obs)
    assert all(
        c.outcome == ComparisonOutcome.INSUFFICIENT_EVIDENCE
        for c in agg.comparisons
    )


def test_aggregation_skips_duplicate_source_observations() -> None:
    obs = [
        _obs(source="GST", verification_id="V1", original="A"),
        _obs(source="GST", verification_id="V2", original="B"),
        _obs(source="PAN", verification_id="V3", original="A"),
    ]
    agg = aggregate(obs)
    # Only the first GST observation is used; the second is suppressed.
    assert len(agg.comparisons) == 1
    pair = agg.comparisons[0]
    assert pair.left_source == "GST" and pair.right_source == "PAN"
    assert pair.left_verification_id == "V1"  # the FIRST GST one
    assert agg.verified_sources == ("GST", "PAN")


def test_aggregation_through_real_verification_records() -> None:
    from tests.ai_verification.identity._builders import (
        gst_verified,
        mca_verified,
        pan_verified,
        udyam_verified,
    )

    engine = IdentityReconciliationEngine()
    records = [
        gst_verified(legal_name="ACME ENTERPRISES PRIVATE LIMITED"),
        pan_verified(name_on_pan="ACME TRADING PRIVATE LIMITED"),
        udyam_verified(enterprise_name="ACME ENTERPRISES PRIVATE LIMITED"),
        mca_verified(company_name="ACME ENTERPRISES PRIVATE LIMITED"),
    ]
    agg = engine.reconcile(records, bidder_id="bidder-1").aggregation
    assert agg.bidder_id == "bidder-1"
    assert agg.verified_count == 4
    # PAN disagrees with GST, UDYAM, and MCA; the other three agree.
    assert agg.disagreeing_pair_count == 3
    assert agg.has_material_mismatch is True
    disagreeing_pair_keys = {
        (p.left_source, p.right_source) for p in agg.disagreeing_pairs
    }
    assert disagreeing_pair_keys == {
        ("GST", "PAN"),
        ("PAN", "UDYAM"),
        ("PAN", "MCA"),
    }


def test_aggregation_through_real_verification_records_all_agree() -> None:
    from tests.ai_verification.identity._builders import (
        gst_verified,
        mca_verified,
        pan_verified,
        udyam_verified,
    )

    engine = IdentityReconciliationEngine()
    records = [
        gst_verified(legal_name="ACME ENTERPRISES"),
        pan_verified(name_on_pan="acme enterprises"),
        udyam_verified(enterprise_name="ACME Enterprises."),
        mca_verified(company_name="ACME enterprises"),
    ]
    agg = engine.reconcile(records, bidder_id="bidder-1").aggregation
    assert agg.verified_count == 4
    assert agg.disagreeing_pair_count == 0
    assert agg.has_material_mismatch is False