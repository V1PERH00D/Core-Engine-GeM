"""Tests for the explanation engine (model + fallback + validation)."""

import pytest

from ai_verification.explanations.content import ExplanationContent, ObservedFact, StatementType
from ai_verification.explanations.engine import ExplanationEngine
from ai_verification.explanations.facts import FactKind, StructuredFact
from ai_verification.explanations.grounding import ExplanationGrounding
from ai_verification.explanations.models import ValidationStatus
from ai_verification.explanations.provider import (
    ExplanationModelResponse,
    ExplanationModelUnavailableError,
    MalformedModelOutputError,
)


def _threshold_facts():
    return [
        StructuredFact(fact_id="f_threshold", kind=FactKind.THRESHOLD, value=25.0, unit="crore", source_ref="e1"),
        StructuredFact(fact_id="f_actual", kind=FactKind.ACTUAL_VALUE, value=18.4, unit="crore", source_ref="e2"),
    ]


def _grounding():
    return ExplanationGrounding(evidence_refs=("e1", "e2"))


class _UnavailableModel:
    def generate(self, prompt, *, timeout_seconds=None):
        raise ExplanationModelUnavailableError("down")


class _MalformedModel:
    def generate(self, prompt, *, timeout_seconds=None):
        raise MalformedModelOutputError("bad json")


class _InventedNumberModel:
    def generate(self, prompt, *, timeout_seconds=None):
        return ExplanationModelResponse(
            content=ExplanationContent(
                summary="Flag is true.",
                detailed_explanation="The turnover is 9999.9 crore.",
                observed_facts=[
                    ObservedFact(fact_ref="f_actual", statement_type=StatementType.ACTUAL_VALUE, source_ref="e2"),
                ],
                evidence_refs=["e1", "e2"],
            ),
            model_name="m",
            provider_name="p",
        )


def test_engine_explain_returns_result():
    res = ExplanationEngine().explain(
        "b1", "TURNOVER_BELOW_THRESHOLD", True, grounding=_grounding(), facts=_threshold_facts()
    )
    assert res.bidder_id == "b1"
    assert res.flag_id == "TURNOVER_BELOW_THRESHOLD"
    assert res.flag_state is True
    assert res.fallback_used is True


def test_engine_default_fallback_is_deterministic():
    a = ExplanationEngine().explain("b1", "TURNOVER_BELOW_THRESHOLD", True, grounding=_grounding(), facts=_threshold_facts())
    b = ExplanationEngine().explain("b1", "TURNOVER_BELOW_THRESHOLD", True, grounding=_grounding(), facts=_threshold_facts())
    assert a.content.summary == b.content.summary
    assert a.content.detailed_explanation == b.content.detailed_explanation
    assert a.explanation_id == b.explanation_id


def test_engine_true_vs_false_states_differ():
    t = ExplanationEngine().explain("b1", "TURNOVER_BELOW_THRESHOLD", True, grounding=_grounding(), facts=_threshold_facts())
    f = ExplanationEngine().explain("b1", "TURNOVER_BELOW_THRESHOLD", False, grounding=_grounding(), facts=_threshold_facts())
    assert t.explanation_id != f.explanation_id
    assert "is true" in t.content.summary
    assert "is false" in f.content.summary


def test_engine_fallback_mentions_threshold_and_actual():
    res = ExplanationEngine().explain("b1", "TURNOVER_BELOW_THRESHOLD", True, grounding=_grounding(), facts=_threshold_facts())
    text = res.content.detailed_explanation
    assert "25.0" in text
    assert "18.4" in text


def test_engine_model_unavailable_falls_back():
    res = ExplanationEngine(model=_UnavailableModel()).explain(
        "b1", "TURNOVER_BELOW_THRESHOLD", True, grounding=_grounding(), facts=_threshold_facts()
    )
    assert res.fallback_used is True
    assert res.validation_status is ValidationStatus.VALID


def test_engine_model_malformed_falls_back():
    res = ExplanationEngine(model=_MalformedModel()).explain(
        "b1", "TURNOVER_BELOW_THRESHOLD", True, grounding=_grounding(), facts=_threshold_facts()
    )
    assert res.fallback_used is True


def test_engine_grounding_failure_falls_back():
    res = ExplanationEngine(model=_InventedNumberModel()).explain(
        "b1", "TURNOVER_BELOW_THRESHOLD", True, grounding=_grounding(), facts=_threshold_facts()
    )
    assert res.fallback_used is True
    assert res.validation_status is ValidationStatus.FALLBACK


def test_engine_strict_raises_on_unavailable():
    from ai_verification.explanations.generator import ExplanationRequest

    req = ExplanationRequest(bidder_id="b1", flag_id="TURNOVER_BELOW_THRESHOLD", flag_active=True)
    with pytest.raises(ExplanationModelUnavailableError):
        ExplanationEngine(model=_UnavailableModel()).explain_strict(req, grounding=_grounding())


def test_engine_result_has_no_severity_or_risk():
    res = ExplanationEngine().explain("b1", "TURNOVER_BELOW_THRESHOLD", True, grounding=_grounding(), facts=_threshold_facts())
    dumped = res.model_dump(mode="json")
    assert "severity" not in dumped
    assert "risk" not in dumped


def test_engine_unavailable_verification_stays_uncertain():
    fact = StructuredFact(fact_id="f_status", kind=FactKind.VERIFICATION_STATUS, value="NOT_FOUND", source_ref="v1")
    res = ExplanationEngine().explain(
        "b1", "GST_VERIFICATION_UNAVAILABLE", False,
        grounding=ExplanationGrounding(verification_refs=("v1",)), facts=[fact], uncertainties=["source down"],
    )
    assert "NOT_FOUND" in res.content.detailed_explanation
    assert "source down" in res.content.uncertainties


def test_engine_grounding_object_preserved_in_result():
    g = _grounding()
    res = ExplanationEngine().explain("b1", "TURNOVER_BELOW_THRESHOLD", True, grounding=g, facts=_threshold_facts())
    assert res.grounding.evidence_refs == ("e1", "e2")