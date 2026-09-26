"""Contract test for the tender / requirement-provider -> CE handoff.

The requirement provider is an EXTERNAL module: it extracts requirements
from tender documents and hands the Compliance Engine plain
:class:`Requirement` objects. CE must:

1. accept requirements it did not construct or derive,
2. route them to rules/providers deterministically,
3. never derive requirements from evidence/documents itself,
4. pass tender-specific values (``expected`` / ``parameters``) through
   to the rule unchanged.

These tests build requirements from raw dicts exactly like an external
producer would (no CE test factories, no tender parser), and pin the
missing-rule / not-applicable semantics.
"""

from __future__ import annotations

from compliance_engine.engine import ComplianceEngine
from compliance_engine.models import (
    ComplianceStatus,
    Evidence,
    Requirement,
)
from compliance_engine.rules import FinancialCapacityRule, GSTRegistrationRule
from compliance_engine.verification import MockGSTProvider


def _external_requirements() -> list[Requirement]:
    """Simulate requirements produced by an external tender parser.

    Built from plain dicts, validating against the public
    :class:`Requirement` model only — nothing CE-internal is used.
    """
    payloads = [
        {
            "requirement_id": "tender-42-req-gst",
            "capability": "GST",
            "description": "Bidder shall hold an active GST registration.",
            "mandatory": True,
            "applicability": "APPLICABLE",
            "expected": "ACTIVE",
            "rule_id": "GST_REGISTRATION_001",
        },
        {
            "requirement_id": "tender-42-req-fin-turnover",
            "capability": "Financial Capacity",
            "description": "Average annual turnover >= 25 INR crore over 2023-24.",
            "mandatory": True,
            "applicability": "APPLICABLE",
            "parameters": {
                "minimum_turnover_inr_cr": 25.0,
                "turnover_operator": ">=",
                "turnover_mode": "AVERAGE_ANNUAL",
                "required_financial_years": ["2023-24"],
            },
            "rule_id": "FINANCIAL_CAPACITY_001",
        },
        {
            "requirement_id": "tender-42-req-unknown-rule",
            "capability": "OEM",
            "description": "Bidder shall be an authorized OEM.",
            "mandatory": True,
            "applicability": "APPLICABLE",
            "rule_id": "OEM_AUTHORIZATION_001",  # no rule registered in CE
        },
        {
            "requirement_id": "tender-42-req-na",
            "capability": "UDYAM",
            "description": "Udyam registration (not applicable to this tender class).",
            "mandatory": False,
            "applicability": "NOT_APPLICABLE",
            "rule_id": "UDYAM_REGISTRATION_001",
        },
    ]
    return [Requirement.model_validate(p) for p in payloads]


def _financial_evidence() -> list[Evidence]:
    return [
        Evidence(
            evidence_id=f"doc-bs-001:{f}",
            bidder_id="bidder_1",
            document_id="doc-bs-001",
            document_type="FIN_STMT",
            field_name=f,
            value=v,
        )
        for f, v in [("financial_year", "2023-24"), ("turnover_inr_cr", 30.0)]
    ] + [
        Evidence(
            evidence_id="doc-gst-001:gstin",
            bidder_id="bidder_1",
            document_id="doc-gst-001",
            document_type="GST",
            field_name="gstin",
            value=MockGSTProvider.GSTIN_VERIFIED,
        )
    ]


def _engine() -> ComplianceEngine:
    return ComplianceEngine(
        rules={
            "GST_REGISTRATION_001": GSTRegistrationRule(),
            "FINANCIAL_CAPACITY_001": FinancialCapacityRule(),
        },
        providers={"GST": MockGSTProvider()},
    )


def test_engine_accepts_externally_constructed_requirements() -> None:
    requirements = _external_requirements()
    assert len(requirements) == 4

    result = _engine().run(
        evidence=_financial_evidence(), requirements=requirements
    )

    assert len(result.compliance_results) == 4
    by_id = {r.requirement_id: r for r in result.compliance_results}
    assert by_id["tender-42-req-gst"].status is ComplianceStatus.PASS
    assert by_id["tender-42-req-fin-turnover"].status is ComplianceStatus.PASS


def test_tender_specific_parameters_reach_the_rule_unchanged() -> None:
    # The financial threshold lives ONLY in the requirement; with the
    # same evidence, a stricter tender value must flip the outcome.
    evidence = _financial_evidence()
    passing = Requirement.model_validate(
        {
            "requirement_id": "req-a",
            "capability": "Financial Capacity",
            "description": "turnover >= 25",
            "mandatory": True,
            "applicability": "APPLICABLE",
            "parameters": {"minimum_turnover_inr_cr": 25.0, "turnover_operator": ">="},
            "rule_id": "FINANCIAL_CAPACITY_001",
        }
    )
    failing = passing.model_copy(
        update={
            "requirement_id": "req-b",
            "parameters": {"minimum_turnover_inr_cr": 50.0, "turnover_operator": ">="},
        }
    )

    result = _engine().run(evidence=evidence, requirements=[passing, failing])
    by_id = {r.requirement_id: r for r in result.compliance_results}
    assert by_id["req-a"].status is ComplianceStatus.PASS
    assert by_id["req-b"].status is ComplianceStatus.FAIL


def test_unsupported_requirement_yields_not_checked_deterministically() -> None:
    # Rule unregistered but provider present -> NOT_CHECKED from the
    # executor (a known capability gap, not an error).
    req = Requirement.model_validate(
        {
            "requirement_id": "req-no-rule",
            "capability": "GST",
            "description": "GST check with no rule registered",
            "mandatory": True,
            "applicability": "APPLICABLE",
            "rule_id": "GST_SOMETHING_NOT_IMPLEMENTED",
        }
    )
    result = _engine().run(evidence=[], requirements=[req])
    r = result.compliance_results[0]
    assert r.status is ComplianceStatus.NOT_CHECKED
    assert "GST_SOMETHING_NOT_IMPLEMENTED" in r.reason


def test_requirement_without_provider_is_unverifiable_deterministically() -> None:
    # Capability with no registered provider -> UNVERIFIABLE from the
    # orchestration layer, before any rule lookup; never a crash.
    result = _engine().run(
        evidence=[], requirements=[_external_requirements()[2]]
    )
    assert result.compliance_results[0].status is ComplianceStatus.UNVERIFIABLE


def test_not_applicable_requirement_short_circuits() -> None:
    result = _engine().run(
        evidence=[], requirements=[_external_requirements()[3]]
    )
    r = result.compliance_results[0]
    assert r.status is ComplianceStatus.NOT_APPLICABLE


def test_engine_never_derives_requirements() -> None:
    # Evidence alone must produce zero compliance results: requirements
    # are always caller-supplied.
    result = _engine().run(evidence=_financial_evidence(), requirements=[])
    assert result.compliance_results == []
