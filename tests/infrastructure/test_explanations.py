"""Grounded explanation generation and persistence."""

import pytest

from compliance_engine.flags import FlagSeverity

from ai_verification.explanations import (
    DeterministicFallbackExplanationGenerator,
    ExplanationRequest,
    GroundedExplanation,
    GroundingKind,
    GroundingReference,
)
from ai_verification.models.contracts import VerificationFinding

from infrastructure.persistence.records import ExplanationRecord


def _finding():
    return VerificationFinding(
        finding_id="f1",
        bidder_id="b1",
        flag_id="GSTIN_MISSING",
        severity=FlagSeverity.HIGH,
        confidence=0.9,
        explanation="GSTIN was not found on the registry.",
        evidence_refs=["e1"],
        verification_refs=["v1"],
    )


def test_deterministic_fallback_text_grounded():
    gen = DeterministicFallbackExplanationGenerator()
    request = ExplanationRequest(
        bidder_id="b1",
        flag_id="GSTIN_MISSING",
        flag_active=True,
        finding=_finding(),
        evidence_refs=["e1"],
        verification_refs=["v1"],
    )
    explanation = gen.explain(request)
    assert "GSTIN_MISSING" in explanation.concise_text
    assert "active" in explanation.concise_text


def test_grounding_references_preserved():
    gen = DeterministicFallbackExplanationGenerator()
    request = ExplanationRequest(
        bidder_id="b1",
        flag_id="GSTIN_MISSING",
        flag_active=True,
        finding=_finding(),
        evidence_refs=["e1"],
        verification_refs=["v1"],
    )
    explanation = gen.explain(request)
    kinds = {r.kind for r in explanation.grounding}
    assert GroundingKind.EVIDENCE in kinds
    assert GroundingKind.VERIFICATION in kinds
    assert GroundingKind.VERIFICATION_FINDING in kinds


def test_flag_linkage_and_finding_refs():
    gen = DeterministicFallbackExplanationGenerator()
    explanation = gen.explain(
        ExplanationRequest(
            bidder_id="b1", flag_id="GSTIN_MISSING", flag_active=True,
            finding=_finding(),
        )
    )
    assert explanation.flag_id == "GSTIN_MISSING"
    assert explanation.flag_active is True
    assert explanation.finding_refs == ["f1"]


def test_generation_metadata_marks_fallback():
    gen = DeterministicFallbackExplanationGenerator()
    explanation = gen.explain(
        ExplanationRequest(bidder_id="b1", flag_id="GSTIN_MISSING", flag_active=False)
    )
    assert explanation.generation.deterministic_fallback is True
    assert explanation.generation.generator == "deterministic_fallback"


def test_explanation_id_is_idempotent():
    a = GroundedExplanation.allocate_explanation_id("b1", "GSTIN_MISSING", True)
    b = GroundedExplanation.allocate_explanation_id("b1", "GSTIN_MISSING", True)
    assert a == b
    c = GroundedExplanation.allocate_explanation_id("b1", "GSTIN_MISSING", False)
    assert a != c


def test_explanation_has_no_severity_or_risk():
    gen = DeterministicFallbackExplanationGenerator()
    explanation = gen.explain(
        ExplanationRequest(bidder_id="b1", flag_id="GSTIN_MISSING", flag_active=True)
    )
    dumped = explanation.model_dump(mode="json")
    assert "severity" not in dumped
    assert "risk" not in dumped


def test_explanation_record_persistence_roundtrip():
    gen = DeterministicFallbackExplanationGenerator()
    explanation = gen.explain(
        ExplanationRequest(bidder_id="b1", flag_id="GSTIN_MISSING", flag_active=True)
    )
    record = ExplanationRecord(
        explanation_id=explanation.explanation_id,
        bidder_id=explanation.bidder_id,
        flag_id=explanation.flag_id,
        flag_active=explanation.flag_active,
        finding_refs=explanation.finding_refs,
        concise_text=explanation.concise_text,
        detailed_text=explanation.detailed_text,
        grounding=[g.model_dump(mode="json") for g in explanation.grounding],
        generation=explanation.generation.model_dump(mode="json"),
        created_at=1.0,
    )
    assert record.flag_id == "GSTIN_MISSING"
    assert record.generation["deterministic_fallback"] is True

    # Round-trip grounding references back.
    refs = [GroundingReference.model_validate(g) for g in record.grounding]
    assert len(refs) == len(explanation.grounding)


def test_unknown_flag_rejected():
    with pytest.raises(Exception):
        GroundedExplanation(
            explanation_id="x",
            bidder_id="b1",
            flag_id="NOT_A_REAL_FLAG",
            flag_active=True,
            concise_text="x",
            generation={
                "generator": "g",
                "generator_version": "1",
                "deterministic_fallback": True,
            },
        )