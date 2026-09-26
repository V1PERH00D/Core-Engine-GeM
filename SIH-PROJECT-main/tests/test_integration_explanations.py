"""Explanation grounding/immutability, no-Module-3, consolidated-output
regression and the end-to-end pipeline test (TEST K, L, M, J, N)."""

from __future__ import annotations

import json

from app.integration import module4_service
from app.integration.future_module3 import ComplianceStage
from app.integration.module12_adapter import (
    build_bidder_evidence,
    build_upstream_payload,
    extract_document_fields,
)
from tests.helpers import doc, flags_of, load_fixture, run_fixture


# TEST J — consolidated output regression (Module 2 still works)
def test_j_consolidated_bidder_extraction_still_works():
    from app.entity_extraction.tasks import process_entity_extraction_job

    sample_payload = {
        "submission_id": "test_submission_regression",
        "pages": [
            {
                "page_number": 1,
                "raw_text": (
                    "GSTIN: 27AAACI1234F1Z5 PAN: AAACI1234F "
                    "UDYAM-MH-12-0012345"
                ),
                "blocks": [],
            },
            {
                "page_number": 2,
                "raw_text": (
                    "Financials: FY 2022-23: INR 12.50 Cr. "
                    "FY 2023-24: INR 15.00 Cr. Net Worth: INR 20.0 Cr. "
                    "Local Content: 65%"
                ),
                "blocks": [],
            },
        ],
    }
    result = process_entity_extraction_job(sample_payload)
    assert result["status"] == "SUCCESS"
    assert result["bidders"][0]["document_count"] == 2
    data = result["bidders"][0]["extracted_entities"]
    assert data["gst"]["gstin"] == "27AAACI1234F1Z5"
    assert data["pan_itr"]["pan_number"] == "AAACI1234F"
    assert data["make_in_india"]["supplier_class"] == "Class-I Local Supplier"
    assert len(data["balance_sheet"]["turnover_records"]) == 2


# TEST K — explanation grounding: explanation receives real source evidence
def test_k_explanation_is_grounded_in_real_evidence():
    result, _evidence = run_fixture(load_fixture("contradiction_bidder.json"))
    finding = next(
        f for f in result["findings"]
        if f["flag_id"] == "CROSS_DOCUMENT_ADDRESS_CONFLICT"
    )
    explanation = next(
        e for e in result["explanations"] if e["flag_id"] == finding["flag_id"]
    )

    # Grounding carries the actual evidence refs and document ids.
    assert set(explanation["grounding"]["evidence_refs"]) == set(
        finding["evidence_refs"]
    )
    assert set(explanation["grounding"]["document_refs"]) == {
        "GST_DOC_001",
        "UDYAM_DOC_003",
    }
    assert finding["finding_id"] in explanation["grounding"]["finding_refs"]

    # The explanation text is composed from the real extracted values of
    # both source documents (deterministic fallback, facts-only).
    detailed = explanation["content"]["detailed_explanation"]
    assert "Plot 42, Hinjawadi Phase 1, Pune, Maharashtra 411057" in detailed
    assert "89 MG Road, Bengaluru, Karnataka 560001" in detailed
    # The structured comparison outcome is one of the supplied facts.
    observed = [f["fact_ref"] for f in explanation["content"]["observed_facts"]]
    assert any(ref.startswith("comparison:") for ref in observed)


# TEST L — explanation immutability: explaining never changes flags/findings
def test_l_explanations_cannot_modify_findings():
    evidence = build_bidder_evidence(
        "b-immutable",
        [
            doc("GST_A", "gst_certificate", gstin="27AAACI1234F1Z5"),
            doc("GST_B", "gst_certificate", gstin="29BBBCD1234E1Z6"),
        ],
    )
    result = module4_service.run_bidder_verification("b-immutable", evidence)

    findings_before = [json.loads(json.dumps(f)) for f in result["findings"]]
    flags_before = list(result["flags"])

    # Regenerate explanations over the SAME findings (a second pass, as an
    # LLM-backed engine would also do).
    from ai_verification.explanations import ExplanationEngine
    from ai_verification.models.contracts import VerificationFinding

    evidence_by_id = {e.evidence_id: e for e in evidence}
    engine = ExplanationEngine()  # deterministic fallback (no LLM) here
    for raw in result["findings"]:
        finding = VerificationFinding.model_validate(raw)
        explanation = module4_service.explain_finding(
            engine, finding, evidence_by_id=evidence_by_id, aggregation=None
        )
        assert explanation.fallback_used is True
        # Values cited in the explanation come from real evidence only.
        assert set(explanation.grounding.evidence_refs) <= set(
            evidence_by_id.keys()
        )

    # Findings and flags are bit-for-bit what the deterministic engine
    # produced; explanation work changed nothing.
    assert result["findings"] == findings_before
    assert result["flags"] == flags_before


# TEST M — no Module 3 dependency
def test_m_pipeline_runs_without_module3():
    import sys

    # Nothing named like Module 3 is imported by the integration path.
    assert not any(name.startswith("module3") for name in sys.modules)

    # The future hook exists but defines no implementation.
    assert callable(ComplianceStage.run)

    # A complete evaluation runs with ZERO authoritative verifications.
    result, _evidence = run_fixture(load_fixture("contradiction_bidder.json"))
    assert result["status"] == module4_service.STATUS_VERIFIED
    assert result["verification_records_used"] == 0
    assert result["flags"]  # findings still emerge from Evidence alone
