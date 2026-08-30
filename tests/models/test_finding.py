"""Tests for formally structured findings models."""

import pytest

from compliance_engine.flags import UnknownFlagError
from compliance_engine.models import IdentityFinding


def test_valid_identity_finding() -> None:
    """Verify IdentityFinding can be created with valid data."""
    finding = IdentityFinding(
        flag_id="CROSS_DOCUMENT_IDENTITY_MISMATCH",
        capability="Bidder Identity",
        message="Names differ after normalization",
        evidence_refs=["ev-1", "ev-2"],
        compared_values=["ACME LIMITED", "ACME TRADING LIMITED"],
        normalized_values=["acme limited", "acme trading limited"],
    )
    assert finding.flag_id == "CROSS_DOCUMENT_IDENTITY_MISMATCH"
    assert finding.capability == "Bidder Identity"
    assert finding.message == "Names differ after normalization"
    assert finding.evidence_refs == ["ev-1", "ev-2"]
    assert finding.compared_values == ["ACME LIMITED", "ACME TRADING LIMITED"]
    assert finding.normalized_values == ["acme limited", "acme trading limited"]


def test_invalid_flag_id_raises_error() -> None:
    """Verify invalid/unregistered flag_id raises UnknownFlagError."""
    with pytest.raises(UnknownFlagError):
        IdentityFinding(
            flag_id="UNKNOWN_FLAG_ID",
            capability="Bidder Identity",
            message="Test message",
            evidence_refs=["ev-1"],
            compared_values=["value1"],
            normalized_values=["normalized1"],
        )


def test_evidence_references_preserved() -> None:
    """Verify evidence references are preserved exactly."""
    evidence_refs = ["doc-gst-001:legal_name", "doc-pan-001:name_on_pan"]
    finding = IdentityFinding(
        flag_id="CROSS_DOCUMENT_IDENTITY_MISMATCH",
        capability="Bidder Identity",
        message="Identity mismatch",
        evidence_refs=evidence_refs,
        compared_values=["value1", "value2"],
        normalized_values=["normalized1", "normalized2"],
    )
    assert finding.evidence_refs == evidence_refs


def test_compared_and_normalized_values_correspondence() -> None:
    """Verify normalized_values correspond to compared_values in order."""
    finding = IdentityFinding(
        flag_id="CROSS_DOCUMENT_IDENTITY_MISMATCH",
        capability="Bidder Identity",
        message="Mismatch",
        evidence_refs=["ev-1", "ev-2", "ev-3"],
        compared_values=["VALUE A", "VALUE B", "VALUE C"],
        normalized_values=["value a", "value b", "value c"],
    )
    assert len(finding.compared_values) == len(finding.normalized_values)
    assert len(finding.compared_values) == 3


def test_normalized_values_length_mismatch_raises_error() -> None:
    """Verify mismatched lengths between compared and normalized values raise error."""
    with pytest.raises(ValueError, match="must match compared_values length"):
        IdentityFinding(
            flag_id="CROSS_DOCUMENT_IDENTITY_MISMATCH",
            capability="Bidder Identity",
            message="Test",
            evidence_refs=["ev-1", "ev-2"],
            compared_values=["value1", "value2"],
            normalized_values=["normalized1"],  # Mismatch: only 1 instead of 2
        )


def test_empty_lists_allowed() -> None:
    """Verify empty lists are allowed where appropriate."""
    finding = IdentityFinding(
        flag_id="CROSS_DOCUMENT_IDENTITY_MISMATCH",
        capability="Bidder Identity",
        message="No mismatch found",
        evidence_refs=[],
        compared_values=[],
        normalized_values=[],
    )
    assert finding.evidence_refs == []
    assert finding.compared_values == []
    assert finding.normalized_values == []


def test_mixed_value_types_in_compared_values() -> None:
    """Verify compared_values can contain mixed types."""
    finding = IdentityFinding(
        flag_id="CROSS_DOCUMENT_IDENTITY_MISMATCH",
        capability="Bidder Identity",
        message="Types matter",
        evidence_refs=["ev-1", "ev-2"],
        compared_values=["string_value", 123, None],
        normalized_values=["string value", "123", "none"],
    )
    assert finding.compared_values[0] == "string_value"
    assert finding.compared_values[1] == 123
    assert finding.compared_values[2] is None
    assert len(finding.compared_values) == len(finding.normalized_values)
