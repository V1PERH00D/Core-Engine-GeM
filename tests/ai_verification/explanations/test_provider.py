"""Tests for the explanation-model provider abstraction."""

import pytest
from pydantic import ValidationError

from ai_verification.explanations.content import (
    ExplanationContent,
    ObservedFact,
    StatementType,
)
from ai_verification.explanations.facts import FactKind, StructuredFact
from ai_verification.explanations.provider import (
    ExplanationModelResponse,
    ExplanationModelTimeoutError,
    ExplanationModelUnavailableError,
    ExplanationPrompt,
    HttpExplanationModel,
    MalformedModelOutputError,
    StaticExplanationModel,
)


def _prompt(facts=(), flag_state=True):
    return ExplanationPrompt(
        flag_id="TURNOVER_BELOW_THRESHOLD",
        flag_state=flag_state,
        flag_title="Turnover below threshold",
        facts=tuple(facts),
        evidence_refs=("e1",),
    )


def _threshold_fact():
    return StructuredFact(fact_id="f1", kind=FactKind.THRESHOLD, value=25.0, unit="crore")


def test_static_provider_returns_content():
    resp = StaticExplanationModel().generate(_prompt(facts=[_threshold_fact()]))
    assert isinstance(resp.content, ExplanationContent)
    assert resp.content.summary == "Turnover below threshold is true."


def test_static_provider_populates_observed_facts():
    resp = StaticExplanationModel().generate(_prompt(facts=[_threshold_fact()]))
    assert resp.content.observed_facts == [
        ObservedFact(fact_ref="f1", statement_type=StatementType.THRESHOLD, source_ref=None)
    ]


def test_static_provider_is_deterministic():
    a = StaticExplanationModel().generate(_prompt(facts=[_threshold_fact()]))
    b = StaticExplanationModel().generate(_prompt(facts=[_threshold_fact()]))
    assert a.content.summary == b.content.summary
    assert a.content.detailed_explanation == b.content.detailed_explanation


def test_static_provider_records_model_and_provider_name():
    resp = StaticExplanationModel(model_name="k", provider_name="p").generate(_prompt())
    assert resp.model_name == "k"
    assert resp.provider_name == "p"


def test_static_provider_never_calls_network():
    resp = StaticExplanationModel().generate(_prompt(facts=[_threshold_fact()]))
    assert "e1" in resp.content.evidence_refs


def test_prompt_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ExplanationPrompt(flag_id="X", flag_state=True, invented="y")


def test_http_model_forwards_payload_and_parses():
    captured = {}

    def send(payload, timeout):
        captured["payload"] = payload
        captured["timeout"] = timeout
        return {"ok": True}

    def parse(raw):
        assert raw == {"ok": True}
        return ExplanationContent(summary="s", detailed_explanation="d")

    model = HttpExplanationModel(
        model_name="m", provider_name="p", send=send, parse=parse
    )
    resp = model.generate(_prompt(), timeout_seconds=5.0)
    assert resp.model_name == "m"
    assert resp.provider_name == "p"
    assert captured["timeout"] == 5.0
    assert captured["payload"]["flag_id"] == "TURNOVER_BELOW_THRESHOLD"


def test_http_model_unavailable_raises():
    def send(payload, timeout):
        raise ConnectionError("boom")

    model = HttpExplanationModel(
        model_name="m", provider_name="p", send=send, parse=lambda r: None
    )
    with pytest.raises(ExplanationModelUnavailableError):
        model.generate(_prompt())


def test_http_model_timeout_raises():
    def send(payload, timeout):
        raise TimeoutError("slow")

    model = HttpExplanationModel(
        model_name="m", provider_name="p", send=send, parse=lambda r: None
    )
    with pytest.raises(ExplanationModelTimeoutError):
        model.generate(_prompt())


def test_http_model_malformed_raises():
    def send(payload, timeout):
        return {"bad": "shape"}

    def parse(raw):
        raise MalformedModelOutputError("unparseable")

    model = HttpExplanationModel(
        model_name="m", provider_name="p", send=send, parse=parse
    )
    with pytest.raises(MalformedModelOutputError):
        model.generate(_prompt())


def test_http_model_wrong_parse_type_raises():
    def send(payload, timeout):
        return {}

    def parse(raw):
        return "not a content"  # wrong type

    model = HttpExplanationModel(
        model_name="m", provider_name="p", send=send, parse=parse
    )
    with pytest.raises(MalformedModelOutputError):
        model.generate(_prompt())