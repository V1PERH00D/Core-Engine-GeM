"""Tests for the identity findings emission."""

from __future__ import annotations

from compliance_engine.flags import FlagSeverity, get_flag_definition
from compliance_engine.models import Capability, IdentityFinding

from ai_verification.identity import (
    CROSS_SOURCE_IDENTITY_MISMATCH,
    IdentityReconciliationEngine,
)
from ai_verification.identity.findings import (
    to_identity_findings,
    to_verification_findings,
)


def test_flag_is_registered_with_correct_severity_and_capability() -> None:
    definition = get_flag_definition(CROSS_SOURCE_IDENTITY_MISMATCH)
    assert definition.flag_id == "CROSS_SOURCE_IDENTITY_MISMATCH"
    assert definition.severity == FlagSeverity.HIGH
    assert definition.capability == "Bidder Identity"


def test_findings_emit_identity_finding_with_correct_flag() -> None:
    from tests.ai_verification.identity._builders import (
        gst_verified,
        pan_verified,
    )

    engine = IdentityReconciliationEngine()
    records = [
        gst_verified(legal_name="ACME ENTERPRISES PRIVATE LIMITED"),
        pan_verified(name_on_pan="ACME TRADING PRIVATE LIMITED"),
    ]
    result = engine.reconcile(records, bidder_id="bidder-1")
    identity_findings = to_identity_findings(result.aggregation)
    assert len(identity_findings) == 1
    finding = identity_findings[0]
    assert isinstance(finding, IdentityFinding)
    assert finding.flag_id == CROSS_SOURCE_IDENTITY_MISMATCH
    assert finding.capability == Capability.BIDDER_IDENTITY


def test_findings_emit_verification_finding_with_correct_fields() -> None:
    from tests.ai_verification.identity._builders import (
        gst_verified,
        pan_verified,
    )

    engine = IdentityReconciliationEngine()
    records = [
        gst_verified(
            verification_id="V-GST",
            legal_name="ACME ENTERPRISES PRIVATE LIMITED",
            evidence_id="ev-gst",
            document_id="doc-gst",
        ),
        pan_verified(
            verification_id="V-PAN",
            name_on_pan="ACME TRADING PRIVATE LIMITED",
            evidence_id="ev-pan",
            document_id="doc-pan",
        ),
    ]
    result = engine.reconcile(records, bidder_id="bidder-1")
    vf = to_verification_findings(result.aggregation, bidder_id="bidder-1")
    assert len(vf) == 1
    finding = vf[0]
    assert finding.flag_id == CROSS_SOURCE_IDENTITY_MISMATCH
    assert finding.severity == FlagSeverity.HIGH
    assert finding.bidder_id == "bidder-1"
    assert finding.verification_refs == ["V-GST", "V-PAN"]
    assert "ev-gst" in finding.evidence_refs
    assert "ev-pan" in finding.evidence_refs


def test_no_findings_when_all_sources_agree() -> None:
    from tests.ai_verification.identity._builders import (
        gst_verified,
        pan_verified,
        udyam_verified,
    )

    engine = IdentityReconciliationEngine()
    records = [
        gst_verified(legal_name="ACME ENTERPRISES PRIVATE LIMITED"),
        pan_verified(name_on_pan="ACME ENTERPRISES PRIVATE LIMITED"),
        udyam_verified(enterprise_name="ACME ENTERPRISES PRIVATE LIMITED"),
    ]
    result = engine.reconcile(records, bidder_id="bidder-1")
    assert to_identity_findings(result.aggregation) == []
    assert to_verification_findings(result.aggregation) == []


def test_no_findings_when_sources_insufficient() -> None:
    from compliance_engine.models.verification import VerificationStatus

    from tests.ai_verification.identity._builders import (
        gst_verified,
        pan_verified,
    )

    engine = IdentityReconciliationEngine()
    records = [
        gst_verified(legal_name="ACME ENTERPRISES"),
        pan_verified().model_copy(
            update={"status": VerificationStatus.NOT_FOUND, "data": {}}
        ),
    ]
    result = engine.reconcile(records, bidder_id="bidder-1")
    assert to_identity_findings(result.aggregation) == []
    assert to_verification_findings(result.aggregation) == []


def test_findings_explanation_does_not_leak_secrets() -> None:
    from tests.ai_verification.identity._builders import (
        gst_verified,
        pan_verified,
    )

    engine = IdentityReconciliationEngine()
    records = [
        gst_verified(
            legal_name="ACME ENTERPRISES PRIVATE LIMITED",
            queried_identifier="27AAAAA0000A1Z5",
        ),
        pan_verified(
            name_on_pan="ACME TRADING PRIVATE LIMITED",
            queried_identifier="AAAAA0000A",
        ),
    ]
    result = engine.reconcile(records, bidder_id="bidder-1")
    for finding in to_identity_findings(result.aggregation):
        assert "27AAAAA0000A1Z5" not in finding.message
        assert "AAAAA0000A" not in finding.message


def test_findings_emit_multiple_when_multiple_pairs_disagree() -> None:
    from tests.ai_verification.identity._builders import (
        gst_verified,
        mca_verified,
        pan_verified,
        udyam_verified,
    )

    engine = IdentityReconciliationEngine()
    records = [
        gst_verified(legal_name="ACME ENTERPRISES PRIVATE LIMITED"),
        pan_verified(name_on_pan="ACME TRADING PRIVATE LIMITED"),
        udyam_verified(enterprise_name="ACME ENTERPRISES PRIVATE LIMITED"),
        mca_verified(company_name="ACME ENTERPRISES PRIVATE LIMITED"),
    ]
    result = engine.reconcile(records, bidder_id="bidder-1")
    findings = to_identity_findings(result.aggregation)
    assert len(findings) == 3


def test_to_verification_findings_bidder_override() -> None:
    from tests.ai_verification.identity._builders import (
        gst_verified,
        pan_verified,
    )

    engine = IdentityReconciliationEngine()
    records = [
        gst_verified(legal_name="ACME ENTERPRISES PRIVATE LIMITED"),
        pan_verified(name_on_pan="ACME TRADING PRIVATE LIMITED"),
    ]
    result = engine.reconcile(records, bidder_id="bidder-1")
    findings = to_verification_findings(
        result.aggregation, bidder_id="override-id"
    )
    assert all(f.bidder_id == "override-id" for f in findings)