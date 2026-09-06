"""Tests for the typed Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_verification.cross_document.models import (
    AddressComparisonOutcome,
    ConsistencyDimension,
    CrossDocumentAggregation,
    DateComparisonOutcome,
    DateRole,
    DimensionSummary,
    FieldObservation,
    FieldStatus,
    IdentifierComparisonOutcome,
    IdentifierKind,
    ManufacturerComparisonOutcome,
    PairwiseComparison,
    ProductComparisonOutcome,
    outcome_for_dimension,
)


def test_consistency_dimension_members() -> None:
    assert set(ConsistencyDimension) == {
        ConsistencyDimension.IDENTIFIER,
        ConsistencyDimension.ADDRESS,
        ConsistencyDimension.DATE,
        ConsistencyDimension.PRODUCT,
        ConsistencyDimension.MANUFACTURER,
    }


def test_field_status_members() -> None:
    assert set(FieldStatus) == {
        FieldStatus.NOT_QUERIED,
        FieldStatus.AVAILABLE,
        FieldStatus.MISSING,
        FieldStatus.UNAVAILABLE,
        FieldStatus.INVALID,
        FieldStatus.INSUFFICIENT_EVIDENCE,
    }


def test_date_role_members() -> None:
    assert set(DateRole) == {
        DateRole.ISSUE_DATE,
        DateRole.EFFECTIVE_DATE,
        DateRole.EXPIRY_DATE,
        DateRole.REGISTRATION_DATE,
        DateRole.CANCELLATION_DATE,
        DateRole.FILING_DATE,
        DateRole.UNKNOWN,
    }


def test_identifier_kind_members() -> None:
    assert set(IdentifierKind) == {
        IdentifierKind.GSTIN,
        IdentifierKind.PAN,
        IdentifierKind.UDYAM,
        IdentifierKind.CIN,
        IdentifierKind.UDIN,
        IdentifierKind.GENERIC,
    }


def test_identifier_outcome_members() -> None:
    assert set(IdentifierComparisonOutcome) == {
        IdentifierComparisonOutcome.MATCH_EXACT,
        IdentifierComparisonOutcome.MATCH_NORMALIZED,
        IdentifierComparisonOutcome.MISMATCH,
        IdentifierComparisonOutcome.INSUFFICIENT_EVIDENCE,
    }


def test_address_outcome_members() -> None:
    assert set(AddressComparisonOutcome) == {
        AddressComparisonOutcome.EXACT,
        AddressComparisonOutcome.NORMALIZED_MATCH,
        AddressComparisonOutcome.MISMATCH,
        AddressComparisonOutcome.INSUFFICIENT_EVIDENCE,
    }


def test_date_outcome_members() -> None:
    assert set(DateComparisonOutcome) == {
        DateComparisonOutcome.MATCH,
        DateComparisonOutcome.MISMATCH,
        DateComparisonOutcome.VALIDITY_CONFLICT,
        DateComparisonOutcome.INSUFFICIENT_EVIDENCE,
    }


def test_product_outcome_members() -> None:
    assert set(ProductComparisonOutcome) == {
        ProductComparisonOutcome.EXACT,
        ProductComparisonOutcome.NORMALIZED_MATCH,
        ProductComparisonOutcome.MISMATCH,
        ProductComparisonOutcome.INSUFFICIENT_EVIDENCE,
    }


def test_manufacturer_outcome_members() -> None:
    assert set(ManufacturerComparisonOutcome) == {
        ManufacturerComparisonOutcome.MATCH_EXACT,
        ManufacturerComparisonOutcome.MATCH_NORMALIZED,
        ManufacturerComparisonOutcome.MISMATCH,
        ManufacturerComparisonOutcome.INSUFFICIENT_EVIDENCE,
    }


def test_field_observation_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        FieldObservation(
            bidder_id="b",
            document_id="d",
            document_type="t",
            field_name="f",
            evidence_id="e",
            original_value="v",
            normalized_value="v",
            dimension=ConsistencyDimension.IDENTIFIER,
            status=FieldStatus.AVAILABLE,
            unknown_field="boom",  # type: ignore[call-arg]
        )


def test_pairwise_comparison_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        PairwiseComparison(
            bidder_id="b",
            dimension=ConsistencyDimension.IDENTIFIER,
            left_document_id="d1",
            right_document_id="d2",
            left_document_type="t",
            right_document_type="t",
            left_field_name="g",
            right_field_name="g",
            left_evidence_id="e1",
            right_evidence_id="e2",
            left_original="v",
            right_original="v",
            left_normalized="v",
            right_normalized="v",
            outcome="MISMATCH",
            normalization_version="v1",
            comparability_reason="r",
            explanation="x",
            unknown="boom",  # type: ignore[call-arg]
        )


def test_field_observation_frozen() -> None:
    obs = FieldObservation(
        bidder_id="b",
        document_id="d",
        document_type="t",
        field_name="f",
        evidence_id="e",
        original_value="v",
        normalized_value="v",
        dimension=ConsistencyDimension.IDENTIFIER,
        status=FieldStatus.AVAILABLE,
    )
    with pytest.raises(ValidationError):
        obs.original_value = "new"  # type: ignore[misc]


def test_pairwise_comparison_is_mismatch() -> None:
    base = dict(
        bidder_id="b",
        dimension=ConsistencyDimension.IDENTIFIER,
        left_document_id="d1",
        right_document_id="d2",
        left_document_type="t",
        right_document_type="t",
        left_field_name="g",
        right_field_name="g",
        left_evidence_id="e1",
        right_evidence_id="e2",
        left_original="v",
        right_original="v",
        left_normalized="v",
        right_normalized="v",
        normalization_version="v1",
        comparability_reason="r",
        explanation="x",
    )
    mismatch = PairwiseComparison(**base, outcome="MISMATCH")
    assert mismatch.is_mismatch() is True
    insufficient = PairwiseComparison(
        **base, outcome="INSUFFICIENT_EVIDENCE"
    )
    assert insufficient.is_mismatch() is False


def test_outcome_for_dimension_round_trip() -> None:
    assert outcome_for_dimension(
        ConsistencyDimension.IDENTIFIER, "MATCH_EXACT"
    ) is IdentifierComparisonOutcome.MATCH_EXACT
    assert outcome_for_dimension(
        ConsistencyDimension.ADDRESS, "NORMALIZED_MATCH"
    ) is AddressComparisonOutcome.NORMALIZED_MATCH
    assert outcome_for_dimension(
        ConsistencyDimension.DATE, "VALIDITY_CONFLICT"
    ) is DateComparisonOutcome.VALIDITY_CONFLICT


def test_outcome_for_dimension_rejects_bad_value() -> None:
    with pytest.raises(ValueError):
        outcome_for_dimension(ConsistencyDimension.IDENTIFIER, "NOPE")


def test_dimension_summary_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        DimensionSummary(
            dimension=ConsistencyDimension.IDENTIFIER,
            total_comparisons=1,
            matches=1,
            mismatches=0,
            insufficient_evidence=0,
            unknown="boom",  # type: ignore[call-arg]
        )
