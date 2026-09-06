"""Tests for pairwise comparison semantics."""

from __future__ import annotations

from ai_verification.cross_document import extraction as _extraction
from ai_verification.cross_document.comparison import (
    compare_all,
    compare_pair,
    enumerate_pairs,
)
from ai_verification.cross_document.models import (
    AddressComparisonOutcome,
    DateComparisonOutcome,
    FieldObservation,
    FieldStatus,
    IdentifierComparisonOutcome,
    ManufacturerComparisonOutcome,
    ProductComparisonOutcome,
)

extract_observation = _extraction.extract_observation


def _obs(document_id: str, document_type: str, field_name: str, value):
    return extract_observation(
        __import__('compliance_engine.models', fromlist=['Evidence']).Evidence(
            evidence_id=f"{document_id}:{field_name}",
            bidder_id="bidder-1",
            document_id=document_id,
            document_type=document_type,
            field_name=field_name,
            value=value,
        )
    )


# -----------------------------------------------------------------------
# Identifier comparison
# -----------------------------------------------------------------------


def test_identifier_exact_match() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "GST", "gstin", "27AAACI1234F1Z5")
    comp = compare_pair(left, right)
    assert comp.outcome == IdentifierComparisonOutcome.MATCH_EXACT.value
    assert comp.is_mismatch() is False


def test_identifier_normalized_match() -> None:
    left = _obs("doc-1", "GST", "gstin", "27aaaci1234f1z5")
    right = _obs("doc-2", "GST", "gstin", "27AAACI1234F1Z5")
    comp = compare_pair(left, right)
    assert comp.outcome == IdentifierComparisonOutcome.MATCH_NORMALIZED.value


def test_identifier_mismatch() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9")
    comp = compare_pair(left, right)
    assert comp.outcome == IdentifierComparisonOutcome.MISMATCH.value
    assert comp.is_mismatch() is True


def test_identifier_incompatible_types_recorded() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "PAN", "pan_number", "AAACI1234F")
    comp = compare_pair(left, right)
    assert comp.outcome == IdentifierComparisonOutcome.INSUFFICIENT_EVIDENCE.value
    assert "Incompatible identifier kinds" in comp.comparability_reason


def test_identifier_normalized_preserves_originals() -> None:
    left = _obs("doc-1", "GST", "gstin", "27aaaci1234f1z5")
    right = _obs("doc-2", "GST", "gstin", "27AAACI1234F1Z5")
    comp = compare_pair(left, right)
    assert comp.left_original == "27aaaci1234f1z5"
    assert comp.right_original == "27AAACI1234F1Z5"
    assert comp.left_normalized == "27AAACI1234F1Z5"
    assert comp.right_normalized == "27AAACI1234F1Z5"


def test_identifier_missing_value_is_insufficient_evidence() -> None:
    left = _obs("doc-1", "GST", "gstin", None)
    right = _obs("doc-2", "GST", "gstin", "27AAACI1234F1Z5")
    comp = compare_pair(left, right)
    assert comp.outcome == IdentifierComparisonOutcome.INSUFFICIENT_EVIDENCE.value


def test_identifier_self_comparison_is_insufficient() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    comp = compare_pair(left, left)
    assert comp.outcome == IdentifierComparisonOutcome.INSUFFICIENT_EVIDENCE.value
    assert comp.is_self_comparison is True


# -----------------------------------------------------------------------
# Address comparison
# -----------------------------------------------------------------------


def test_address_exact_match() -> None:
    left = _obs("doc-1", "GST", "registered_address", "Pune, Maharashtra")
    right = _obs("doc-2", "GST", "registered_address", "Pune, Maharashtra")
    comp = compare_pair(left, right)
    assert comp.outcome == AddressComparisonOutcome.EXACT.value


def test_address_normalized_match() -> None:
    left = _obs("doc-1", "GST", "registered_address", "Pune,  Maharashtra")
    right = _obs("doc-2", "GST", "registered_address", "pune, maharashtra")
    comp = compare_pair(left, right)
    assert comp.outcome == AddressComparisonOutcome.NORMALIZED_MATCH.value


def test_address_mismatch() -> None:
    left = _obs("doc-1", "GST", "registered_address", "Pune, Maharashtra")
    right = _obs("doc-2", "GST", "registered_address", "Delhi, Delhi")
    comp = compare_pair(left, right)
    assert comp.outcome == AddressComparisonOutcome.MISMATCH.value


def test_address_no_fuzzy_match() -> None:
    # Very similar but not identical after normalization.
    left = _obs("doc-1", "GST", "registered_address", "Plot 42, Pune")
    right = _obs("doc-2", "GST", "registered_address", "Plot 43, Pune")
    comp = compare_pair(left, right)
    assert comp.outcome == AddressComparisonOutcome.MISMATCH.value


def test_address_missing_is_insufficient_evidence() -> None:
    left = _obs("doc-1", "GST", "registered_address", None)
    right = _obs("doc-2", "GST", "registered_address", "Pune")
    comp = compare_pair(left, right)
    assert comp.outcome == AddressComparisonOutcome.INSUFFICIENT_EVIDENCE.value


# -----------------------------------------------------------------------
# Date comparison
# -----------------------------------------------------------------------


def test_date_match() -> None:
    left = _obs("doc-1", "ITR", "filing_date", "2024-07-28")
    right = _obs("doc-2", "ITR", "filing_date", "2024-07-28")
    comp = compare_pair(left, right)
    assert comp.outcome == DateComparisonOutcome.MATCH.value


def test_date_mismatch() -> None:
    left = _obs("doc-1", "ITR", "filing_date", "2024-07-28")
    right = _obs("doc-2", "ITR", "filing_date", "2024-09-30")
    comp = compare_pair(left, right)
    assert comp.outcome == DateComparisonOutcome.MISMATCH.value


def test_date_unrelated_to_each_other_not_compared() -> None:
    left = _obs("doc-1", "ITR", "filing_date", "2024-07-28")
    right = _obs("doc-2", "ITR", "assessment_year", "2024-25")
    comp = compare_pair(left, right)
    assert comp.outcome == DateComparisonOutcome.INSUFFICIENT_EVIDENCE.value


def test_date_validity_conflict_with_evaluation_date() -> None:
    # Both dates predate the explicit evaluation date.
    left = _obs("doc-1", "ITR", "filing_date", "2020-07-28")
    right = _obs("doc-2", "ITR", "filing_date", "2021-09-30")
    comp = compare_pair(left, right, evaluation_date_iso="2024-01-01")
    assert comp.outcome == DateComparisonOutcome.VALIDITY_CONFLICT.value


def test_date_explicit_evaluation_date_no_conflict_when_dates_are_recent() -> None:
    left = _obs("doc-1", "ITR", "filing_date", "2024-07-28")
    right = _obs("doc-2", "ITR", "filing_date", "2024-09-30")
    comp = compare_pair(left, right, evaluation_date_iso="2024-01-01")
    # Dates differ but are post evaluation date; not a validity conflict.
    assert comp.outcome == DateComparisonOutcome.MISMATCH.value


def test_date_invalid_value_is_insufficient() -> None:
    left = _obs("doc-1", "ITR", "filing_date", "not a date")
    right = _obs("doc-2", "ITR", "filing_date", "2024-07-28")
    comp = compare_pair(left, right)
    assert comp.outcome == DateComparisonOutcome.INSUFFICIENT_EVIDENCE.value


# -----------------------------------------------------------------------
# Product comparison
# -----------------------------------------------------------------------


def test_product_exact_match() -> None:
    left = _obs("doc-1", "MAKE_IN_INDIA", "supplier_class", "Class-I")
    right = _obs("doc-2", "MAKE_IN_INDIA", "supplier_class", "Class-I")
    comp = compare_pair(left, right)
    assert comp.outcome == ProductComparisonOutcome.EXACT.value


def test_product_normalized_match() -> None:
    left = _obs("doc-1", "MAKE_IN_INDIA", "supplier_class", "Class-I")
    right = _obs("doc-2", "MAKE_IN_INDIA", "supplier_class", "class-i")
    comp = compare_pair(left, right)
    assert comp.outcome == ProductComparisonOutcome.NORMALIZED_MATCH.value


def test_product_mismatch() -> None:
    left = _obs("doc-1", "MAKE_IN_INDIA", "supplier_class", "Class-I")
    right = _obs("doc-2", "MAKE_IN_INDIA", "supplier_class", "Class-II")
    comp = compare_pair(left, right)
    assert comp.outcome == ProductComparisonOutcome.MISMATCH.value


def test_product_no_fuzzy_match() -> None:
    left = _obs("doc-1", "MAKE_IN_INDIA", "supplier_class", "Class-I")
    right = _obs("doc-2", "MAKE_IN_INDIA", "supplier_class", "Class-IV")
    comp = compare_pair(left, right)
    assert comp.outcome == ProductComparisonOutcome.MISMATCH.value


# -----------------------------------------------------------------------
# Manufacturer comparison
# -----------------------------------------------------------------------


def test_manufacturer_exact_match() -> None:
    left = _obs("doc-1", "OEM", "manufacturer", "Acme Industries Ltd")
    right = _obs("doc-2", "OEM", "manufacturer", "Acme Industries Ltd")
    comp = compare_pair(left, right)
    assert comp.outcome == ManufacturerComparisonOutcome.MATCH_EXACT.value


def test_manufacturer_normalized_match() -> None:
    left = _obs("doc-1", "OEM", "manufacturer", "Acme Industries Ltd")
    right = _obs("doc-2", "OEM", "manufacturer", "  ACME   Industries  Ltd  ")
    comp = compare_pair(left, right)
    assert comp.outcome == ManufacturerComparisonOutcome.MATCH_NORMALIZED.value


def test_manufacturer_mismatch() -> None:
    left = _obs("doc-1", "OEM", "manufacturer", "Acme Industries Ltd")
    right = _obs("doc-2", "OEM", "manufacturer", "Zenith Corp")
    comp = compare_pair(left, right)
    assert comp.outcome == ManufacturerComparisonOutcome.MISMATCH.value


def test_manufacturer_does_not_invent_equivalence_for_abbreviations() -> None:
    # The manufacturer normalizer is deliberately conservative; it
    # does NOT rewrite ``Pvt Ltd`` to ``Private Limited``.
    left = _obs("doc-1", "OEM", "manufacturer", "Acme Pvt Ltd")
    right = _obs("doc-2", "OEM", "manufacturer", "Acme Private Limited")
    comp = compare_pair(left, right)
    assert comp.outcome == ManufacturerComparisonOutcome.MISMATCH.value


# -----------------------------------------------------------------------
# Pair enumeration
# -----------------------------------------------------------------------


def test_enumerate_pairs_no_self_pairs() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "GSTN", "gstin", "27AAACI1234F1Z5")
    pairs = enumerate_pairs([left, right])
    assert len(pairs) == 1
    assert pairs[0][0] is left
    assert pairs[0][1] is right


def test_enumerate_pairs_emits_each_pair_once() -> None:
    obs = [
        _obs(f"doc-{i}", "GST", "gstin", f"27AAACI{i:04d}F1Z5")
        for i in range(4)
    ]
    pairs = enumerate_pairs(obs)
    assert len(pairs) == 6  # 4 choose 2


def test_enumerate_pairs_skips_uncomparable() -> None:
    # Unclassified observation is filtered out.
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    unclass = _obs("doc-2", "UNKNOWN", "foo", "bar")
    pairs = enumerate_pairs([left, unclass])
    assert pairs == []


def test_compare_all_runs_all_pairs() -> None:
    obs = [
        _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5"),
        _obs("doc-2", "GSTN", "gstin", "27AAACI1234F1Z5"),
        _obs("doc-3", "PAN", "pan_number", "AAACI1234F"),
    ]
    comparisons = compare_all(obs)
    # doc-1 vs doc-2 (both GSTIN), doc-1 vs doc-3 (incompatible
    # identifier kinds), doc-2 vs doc-3 (incompatible).
    assert len(comparisons) == 3


def test_compare_all_carries_normalization_version() -> None:
    obs = [
        _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5"),
        _obs("doc-2", "GSTN", "gstin", "27AAACI1234F1Z5"),
    ]
    comparisons = compare_all(obs)
    for comp in comparisons:
        assert comp.normalization_version
        assert comp.normalization_version.startswith("cross-document")
