"""Identity findings: returned separately and coexist with compliance results."""

from __future__ import annotations

from compliance_engine.engine import ComplianceEngine

from ._builders import (
    default_providers,
    default_rules,
    make_evidence,
    pan_evidence,
    pan_requirement,
)


def test_identity_finding_returned_separately_from_compliance_results() -> None:
    gst_identity = make_evidence(
        document_id="doc-gst-001",
        document_type="GST",
        field_name="legal_name",
        value="ACME ENTERPRISES PRIVATE LIMITED",
    )
    pan_identity = make_evidence(
        document_id="doc-pan-001",
        document_type="PAN",
        field_name="name_on_pan",
        value="OTHER BIDDER PRIVATE LIMITED",
    )

    engine = ComplianceEngine(rules=default_rules(), providers=default_providers())
    result = engine.run(
        evidence=[gst_identity, pan_identity],
        requirements=[],
    )

    assert result.compliance_results == []
    assert len(result.identity_findings) == 1
    assert result.identity_findings[0].flag_id == "CROSS_DOCUMENT_IDENTITY_MISMATCH"


def test_identity_finding_present_alongside_compliance_results() -> None:
    gst_identity = make_evidence(
        document_id="doc-gst-001",
        document_type="GST",
        field_name="legal_name",
        value="ACME ENTERPRISES PRIVATE LIMITED",
    )
    pan_pan_evidence = pan_evidence()  # field_name="pan_number" for the rule
    pan_identity = make_evidence(
        document_id="doc-pan-001",
        document_type="PAN",
        field_name="name_on_pan",
        value="OTHER BIDDER PRIVATE LIMITED",
    )

    engine = ComplianceEngine(rules=default_rules(), providers=default_providers())
    result = engine.run(
        evidence=[gst_identity, pan_pan_evidence, pan_identity],
        requirements=[pan_requirement()],
    )

    assert len(result.compliance_results) == 1
    assert result.compliance_results[0].status == "PASS"
    assert len(result.identity_findings) == 1
