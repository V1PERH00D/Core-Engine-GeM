import re
from pathlib import Path

import pytest

from compliance_engine.flags import (
    FLAG_REGISTRY,
    GSTIN_MISSING,
    FlagSeverity,
    UnknownFlagError,
    get_flag_definition,
)
from compliance_engine.models import (
    Applicability,
    Capability,
    Evidence,
    Requirement,
)
from compliance_engine.rules import GSTRegistrationRule
from compliance_engine.verification import MockGSTProvider

MATRIX_PATH = Path(__file__).resolve().parents[2] / "docs" / "capability-matrix.md"
# Regex to match flag IDs in list items (- `FLAG_ID`) or table cells (| `FLAG_ID` |)
_FLAG_ID_RE = re.compile(r"(?:^ *- |^\| )`([A-Z][A-Z0-9_]+)`(?:\s|$|\|)", re.MULTILINE)


def _matrix_flag_ids() -> set[str]:
    return set(_FLAG_ID_RE.findall(MATRIX_PATH.read_text()))


def test_every_matrix_flag_has_a_registry_entry() -> None:
    matrix_ids = _matrix_flag_ids()
    assert matrix_ids
    assert matrix_ids <= set(FLAG_REGISTRY)


def test_registry_matches_matrix_exactly() -> None:
    """Verify registry contains exactly the flags defined in the capability matrix."""
    matrix_ids = _matrix_flag_ids()
    registry_ids = set(FLAG_REGISTRY)
    assert matrix_ids == registry_ids, (
        f"Matrix and registry mismatch: "
        f"matrix has {matrix_ids - registry_ids}, "
        f"registry has extra {registry_ids - matrix_ids}"
    )


def test_gstin_missing_exists() -> None:
    definition = get_flag_definition(GSTIN_MISSING)
    assert definition.flag_id == "GSTIN_MISSING"
    assert definition.severity is FlagSeverity.HIGH
    assert definition.capability == "GST / GSTN"


def test_severities_are_valid() -> None:
    allowed = set(FlagSeverity)
    for definition in FLAG_REGISTRY.values():
        assert definition.severity in allowed
        assert definition.flag_id
        assert definition.capability
        assert definition.title
        assert definition.description


def test_unknown_flag_lookup_fails_clearly() -> None:
    with pytest.raises(UnknownFlagError, match="UNKNOWN_FLAG"):
        get_flag_definition("UNKNOWN_FLAG")


def test_gst_rule_flag_remains_valid() -> None:
    requirement = Requirement(
        requirement_id="req-gst-registration-001",
        capability=Capability.GST,
        description="GST registration must be valid and active.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="ACTIVE",
        rule_id="GST_REGISTRATION_001",
    )
    result = GSTRegistrationRule().evaluate([], MockGSTProvider(), requirement)
    assert result.flags == [GSTIN_MISSING]
    for flag_id in result.flags:
        assert get_flag_definition(flag_id).flag_id == flag_id


def test_null_gstin_flag_remains_valid() -> None:
    requirement = Requirement(
        requirement_id="req-gst-registration-001",
        capability=Capability.GST,
        description="GST registration must be valid and active.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="ACTIVE",
        rule_id="GST_REGISTRATION_001",
    )
    evidence = Evidence(
        evidence_id="doc-uuid-gst-001:gstin",
        bidder_id="bidder_acme_01",
        document_id="doc-uuid-gst-001",
        document_type="GST",
        field_name="gstin",
        value=None,
    )
    result = GSTRegistrationRule().evaluate([evidence], MockGSTProvider(), requirement)
    assert result.flags == [GSTIN_MISSING]
    get_flag_definition(result.flags[0])
