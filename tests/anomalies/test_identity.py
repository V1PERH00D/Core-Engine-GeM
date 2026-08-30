from compliance_engine.anomalies.identity import (
    CROSS_DOCUMENT_IDENTITY_MISMATCH,
    normalize_identity_name,
    verify_cross_document_identity,
)
from compliance_engine.models import Evidence


def _evidence(
    *,
    evidence_id: str,
    document_id: str,
    document_type: str,
    field_name: str,
    value: str | None,
    bidder_id: str = "bidder-001",
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        bidder_id=bidder_id,
        document_id=document_id,
        document_type=document_type,
        field_name=field_name,
        value=value,
    )


def test_identical_names_across_docs_match() -> None:
    evidence = [
        _evidence(
            evidence_id="ev-1",
            document_id="doc-gst",
            document_type="GST",
            field_name="legal_name",
            value="ACME ENTERPRISES PRIVATE LIMITED",
        ),
        _evidence(
            evidence_id="ev-2",
            document_id="doc-pan",
            document_type="PAN",
            field_name="name_on_pan",
            value="ACME ENTERPRISES PRIVATE LIMITED",
        ),
        _evidence(
            evidence_id="ev-3",
            document_id="doc-udyam",
            document_type="UDYAM",
            field_name="enterprise_name",
            value="ACME ENTERPRISES PRIVATE LIMITED",
        ),
    ]

    findings = verify_cross_document_identity(evidence)
    assert findings == []


def test_common_legal_suffix_variations_match() -> None:
    evidence = [
        _evidence(
            evidence_id="ev-1",
            document_id="doc-gst",
            document_type="GST",
            field_name="legal_name",
            value="ACME ENTERPRISES PVT. LTD.",
        ),
        _evidence(
            evidence_id="ev-2",
            document_id="doc-pan",
            document_type="PAN",
            field_name="name_on_pan",
            value="ACME ENTERPRISES PRIVATE LIMITED",
        ),
    ]

    findings = verify_cross_document_identity(evidence)
    assert findings == []


def test_conflicting_names_produce_cross_document_identity_mismatch() -> None:
    evidence = [
        _evidence(
            evidence_id="ev-1",
            document_id="doc-gst",
            document_type="GST",
            field_name="legal_name",
            value="ACME ENTERPRISES PRIVATE LIMITED",
        ),
        _evidence(
            evidence_id="ev-2",
            document_id="doc-pan",
            document_type="PAN",
            field_name="name_on_pan",
            value="ACME TRADING PRIVATE LIMITED",
        ),
    ]

    findings = verify_cross_document_identity(evidence)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.flag_id == CROSS_DOCUMENT_IDENTITY_MISMATCH
    assert finding.capability == "Bidder Identity"
    assert finding.evidence_refs == ["ev-1", "ev-2"]
    assert finding.normalized_values == ["acme enterprises private limited", "acme trading private limited"]


def test_only_one_identity_field_present_does_not_raise_mismatch() -> None:
    evidence = [
        _evidence(
            evidence_id="ev-1",
            document_id="doc-gst",
            document_type="GST",
            field_name="legal_name",
            value="ACME ENTERPRISES PRIVATE LIMITED",
        )
    ]

    assert verify_cross_document_identity(evidence) == []


def test_null_missing_and_not_present_values_are_ignored() -> None:
    evidence = [
        _evidence(
            evidence_id="ev-1",
            document_id="doc-gst",
            document_type="GST",
            field_name="legal_name",
            value=None,
        ),
        _evidence(
            evidence_id="ev-2",
            document_id="doc-pan",
            document_type="PAN",
            field_name="name_on_pan",
            value="NOT_PRESENT",
        ),
        _evidence(
            evidence_id="ev-3",
            document_id="doc-udyam",
            document_type="UDYAM",
            field_name="enterprise_name",
            value="ACME ENTERPRISES PRIVATE LIMITED",
        ),
    ]

    assert verify_cross_document_identity(evidence) == []


def test_multiple_records_with_one_conflicting_pair_produces_finding() -> None:
    evidence = [
        _evidence(
            evidence_id="ev-1",
            document_id="doc-gst",
            document_type="GST",
            field_name="legal_name",
            value="ACME ENTERPRISES PRIVATE LIMITED",
        ),
        _evidence(
            evidence_id="ev-2",
            document_id="doc-pan",
            document_type="PAN",
            field_name="name_on_pan",
            value="ACME ENTERPRISES PRIVATE LIMITED",
        ),
        _evidence(
            evidence_id="ev-3",
            document_id="doc-udyam",
            document_type="UDYAM",
            field_name="enterprise_name",
            value="ACME TRADING PRIVATE LIMITED",
        ),
    ]

    findings = verify_cross_document_identity(evidence)
    assert len(findings) == 1
    assert findings[0].evidence_refs == ["ev-1", "ev-3"] or findings[0].evidence_refs == ["ev-2", "ev-3"]


def test_evidence_references_are_preserved() -> None:
    evidence = [
        _evidence(
            evidence_id="ev-gst",
            document_id="doc-gst",
            document_type="GST",
            field_name="legal_name",
            value="ACME ENTERPRISES PRIVATE LIMITED",
        ),
        _evidence(
            evidence_id="ev-pan",
            document_id="doc-pan",
            document_type="PAN",
            field_name="name_on_pan",
            value="ACME TRADING PRIVATE LIMITED",
        ),
    ]

    findings = verify_cross_document_identity(evidence)
    assert findings[0].evidence_refs == ["ev-gst", "ev-pan"]
    assert findings[0].left_document_id == "doc-gst"
    assert findings[0].right_document_id == "doc-pan"


def test_normalization_is_deterministic() -> None:
    text_a = "  Acme Enterprises   Pvt. Ltd.   "
    text_b = "ACME-ENTERPRISES PVT LTD"

    first = normalize_identity_name(text_a)
    second = normalize_identity_name(text_b)
    assert first == second == "acme enterprises private limited"
