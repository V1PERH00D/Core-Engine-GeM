"""Tests for the explicit grounding contract."""

import pytest
from pydantic import ValidationError

from ai_verification.explanations.grounding import (
    ExplanationGrounding,
    GroundingRefKind,
)


def test_grounding_normalizes_and_dedups():
    g = ExplanationGrounding(
        evidence_refs=("e2", "e1", "e2"),
        verification_refs=("v1",),
    )
    assert g.evidence_refs == ("e1", "e2")


def test_grounding_rejects_extra():
    with pytest.raises(ValidationError):
        ExplanationGrounding(evidence_refs=(), nope=1)


def test_grounding_immutable():
    g = ExplanationGrounding(evidence_refs=("e1",))
    with pytest.raises(ValidationError):
        g.evidence_refs = ()  # type: ignore[misc]


def test_known_ids_membership():
    g = ExplanationGrounding(evidence_refs=("e1", "e2"))
    assert "e1" in g.known_ids(GroundingRefKind.EVIDENCE)
    assert "v1" not in g.known_ids(GroundingRefKind.VERIFICATION)


def test_grounding_hash_deterministic():
    a = ExplanationGrounding(evidence_refs=("e2", "e1"))
    b = ExplanationGrounding(evidence_refs=("e1", "e2"))
    assert a.content_hash() == b.content_hash()


def test_grounding_hash_differs_on_content():
    a = ExplanationGrounding(evidence_refs=("e1",))
    b = ExplanationGrounding(evidence_refs=("e2",))
    assert a.content_hash() != b.content_hash()


def test_grounding_hash_differs_per_kind():
    a = ExplanationGrounding(evidence_refs=("x",))
    b = ExplanationGrounding(verification_refs=("x",))
    assert a.content_hash() != b.content_hash()


def test_is_empty():
    assert ExplanationGrounding().is_empty() is True
    assert ExplanationGrounding(evidence_refs=("e1",)).is_empty() is False


def test_all_refs_shape():
    g = ExplanationGrounding(evidence_refs=("e1",), finding_refs=("f1",))
    refs = g.all_refs()
    assert refs["EVIDENCE"] == ("e1",)
    assert refs["FINDING"] == ("f1",)
    assert refs["TRACE"] == ()


def test_duplicate_refs_collapse():
    g = ExplanationGrounding(finding_refs=("f1", "f1", "f2"))
    assert g.finding_refs == ("f1", "f2")
    assert len(g.content_hash()) == 64