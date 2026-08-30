"""Missing provider, exception propagation, and immutability guarantees."""

from __future__ import annotations

import copy

import pytest

from compliance_engine.engine import ComplianceEngine
from compliance_engine.models import Capability, EngineResult
from compliance_engine.rules import Rule
from compliance_engine.verification import MockGSTProvider

from ._builders import (
    default_providers,
    default_rules,
    gst_evidence,
    gst_requirement,
    make_requirement,
    pan_evidence,
    pan_requirement,
    udyam_evidence,
    udyam_requirement,
)


def test_missing_provider_yields_unverifiable_for_applicable_requirements() -> None:
    engine = ComplianceEngine(
        rules=default_rules(),
        providers={Capability.GST: MockGSTProvider()},
    )
    result = engine.run(
        evidence=[gst_evidence(), pan_evidence(), udyam_evidence()],
        requirements=[gst_requirement(), pan_requirement(), udyam_requirement()],
    )

    by_id = {r.requirement_id: r for r in result.compliance_results}
    assert by_id["req-gst-001"].status == "PASS"
    assert by_id["req-pan-001"].status == "UNVERIFIABLE"
    assert by_id["req-udyam-001"].status == "UNVERIFIABLE"
    assert str(Capability.PAN_INCOME_TAX) in by_id["req-pan-001"].reason
    assert str(Capability.UDYAM) in by_id["req-udyam-001"].reason


def test_missing_provider_does_not_crash_engine_with_empty_providers() -> None:
    engine = ComplianceEngine(rules=default_rules(), providers={})
    result = engine.run(
        evidence=[gst_evidence()],
        requirements=[gst_requirement()],
    )
    assert result.compliance_results[0].status == "UNVERIFIABLE"


def test_unexpected_rule_exception_propagates() -> None:
    class _ExplodingRule(Rule):
        rule_id = "EXPLODING_RULE_001"
        name = "Exploding rule"

        def evaluate(self, evidence, *args, **kwargs):  # type: ignore[override]
            raise RuntimeError("boom from inside the rule")

    engine = ComplianceEngine(
        rules={"EXPLODING_RULE_001": _ExplodingRule()},
        providers={Capability.GST: MockGSTProvider()},
    )
    requirements = [
        make_requirement(
            requirement_id="req-boom",
            capability=Capability.GST,
            rule_id="EXPLODING_RULE_001",
        )
    ]

    with pytest.raises(RuntimeError, match="boom from inside the rule"):
        engine.run(evidence=[gst_evidence()], requirements=requirements)


def test_evidence_is_not_mutated() -> None:
    evidence = [gst_evidence(), pan_evidence(), udyam_evidence()]
    snapshot = copy.deepcopy(evidence)

    engine = ComplianceEngine(rules=default_rules(), providers=default_providers())
    engine.run(
        evidence=evidence,
        requirements=[gst_requirement(), pan_requirement(), udyam_requirement()],
    )

    assert evidence == snapshot


def test_requirements_are_not_mutated() -> None:
    requirements = [gst_requirement(), pan_requirement(), udyam_requirement()]
    snapshot = copy.deepcopy(requirements)

    engine = ComplianceEngine(rules=default_rules(), providers=default_providers())
    engine.run(
        evidence=[gst_evidence(), pan_evidence(), udyam_evidence()],
        requirements=requirements,
    )

    assert requirements == snapshot


def test_engine_result_carries_no_aggregate_fields() -> None:
    engine = ComplianceEngine(rules=default_rules(), providers=default_providers())
    result = engine.run(
        evidence=[gst_evidence()],
        requirements=[gst_requirement()],
    )
    forbidden = {
        "score",
        "risk_level",
        "recommendation",
        "bid_status",
        "compliance_state",
    }
    actual = set(EngineResult.model_fields.keys())
    assert forbidden.isdisjoint(actual)
    for attr in forbidden:
        assert not hasattr(result, attr)
