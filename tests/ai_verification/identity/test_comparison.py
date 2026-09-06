"""Tests for pairwise identity comparison."""

from __future__ import annotations

from ai_verification.identity import (
    ComparisonOutcome,
    IdentityObservation,
    IdentityReconciliationEngine,
    SourceAvailability,
    normalize_legal_name,
)
from ai_verification.identity.comparison import (
    SUPPORTED_SOURCES,
    compare_pair,
    enumerate_pairs,
)


def _obs(
    *,
    source: str,
    verification_id: str,
    original: str | None,
    status: SourceAvailability = SourceAvailability.VERIFIED,
    evidence_id: str | None = "ev-x",
    document_id: str | None = "doc-x",
) -> IdentityObservation:
    return IdentityObservation(
        source=source,
        bidder_id="bidder-1",
        verification_id=verification_id,
        original_name=original,
        normalized_name=normalize_legal_name(original),
        source_status=status,
        queried_identifier="ID-1",
        evidence_ref=evidence_id,
        document_ref=document_id,
        normalization_version="identity-name-v1",
    )


# ---------------------------------------------------------------------------
# Pair enumeration
# ---------------------------------------------------------------------------


def test_enumerate_pairs_covers_all_distinct_pairs() -> None:
    obs = [
        _obs(source="GST", verification_id="V-GST", original="A"),
        _obs(source="PAN", verification_id="V-PAN", original="A"),
        _obs(source="UDYAM", verification_id="V-UDYAM", original="A"),
        _obs(source="MCA", verification_id="V-MCA", original="A"),
    ]
    pairs = enumerate_pairs(obs)
    pair_keys = {(p[0].source, p[1].source) for p in pairs}
    expected = {
        ("GST", "PAN"),
        ("GST", "UDYAM"),
        ("GST", "MCA"),
        ("PAN", "UDYAM"),
        ("PAN", "MCA"),
        ("UDYAM", "MCA"),
    }
    assert pair_keys == expected


def test_enumerate_pairs_deterministic_order() -> None:
    obs = [
        _obs(source="MCA", verification_id="V-MCA", original="A"),
        _obs(source="PAN", verification_id="V-PAN", original="A"),
        _obs(source="GST", verification_id="V-GST", original="A"),
    ]
    pairs = enumerate_pairs(obs)
    keys = [(p[0].source, p[1].source) for p in pairs]
    # Pairs follow SUPPORTED_SOURCES order: GST first, then PAN, MCA.
    assert keys == [("GST", "PAN"), ("GST", "MCA"), ("PAN", "MCA")]


def test_enumerate_pairs_skips_self_pairs() -> None:
    obs = [
        _obs(source="GST", verification_id="V-GST-1", original="A"),
        _obs(source="GST", verification_id="V-GST-2", original="A"),
    ]
    pairs = enumerate_pairs(obs)
    assert pairs == []


def test_enumerate_pairs_dedupes_same_source_observations() -> None:
    obs = [
        _obs(source="GST", verification_id="V-GST-1", original="A"),
        _obs(source="GST", verification_id="V-GST-2", original="A"),
        _obs(source="PAN", verification_id="V-PAN", original="A"),
    ]
    pairs = enumerate_pairs(obs)
    assert len(pairs) == 1
    assert pairs[0][0].verification_id == "V-GST-1"


def test_supported_sources_contains_canonical_four() -> None:
    assert set(SUPPORTED_SOURCES) == {"GST", "PAN", "UDYAM", "MCA"}


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


def test_exact_match_byte_identical_names() -> None:
    left = _obs(source="GST", verification_id="V1", original="ACME PVT LTD")
    right = _obs(source="PAN", verification_id="V2", original="ACME PVT LTD")
    result = compare_pair(left, right)
    assert result.outcome == ComparisonOutcome.MATCH_EXACT


def test_normalized_match_case_whitespace_difference() -> None:
    left = _obs(
        source="GST", verification_id="V1", original="ACME  Enterprises"
    )
    right = _obs(
        source="PAN", verification_id="V2", original="acme enterprises."
    )
    result = compare_pair(left, right)
    assert result.outcome == ComparisonOutcome.MATCH_NORMALIZED
    assert (
        result.left_normalized
        == result.right_normalized
        == "acme enterprises"
    )


def test_true_mismatch_when_names_materially_differ() -> None:
    left = _obs(
        source="GST",
        verification_id="V-GST",
        original="ACME ENTERPRISES PRIVATE LIMITED",
    )
    right = _obs(
        source="PAN",
        verification_id="V-PAN",
        original="ACME TRADING PRIVATE LIMITED",
    )
    result = compare_pair(left, right)
    assert result.outcome == ComparisonOutcome.MISMATCH
    assert result.left_normalized != result.right_normalized


# ---------------------------------------------------------------------------
# Insufficient evidence
# ---------------------------------------------------------------------------


def test_insufficient_when_pan_unavailable() -> None:
    left = _obs(source="GST", verification_id="V1", original="ACME ENTERPRISES")
    right = _obs(
        source="PAN",
        verification_id="V2",
        original="ACME ENTERPRISES",
        status=SourceAvailability.UNAVAILABLE,
    )
    result = compare_pair(left, right)
    assert result.outcome == ComparisonOutcome.INSUFFICIENT_EVIDENCE


def test_insufficient_when_gst_not_found() -> None:
    left = _obs(
        source="GST",
        verification_id="V1",
        original=None,
        status=SourceAvailability.NOT_FOUND,
    )
    right = _obs(source="PAN", verification_id="V2", original="ACME ENTERPRISES")
    result = compare_pair(left, right)
    assert result.outcome == ComparisonOutcome.INSUFFICIENT_EVIDENCE


def test_insufficient_when_udyam_inactive() -> None:
    left = _obs(source="GST", verification_id="V1", original="ACME ENTERPRISES")
    right = _obs(
        source="UDYAM",
        verification_id="V3",
        original="ACME ENTERPRISES",
        status=SourceAvailability.INACTIVE,
    )
    result = compare_pair(left, right)
    assert result.outcome == ComparisonOutcome.INSUFFICIENT_EVIDENCE


def test_insufficient_when_verified_but_name_missing() -> None:
    left = _obs(source="GST", verification_id="V1", original="ACME ENTERPRISES")
    right = _obs(
        source="MCA",
        verification_id="V4",
        original=None,
        status=SourceAvailability.VERIFIED_WITHOUT_NAME,
    )
    result = compare_pair(left, right)
    assert result.outcome == ComparisonOutcome.INSUFFICIENT_EVIDENCE


def test_insufficient_when_not_queried() -> None:
    left = _obs(source="GST", verification_id="V1", original="ACME ENTERPRISES")
    right = _obs(
        source="PAN",
        verification_id="V2",
        original=None,
        status=SourceAvailability.NOT_QUERIED,
    )
    result = compare_pair(left, right)
    assert result.outcome == ComparisonOutcome.INSUFFICIENT_EVIDENCE


def test_compare_pair_handles_same_source_safely() -> None:
    left = _obs(source="GST", verification_id="V1", original="A")
    result = compare_pair(left, left)
    assert result.outcome == ComparisonOutcome.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# Audit propagation
# ---------------------------------------------------------------------------


def test_comparison_preserves_original_and_normalized_names() -> None:
    left = _obs(
        source="GST", verification_id="V-GST", original="  ACME  Enterprises  "
    )
    right = _obs(
        source="PAN", verification_id="V-PAN", original="acme enterprises"
    )
    result = compare_pair(left, right)
    assert result.left_original == "  ACME  Enterprises  "
    assert result.right_original == "acme enterprises"
    assert result.left_normalized == "acme enterprises"
    assert result.right_normalized == "acme enterprises"
    assert result.left_verification_id == "V-GST"
    assert result.right_verification_id == "V-PAN"


def test_comparison_propagates_evidence_and_document_refs() -> None:
    left = _obs(
        source="GST",
        verification_id="V-GST",
        original="ACME ENTERPRISES",
        evidence_id="ev-gst",
        document_id="doc-gst",
    )
    right = _obs(
        source="PAN",
        verification_id="V-PAN",
        original="ACME TRADING PRIVATE LIMITED",
        evidence_id="ev-pan",
        document_id="doc-pan",
    )
    result = compare_pair(left, right)
    assert result.left_evidence_ref == "ev-gst"
    assert result.right_evidence_ref == "ev-pan"
    assert result.left_document_ref == "doc-gst"
    assert result.right_document_ref == "doc-pan"
    assert result.left_queried_identifier == "ID-1"
    assert result.right_queried_identifier == "ID-1"


# ---------------------------------------------------------------------------
# End-to-end through real Verification records
# ---------------------------------------------------------------------------


def test_end_to_end_normalized_match_via_real_verification_records() -> None:
    from tests.ai_verification.identity._builders import (
        gst_verified,
        pan_verified,
    )

    engine = IdentityReconciliationEngine()
    records = [
        gst_verified(legal_name="ACME Enterprises"),
        pan_verified(name_on_pan="acme enterprises"),
    ]
    result = engine.reconcile(records, bidder_id="bidder-1")
    assert result.aggregation.comparisons
    for comp in result.aggregation.comparisons:
        assert comp.outcome == ComparisonOutcome.MATCH_NORMALIZED


def test_end_to_end_mismatch_via_real_verification_records() -> None:
    from tests.ai_verification.identity._builders import (
        gst_verified,
        pan_verified,
    )

    engine = IdentityReconciliationEngine()
    records = [
        gst_verified(legal_name="ACME ENTERPRISES PRIVATE LIMITED"),
        pan_verified(name_on_pan="ACME TRADING PRIVATE LIMITED"),
    ]
    result = engine.reconcile(records, bidder_id="bidder-1")
    assert result.aggregation.disagreeing_pairs
    for comp in result.aggregation.disagreeing_pairs:
        assert comp.outcome == ComparisonOutcome.MISMATCH