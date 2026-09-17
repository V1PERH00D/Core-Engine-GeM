"""Tests for explanation request / result domain models."""

import pytest
from pydantic import ValidationError

from compliance_engine.flags import UnknownFlagError

from ai_verification.explanations.content import ExplanationContent
from ai_verification.explanations.facts import FactKind, StructuredFact
from ai_verification.explanations.generator import ExplanationRequest
from ai_verification.explanations.grounding import ExplanationGrounding
from ai_verification.explanations.models import (
    EXPLANATION_SCHEMA_VERSION,
    ExplanationResult,
    ValidationStatus,
)


def test_request_flag_state_alias():
    req = ExplanationRequest(bidder_id="b1", flag_id="GSTIN_MISSING", flag_active=True)
    assert req.flag_state is True
    assert req.flag_active is True


def test_request_is_boolean_state():
    req = ExplanationRequest(bidder_id="b1", flag_id="GSTIN_MISSING", flag_active=False)
    assert req.flag_state is False


def test_request_rich_fields_default():
    req = ExplanationRequest(bidder_id="b1", flag_id="GSTIN_MISSING", flag_active=True)
    assert req.finding_refs == []
    assert req.document_refs == []
    assert req.facts == []


def test_request_unknown_flag_rejected():
    with pytest.raises(UnknownFlagError):
        ExplanationRequest(bidder_id="b1", flag_id="NOPE", flag_active=True)


def test_request_build_grounding_collects_refs():
    fact = StructuredFact(
        fact_id="f1", kind=FactKind.ACTUAL_VALUE, value=1, source_ref="e1"
    )
    req = ExplanationRequest(
        bidder_id="b1",
        flag_id="TURNOVER_BELOW_THRESHOLD",
        flag_active=True,
        facts=[fact],
        finding_refs=["finding_1"],
    )
    grounding = req.build_grounding()
    assert "e1" in grounding.evidence_refs
    assert "finding_1" in grounding.finding_refs
    assert "f1" not in grounding.evidence_refs


def test_result_allocate_id_is_idempotent():
    a = ExplanationResult.allocate_explanation_id("b1", "GSTIN_MISSING", True)
    b = ExplanationResult.allocate_explanation_id("b1", "GSTIN_MISSING", True)
    assert a == b
    assert a != ExplanationResult.allocate_explanation_id("b1", "GSTIN_MISSING", False)


def test_result_concise_and_detailed_aliases():
    result = ExplanationResult(
        explanation_id="x",
        bidder_id="b1",
        flag_id="GSTIN_MISSING",
        flag_state=True,
        content=ExplanationContent(summary="sum", detailed_explanation="det"),
        grounding=ExplanationGrounding(),
        generation={"generator": "g"},
    )
    assert result.concise_text == "sum"
    assert result.detailed_text == "det"


def test_result_unknown_flag_rejected():
    with pytest.raises(UnknownFlagError):
        ExplanationResult(
            explanation_id="x",
            bidder_id="b1",
            flag_id="NOT_REAL",
            flag_state=True,
            content=ExplanationContent(summary="s", detailed_explanation="d"),
            grounding=ExplanationGrounding(),
            generation={"generator": "g"},
        )


def test_schema_version_stable():
    assert EXPLANATION_SCHEMA_VERSION == 1


def test_validation_status_values():
    assert ValidationStatus.VALID.value == "VALID"
    assert ValidationStatus.FALLBACK.value == "FALLBACK"
    assert ValidationStatus.GROUNDING_FAILED.value == "GROUNDING_FAILED"