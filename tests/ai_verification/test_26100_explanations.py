"""Explanation compatibility for the four new capability flags.

The explanation engine is strictly downstream: it explains a boolean flag
state it is given and never changes it.
"""

from ai_verification.explanations.engine import ExplanationEngine
from ai_verification.explanations.grounding import ExplanationGrounding


def _engine():
    return ExplanationEngine()


def test_bis_flag_explains_without_mutating_state():
    engine = _engine()
    res = engine.explain("bidder-1", "BIS_CERTIFICATE_EXPIRED", True)
    assert res.flag_id == "BIS_CERTIFICATE_EXPIRED"
    assert res.flag_state is True
    assert res.content is not None


def test_oem_flag_explains_false_state():
    res = _engine().explain("bidder-1", "OEM_AUTHORIZATION_EXPIRED", False)
    assert res.flag_state is False


def test_digilocker_flag_explains():
    res = _engine().explain("bidder-1", "DIGITAL_DOCUMENT_NOT_FOUND", True)
    assert res.flag_state is True
    assert res.flag_id == "DIGITAL_DOCUMENT_NOT_FOUND"


def test_local_content_flag_explains():
    res = _engine().explain("bidder-1", "LOCAL_CONTENT_BELOW_THRESHOLD", True)
    assert res.flag_id == "LOCAL_CONTENT_BELOW_THRESHOLD"


def test_grounded_explanation_preserves_evidence_and_verification_refs():
    grounding = ExplanationGrounding(
        evidence_refs=["e-1"],
        verification_refs=["v-1"],
        document_refs=["d-1"],
    )
    res = _engine().explain("bidder-1", "BIS_CERTIFICATE_INVALID", True, grounding=grounding)
    assert res.grounding is not None
    assert list(res.grounding.evidence_refs) == ["e-1"]
    assert list(res.grounding.verification_refs) == ["v-1"]


def test_provider_unavailable_flag_explains_as_unverifiable():
    res = _engine().explain("bidder-1", "BIS_VERIFICATION_UNAVAILABLE", True)
    assert res.flag_id == "BIS_VERIFICATION_UNAVAILABLE"


def test_explanation_never_changes_flag():
    """The boolean flag state is an input to the explanation, not an output."""
    for flag in ("BIS_CERTIFICATE_EXPIRED", "OEM_NAME_MISMATCH", "LOCAL_CONTENT_BELOW_THRESHOLD"):
        res = _engine().explain("b", flag, True)
        assert res.flag_id == flag
        assert res.flag_state is True