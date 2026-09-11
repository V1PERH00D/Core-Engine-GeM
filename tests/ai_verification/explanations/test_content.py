"""Tests for the structured content model."""

import pytest
from pydantic import ValidationError

from ai_verification.explanations.content import (
    ExplanationContent,
    ObservedFact,
    StatementType,
)


def test_content_valid():
    c = ExplanationContent(summary="s", detailed_explanation="d")
    assert c.summary == "s"
    assert c.observed_facts == []


def test_content_rejects_extra():
    with pytest.raises(ValidationError):
        ExplanationContent(summary="s", detailed_explanation="d", hallucination="x")


def test_content_frozen():
    c = ExplanationContent(summary="s", detailed_explanation="d")
    with pytest.raises(ValidationError):
        c.summary = "other"  # type: ignore[misc]


def test_content_empty_summary_rejected():
    with pytest.raises(ValidationError):
        ExplanationContent(summary="", detailed_explanation="d")


def test_observed_fact_valid():
    o = ObservedFact(fact_ref="f1", statement_type=StatementType.ACTUAL_VALUE)
    assert o.fact_ref == "f1"
    assert o.source_ref is None


def test_observed_fact_rejects_extra():
    with pytest.raises(ValidationError):
        ObservedFact(fact_ref="f1", statement_type=StatementType.ACTUAL_VALUE, extra=1)


def test_observed_fact_empty_ref_rejected():
    with pytest.raises(ValidationError):
        ObservedFact(fact_ref="", statement_type=StatementType.ACTUAL_VALUE)


def test_content_dedups_string_lists():
    c = ExplanationContent(
        summary="s",
        detailed_explanation="d",
        uncertainties=["u", "u", "v"],
        evidence_refs=["e1", "e1"],
    )
    assert c.uncertainties == ["u", "v"]
    assert c.evidence_refs == ["e1"]


def test_content_statement_types_complete():
    assert StatementType.THRESHOLD.value == "THRESHOLD"
    assert StatementType.SIMILARITY_THRESHOLD.value == "SIMILARITY_THRESHOLD"