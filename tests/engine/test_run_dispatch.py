"""Empty / single / multi-capability dispatch and applicability delegation."""

from __future__ import annotations

from compliance_engine.engine import ComplianceEngine
from compliance_engine.models import (
    Applicability,
    Capability,
    ComplianceStatus,
)

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


def test_run_with_empty_requirements_produces_empty_compliance_results() -> None:
    engine = ComplianceEngine(rules=default_rules(), providers=default_providers())
    result = engine.run(evidence=[gst_evidence()], requirements=[])
    assert result.compliance_results == []
    assert result.identity_findings == []


def test_run_with_empty_inputs_produces_empty_outputs() -> None:
    engine = ComplianceEngine(rules=default_rules(), providers=default_providers())
    result = engine.run(evidence=[], requirements=[])
    assert result.compliance_results == []
    assert result.identity_findings == []
    assert result.bidder_id is None


def test_run_with_one_applicable_requirement_executes_its_rule() -> None:
    engine = ComplianceEngine(rules=default_rules(), providers=default_providers())
    result = engine.run(
        evidence=[gst_evidence()],
        requirements=[gst_requirement()],
    )
    assert len(result.compliance_results) == 1
    assert result.compliance_results[0].requirement_id == "req-gst-001"
    assert result.compliance_results[0].status == ComplianceStatus.PASS
    assert result.bidder_id == "bidder_1"
    assert result.evaluated_at is not None


def test_run_with_multiple_requirements_uses_matching_provider_per_capability() -> None:
    engine = ComplianceEngine(rules=default_rules(), providers=default_providers())
    result = engine.run(
        evidence=[gst_evidence(), pan_evidence(), udyam_evidence()],
        requirements=[
            gst_requirement(),
            pan_requirement(),
            udyam_requirement(),
        ],
    )
    statuses = {r.requirement_id: r.status for r in result.compliance_results}
    assert statuses == {
        "req-gst-001": ComplianceStatus.PASS,
        "req-pan-001": ComplianceStatus.PASS,
        "req-udyam-001": ComplianceStatus.PASS,
    }


def test_not_applicable_requirement_produces_not_applicable_result() -> None:
    engine = ComplianceEngine(rules=default_rules(), providers=default_providers())
    result = engine.run(
        evidence=[gst_evidence()],
        requirements=[gst_requirement(applicability=Applicability.NOT_APPLICABLE)],
    )
    assert len(result.compliance_results) == 1
    assert result.compliance_results[0].status == ComplianceStatus.NOT_APPLICABLE
    assert "not applicable" in result.compliance_results[0].reason.lower()


def test_unknown_applicability_produces_unverifiable_result() -> None:
    engine = ComplianceEngine(rules=default_rules(), providers=default_providers())
    result = engine.run(
        evidence=[gst_evidence()],
        requirements=[gst_requirement(applicability=Applicability.UNKNOWN)],
    )
    assert len(result.compliance_results) == 1
    assert result.compliance_results[0].status == ComplianceStatus.UNVERIFIABLE
    assert (
        "applicability is unknown" in result.compliance_results[0].reason.lower()
    )


def test_unknown_applicability_does_not_require_provider() -> None:
    """UNKNOWN applicability must short-circuit before any rule call."""
    engine = ComplianceEngine(rules=default_rules(), providers={})
    result = engine.run(
        evidence=[gst_evidence()],
        requirements=[gst_requirement(applicability=Applicability.UNKNOWN)],
    )
    assert result.compliance_results[0].status == ComplianceStatus.UNVERIFIABLE
    assert (
        "applicability is unknown" in result.compliance_results[0].reason.lower()
    )


def test_missing_rule_produces_not_checked_result() -> None:
    engine = ComplianceEngine(rules=default_rules(), providers=default_providers())
    result = engine.run(
        evidence=[gst_evidence()],
        requirements=[
            make_requirement(
                requirement_id="req-future",
                capability=Capability.GST,
                rule_id="FUTURE_RULE_999",
            )
        ],
    )
    assert len(result.compliance_results) == 1
    assert result.compliance_results[0].status == ComplianceStatus.NOT_CHECKED
    assert "FUTURE_RULE_999" in result.compliance_results[0].reason
