"""Integration tests for the Module 1/2 -> Module 4 boundary.

These tests exercise the REAL components end to end:

    Module 1/2-style document data
        -> app.integration.module12_adapter (explicit field mapping)
        -> Core ``normalize_upstream`` (canonical Evidence)
        -> Core ``VerificationEngine`` with the real
           ``IdentityReconciliationEngine`` and
           ``CrossDocumentConsistencyEngine`` wired in
        -> canonical findings / flags
        -> Core ``ExplanationEngine`` (deterministic fallback)

No component is mocked. Module 3 is neither implemented nor stubbed: the
pipeline runs with zero authoritative Verification records.

This file covers TEST A (clean documents), TEST B/C (identifier
conflict / match), TEST D/E (address conflict / missing address) and
TEST I (document provenance).
"""

from __future__ import annotations

from app.integration import module4_service
from tests.helpers import doc, flags_of, load_fixture, run_fixture


# TEST A — clean documents: consistent GST/PAN/UDYAM produce no false flags
def test_a_clean_documents_no_false_conflicts():
    result, evidence = run_fixture(load_fixture("clean_bidder.json"))
    assert result["status"] == module4_service.STATUS_VERIFIED
    assert result["findings"] == []
    assert result["flags"] == []
    assert result["explanations"] == []
    # But evidence was genuinely produced for every document field.
    assert len(evidence) >= 5
    for record in evidence:
        assert record.confidence is None  # Module 2 has none; never faked
        assert record.page is None
        assert record.bbox is None


# TEST B — actual identifier conflict -> CROSS_DOCUMENT_IDENTIFIER_CONFLICT
def test_b_identifier_conflict_flagged():
    fixture = {
        "bidder_id": "b-ident-conflict",
        "documents": [
            doc("GST_A", "gst_certificate", gstin="27AAACI1234F1Z5"),
            doc("GST_B", "gst_certificate", gstin="29BBBCD1234E1Z6"),
        ],
    }
    result, _evidence = run_fixture(fixture)
    assert "CROSS_DOCUMENT_IDENTIFIER_CONFLICT" in flags_of(result)
    finding = next(
        f for f in result["findings"]
        if f["flag_id"] == "CROSS_DOCUMENT_IDENTIFIER_CONFLICT"
    )
    from compliance_engine.flags import get_flag_definition

    assert finding["severity"] == get_flag_definition(
        "CROSS_DOCUMENT_IDENTIFIER_CONFLICT"
    ).severity.value
    assert set(finding["evidence_refs"]) == {"GST_A:gstin", "GST_B:gstin"}


# TEST C — matching identifiers -> no conflict flag
def test_c_matching_identifiers_no_conflict():
    fixture = {
        "bidder_id": "b-ident-match",
        "documents": [
            doc("GST_A", "gst_certificate", gstin="27AAACI1234F1Z5"),
            # same identifier, different casing
            doc("GST_B", "gst_certificate", gstin="27aaaci1234f1z5"),
        ],
    }
    result, _evidence = run_fixture(fixture)
    assert result["findings"] == []
    assert result["flags"] == []


# TEST D — address conflict -> CROSS_DOCUMENT_ADDRESS_CONFLICT
def test_d_address_conflict_flagged():
    result, _evidence = run_fixture(load_fixture("contradiction_bidder.json"))
    assert "CROSS_DOCUMENT_ADDRESS_CONFLICT" in flags_of(result)
    finding = next(
        f for f in result["findings"]
        if f["flag_id"] == "CROSS_DOCUMENT_ADDRESS_CONFLICT"
    )
    assert set(finding["evidence_refs"]) == {
        "GST_DOC_001:registered_address",
        "UDYAM_DOC_003:registered_address",
    }


# TEST E — missing address in one doc is NOT a conflict
def test_e_missing_address_is_not_a_conflict():
    fixture = {
        "bidder_id": "b-missing-address",
        "documents": [
            doc(
                "GST_DOC",
                "gst_certificate",
                gstin="27AAACI1234F1Z5",
                registered_address="Plot 42, Pune, Maharashtra 411057",
            ),
            # Udyam certificate without any address evidence:
            doc("UDYAM_DOC", "udyam_certificate", udyam="UDYAM-MH-12-0012345"),
        ],
    }
    result, evidence = run_fixture(fixture)
    assert "CROSS_DOCUMENT_ADDRESS_CONFLICT" not in flags_of(result)
    assert result["findings"] == []
    # The absent field produced no Evidence at all — nothing fabricated.
    assert not any(
        e.field_name == "registered_address" and e.document_id == "UDYAM_DOC"
        for e in evidence
    )


# TEST I — provenance: evidence from document A keeps document A's identity
def test_i_evidence_provenance_is_preserved():
    _result, evidence = run_fixture(load_fixture("contradiction_bidder.json"))
    by_id = {e.evidence_id: e for e in evidence}

    gstin = by_id["GST_DOC_001:gstin"]
    assert gstin.document_id == "GST_DOC_001"
    assert gstin.document_type == "GST"
    assert gstin.value == "27AAACI1234F1Z5"
    assert gstin.bidder_id == "bidder-fixture-001"

    addr = by_id["UDYAM_DOC_003:registered_address"]
    assert addr.document_id == "UDYAM_DOC_003"
    assert addr.document_type == "UDYAM"
    assert "Bengaluru" in addr.value
    # Never attributed to the GST document.
    assert not any(
        e.document_id == "GST_DOC_001" and "Bengaluru" in str(e.value)
        for e in evidence
    )
    # Deterministic identity: same input -> same Evidence ids.
    _r2, again = run_fixture(load_fixture("contradiction_bidder.json"))
    assert {e.evidence_id for e in evidence} == {e.evidence_id for e in again}
