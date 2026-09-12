"""Tests for the structured-fact model."""

import pytest
from pydantic import ValidationError

from ai_verification.explanations.facts import FactKind, StructuredFact


def test_fact_basic_construction():
    fact = StructuredFact(
        fact_id="fact_1", kind=FactKind.ACTUAL_VALUE, value=18.4, unit="crore"
    )
    assert fact.fact_id == "fact_1"
    assert fact.value == 18.4
    assert fact.display_value() == "18.4 crore"


def test_fact_rejects_extra_fields():
    with pytest.raises(ValidationError):
        StructuredFact(fact_id="f", kind=FactKind.ACTUAL_VALUE, invented="x")


def test_fact_is_immutable():
    fact = StructuredFact(fact_id="f", kind=FactKind.VERIFICATION_STATUS, value="NOT_FOUND")
    with pytest.raises(ValidationError):
        fact.kind = FactKind.ACTUAL_VALUE  # type: ignore[misc]


def test_fact_confidence_bounded():
    with pytest.raises(ValidationError):
        StructuredFact(fact_id="f", kind=FactKind.ACTUAL_VALUE, confidence=1.5)


def test_fact_similarity_score_bounded():
    with pytest.raises(ValidationError):
        StructuredFact(fact_id="f", kind=FactKind.SIMILARITY_SCORE, similarity_score=2.0)


def test_fact_all_fields_optional_except_id_and_kind():
    fact = StructuredFact(fact_id="f", kind=FactKind.UNIT)
    assert fact.value is None
    assert fact.source_ref is None


def test_display_value_falls_back_to_actual_and_state():
    assert (
        StructuredFact(fact_id="f", kind=FactKind.ACTUAL_VALUE, actual_value=7).display_value()
        == "7"
    )
    assert (
        StructuredFact(
            fact_id="f", kind=FactKind.QUALITY_STATE, quality_state="DEGRADED"
        ).display_value()
        == "DEGRADED"
    )


def test_fact_uses_only_populated_fields():
    fact = StructuredFact(fact_id="f", kind=FactKind.THRESHOLD, financial_year="2023-24")
    assert fact.value is None
    assert fact.actual_value is None
    assert fact.financial_year == "2023-24"


def test_all_fact_kinds_exist():
    expected = {
        "ACTUAL_VALUE",
        "EXPECTED_VALUE",
        "THRESHOLD",
        "OPERATOR",
        "UNIT",
        "FINANCIAL_YEAR",
        "VERIFICATION_STATUS",
        "QUALITY_STATE",
        "COMPARISON_OUTCOME",
        "SIMILARITY_SCORE",
        "SIMILARITY_THRESHOLD",
        "IDENTIFIER",
        "NORMALIZED_VALUE",
        "DOCUMENT_NAME",
        "DATE",
    }
    assert {k.value for k in FactKind} == expected