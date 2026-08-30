"""Tests for the canonical Capability enum and its adoption in code.

These tests prove that:
- The canonical IDs in :class:`Capability` are all unique.
- Every provider's ``CAPABILITY`` uses a canonical :class:`Capability`
  member (not a raw string).
- The cross-document identity verifier emits the canonical
  ``BIDDER_IDENTITY`` ID on its findings.
- Requirement / Verification / ComplianceResult objects can carry
  :class:`Capability` values.
- No old inconsistent capability strings (``"Udyam / MSME"``,
  ``"Bidder Identity"``, ``"FINANCIAL_CAPACITY"``) appear as bare
  strings in the executable engine code paths we migrated.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import pytest

from compliance_engine.anomalies.identity import verify_cross_document_identity
from compliance_engine.engine import ComplianceEngine
from compliance_engine.models import (
    Capability,
    ComplianceResult,
    Evidence,
    Requirement,
    Verification,
    VerificationStatus,
)
from compliance_engine.rules import (
    GSTRegistrationRule,
    PANValidationRule,
    UdyamRegistrationRule,
)
from compliance_engine.verification import (
    MockGSTProvider,
    MockPANProvider,
    MockUdyamProvider,
)


def test_every_canonical_capability_id_is_unique() -> None:
    """Each canonical capability ID must appear exactly once."""
    values = [member.value for member in Capability]
    assert len(values) == len(set(values))
    assert len(values) >= 1


def test_canonical_ids_are_upper_snake_case_strings() -> None:
    """Machine IDs must be stable upper-snake-case strings."""
    for member in Capability:
        assert isinstance(member.value, str)
        assert member.value == member.value.upper()
        assert " " not in member.value
        assert "/" not in member.value


def test_canonical_ids_documented_for_current_capabilities() -> None:
    """The current engine uses exactly the documented canonical IDs."""
    expected = {
        "GST",
        "PAN_INCOME_TAX",
        "UDYAM",
        "FINANCIAL",
        "BIDDER_IDENTITY",
    }
    actual = {member.value for member in Capability}
    assert expected == actual


def test_mock_gst_provider_uses_canonical_capability() -> None:
    """MockGSTProvider.CAPABILITY must be the canonical GST member."""
    assert MockGSTProvider.CAPABILITY == Capability.GST
    result = MockGSTProvider().verify("bidder_acme_01", MockGSTProvider.GSTIN_VERIFIED)
    # Pydantic stores the str value of a StrEnum in model fields.
    assert result.capability == Capability.GST
    assert result.capability == "GST"


def test_mock_pan_provider_uses_canonical_capability() -> None:
    """MockPANProvider.CAPABILITY must be the canonical PAN_INCOME_TAX member."""
    assert MockPANProvider.CAPABILITY == Capability.PAN_INCOME_TAX
    result = MockPANProvider().verify("bidder_acme_01", MockPANProvider.PAN_VERIFIED)
    assert result.capability == Capability.PAN_INCOME_TAX
    assert result.capability == "PAN_INCOME_TAX"


def test_mock_udyam_provider_uses_canonical_capability() -> None:
    """MockUdyamProvider.CAPABILITY must be the canonical UDYAM member."""
    assert MockUdyamProvider.CAPABILITY == Capability.UDYAM
    result = MockUdyamProvider().verify("bidder_acme_01", MockUdyamProvider.UDYAM_VERIFIED)
    assert result.capability == Capability.UDYAM
    assert result.capability == "UDYAM"


def test_identity_finding_uses_canonical_bidder_identity() -> None:
    """The cross-document identity verifier must emit BIDDER_IDENTITY."""
    evidence = [
        Evidence(
            evidence_id="ev-1",
            bidder_id="bidder-001",
            document_id="doc-gst",
            document_type="GST",
            field_name="legal_name",
            value="ACME ENTERPRISES PRIVATE LIMITED",
        ),
        Evidence(
            evidence_id="ev-2",
            bidder_id="bidder-001",
            document_id="doc-pan",
            document_type="PAN",
            field_name="name_on_pan",
            value="OTHER BIDDER PRIVATE LIMITED",
        ),
    ]
    findings = verify_cross_document_identity(evidence)
    assert len(findings) == 1
    assert findings[0].capability == Capability.BIDDER_IDENTITY
    assert findings[0].capability == "BIDDER_IDENTITY"


def test_requirement_accepts_canonical_capability_enum() -> None:
    """Requirement must accept a Capability enum value and store its str form."""
    from compliance_engine.models import Applicability

    requirement = Requirement(
        requirement_id="req-001",
        capability=Capability.UDYAM,
        description="Udyam requirement",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        rule_id="UDYAM_REGISTRATION_001",
    )
    assert requirement.capability == Capability.UDYAM
    assert requirement.capability == "UDYAM"


def test_verification_accepts_canonical_capability_enum() -> None:
    """Verification must accept a Capability enum value."""
    record = Verification(
        verification_id="ver-1",
        bidder_id="bidder-001",
        capability=Capability.GST,
        source="GSTN_MOCK",
        status=VerificationStatus.VERIFIED,
        data={},
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert record.capability == Capability.GST
    assert record.capability == "GST"


def test_compliance_result_accepts_canonical_capability_enum() -> None:
    """ComplianceResult must accept a Capability enum value."""
    from compliance_engine.models import ComplianceStatus

    result = ComplianceResult(
        requirement_id="req-001",
        capability=Capability.FINANCIAL,
        status=ComplianceStatus.PASS,
        reason="ok",
        rule_id="FIN_RULE_001",
    )
    assert result.capability == Capability.FINANCIAL
    assert result.capability == "FINANCIAL"


def test_engine_runs_with_canonical_capability_keys_for_providers() -> None:
    """The engine must accept a providers dict keyed by Capability members."""
    from compliance_engine.models import Applicability

    engine = ComplianceEngine(
        rules={
            "GST_REGISTRATION_001": GSTRegistrationRule(),
            "PAN_VALIDATION_001": PANValidationRule(),
            "UDYAM_REGISTRATION_001": UdyamRegistrationRule(),
        },
        providers={
            Capability.GST: MockGSTProvider(),
            Capability.PAN_INCOME_TAX: MockPANProvider(),
            Capability.UDYAM: MockUdyamProvider(),
        },
    )
    gst_ev = Evidence(
        evidence_id="doc-gst-1:gstin",
        bidder_id="bidder-1",
        document_id="doc-gst-1",
        document_type="GST",
        field_name="gstin",
        value=MockGSTProvider.GSTIN_VERIFIED,
    )
    pan_ev = Evidence(
        evidence_id="doc-pan-1:pan_number",
        bidder_id="bidder-1",
        document_id="doc-pan-1",
        document_type="PAN",
        field_name="pan_number",
        value=MockPANProvider.PAN_VERIFIED,
    )
    udyam_ev = Evidence(
        evidence_id="doc-udyam-1:udyam_registration_number",
        bidder_id="bidder-1",
        document_id="doc-udyam-1",
        document_type="UDYAM",
        field_name="udyam_registration_number",
        value=MockUdyamProvider.UDYAM_VERIFIED,
    )
    requirements = [
        Requirement(
            requirement_id="req-gst-001",
            capability=Capability.GST,
            description="GST",
            mandatory=True,
            applicability=Applicability.APPLICABLE,
            rule_id="GST_REGISTRATION_001",
        ),
        Requirement(
            requirement_id="req-pan-001",
            capability=Capability.PAN_INCOME_TAX,
            description="PAN",
            mandatory=True,
            applicability=Applicability.APPLICABLE,
            rule_id="PAN_VALIDATION_001",
        ),
        Requirement(
            requirement_id="req-udyam-001",
            capability=Capability.UDYAM,
            description="Udyam",
            mandatory=True,
            applicability=Applicability.APPLICABLE,
            rule_id="UDYAM_REGISTRATION_001",
        ),
    ]
    result = engine.run(
        evidence=[gst_ev, pan_ev, udyam_ev],
        requirements=requirements,
    )
    statuses = {r.requirement_id: r.status for r in result.compliance_results}
    assert statuses["req-gst-001"] == "PASS"
    assert statuses["req-pan-001"] == "PASS"
    assert statuses["req-udyam-001"] == "PASS"


# Files in which old/inconsistent capability identifiers would constitute
# a regression if they reappeared as bare strings. Excludes the
# `capability.py` module which is allowed to mention human-readable
# section names inside its mapping docstring.
_MIGRATED_SOURCES: tuple[Path, ...] = (
    Path("src/compliance_engine/verification/base.py"),
    Path("src/compliance_engine/verification/pan.py"),
    Path("src/compliance_engine/verification/udyam.py"),
    Path("src/compliance_engine/anomalies/identity.py"),
    Path("src/compliance_engine/engine.py"),
)


@pytest.mark.parametrize("path", _MIGRATED_SOURCES, ids=lambda p: p.as_posix())
def test_migrated_source_has_no_old_capability_bare_strings(path: Path) -> None:
    """The migrated engine sources must not contain the old bare capability strings.

    Old strings the audit was about:
    - ``"Udyam / MSME"``        (replaced by ``Capability.UDYAM``)
    - ``"Bidder Identity"``     (replaced by ``Capability.BIDDER_IDENTITY``)
    - ``"FINANCIAL_CAPACITY"``  (replaced by ``Capability.FINANCIAL``)
    """
    repo_root = Path(__file__).resolve().parents[2]
    target = repo_root / path
    text = target.read_text()
    for forbidden in ("Udyam / MSME", "Bidder Identity", "FINANCIAL_CAPACITY"):
        assert forbidden not in text, (
            f"{path} still contains the old bare-string capability {forbidden!r}"
        )


def test_capability_module_documents_human_readable_mapping() -> None:
    """The canonical module's docstring may mention human-readable section names.

    The mapping table is the one place the human-readable names live
    inside the engine. Other migrated code must not contain them as
    bare-string capability identifiers.
    """
    from compliance_engine.models import capability as cap_module

    source = inspect.getsource(cap_module)
    # The mapping docstring is allowed to reference the human-readable names.
    assert "Udyam / MSME" in source
    assert "Bidder Identity" in source


def test_provider_classes_use_capability_enum_type() -> None:
    """Source-level check: provider CAPABILITY is typed as Capability, not str.

    The annotation may be either ``Capability`` or ``Final[Capability]``;
    both prove the field is no longer typed as ``str``.
    """
    repo_root = Path(__file__).resolve().parents[2]
    for relative in (
        "src/compliance_engine/verification/base.py",
        "src/compliance_engine/verification/pan.py",
        "src/compliance_engine/verification/udyam.py",
    ):
        tree = ast.parse((repo_root / relative).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == "CAPABILITY":
                    annotation = ast.unparse(node.annotation)
                    assert annotation in {"Capability", "Final[Capability]"}, (
                        f"{relative}: CAPABILITY annotation is {annotation!r}, "
                        f"expected 'Capability' or 'Final[Capability]'"
                    )


def test_capability_is_a_str_enum() -> None:
    """Capability must be a StrEnum so its members compare equal to their str values."""
    assert issubclass(Capability, StrEnum)
    assert Capability.GST == "GST"
    assert Capability.PAN_INCOME_TAX == "PAN_INCOME_TAX"
    assert Capability.UDYAM == "UDYAM"
    assert Capability.FINANCIAL == "FINANCIAL"
    assert Capability.BIDDER_IDENTITY == "BIDDER_IDENTITY"


def test_capability_module_documents_machine_id_mapping() -> None:
    """The canonical module must document every canonical ID it defines."""
    from compliance_engine.models import capability as cap_module

    source = inspect.getsource(cap_module)
    for canonical in ("GST", "PAN_INCOME_TAX", "UDYAM", "FINANCIAL", "BIDDER_IDENTITY"):
        assert canonical in source, (
            f"Capability module docstring does not mention canonical ID {canonical!r}"
        )





