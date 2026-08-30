"""Shared builders for ComplianceEngine tests."""

from __future__ import annotations

from compliance_engine.models import Applicability, Capability, Evidence, Requirement
from compliance_engine.rules import (
    GSTRegistrationRule,
    PANValidationRule,
    Rule,
    UdyamRegistrationRule,
)
from compliance_engine.verification import (
    MockGSTProvider,
    MockPANProvider,
    MockUdyamProvider,
)


def make_requirement(
    *,
    requirement_id: str,
    capability: str,
    rule_id: str,
    applicability: Applicability = Applicability.APPLICABLE,
) -> Requirement:
    return Requirement(
        requirement_id=requirement_id,
        capability=capability,
        description=f"{capability} requirement {requirement_id}",
        mandatory=True,
        applicability=applicability,
        expected="ACTIVE",
        rule_id=rule_id,
    )


def make_evidence(
    *,
    document_id: str,
    document_type: str,
    field_name: str,
    value: str,
    bidder_id: str = "bidder_1",
) -> Evidence:
    return Evidence(
        evidence_id=f"{document_id}:{field_name}",
        bidder_id=bidder_id,
        document_id=document_id,
        document_type=document_type,
        field_name=field_name,
        value=value,
    )


def gst_requirement(
    requirement_id: str = "req-gst-001",
    applicability: Applicability = Applicability.APPLICABLE,
) -> Requirement:
    return make_requirement(
        requirement_id=requirement_id,
        capability=Capability.GST,
        rule_id="GST_REGISTRATION_001",
        applicability=applicability,
    )


def pan_requirement(
    requirement_id: str = "req-pan-001",
    applicability: Applicability = Applicability.APPLICABLE,
) -> Requirement:
    return make_requirement(
        requirement_id=requirement_id,
        capability=Capability.PAN_INCOME_TAX,
        rule_id="PAN_VALIDATION_001",
        applicability=applicability,
    )


def udyam_requirement(
    requirement_id: str = "req-udyam-001",
    applicability: Applicability = Applicability.APPLICABLE,
) -> Requirement:
    return make_requirement(
        requirement_id=requirement_id,
        capability=Capability.UDYAM,
        rule_id="UDYAM_REGISTRATION_001",
        applicability=applicability,
    )


def gst_evidence(value: str | None = None) -> Evidence:
    return make_evidence(
        document_id="doc-gst-001",
        document_type="GST",
        field_name="gstin",
        value=value if value is not None else MockGSTProvider.GSTIN_VERIFIED,
    )


def pan_evidence(value: str | None = None) -> Evidence:
    return make_evidence(
        document_id="doc-pan-001",
        document_type="PAN",
        field_name="pan_number",
        value=value if value is not None else MockPANProvider.PAN_VERIFIED,
    )


def udyam_evidence(value: str | None = None) -> Evidence:
    return make_evidence(
        document_id="doc-udyam-001",
        document_type="UDYAM",
        field_name="udyam_registration_number",
        value=value if value is not None else MockUdyamProvider.UDYAM_VERIFIED,
    )


def default_rules() -> dict[str, Rule]:
    return {
        "GST_REGISTRATION_001": GSTRegistrationRule(),
        "PAN_VALIDATION_001": PANValidationRule(),
        "UDYAM_REGISTRATION_001": UdyamRegistrationRule(),
    }


def default_providers() -> dict:
    return {
        Capability.GST: MockGSTProvider(),
        Capability.PAN_INCOME_TAX: MockPANProvider(),
        Capability.UDYAM: MockUdyamProvider(),
    }
