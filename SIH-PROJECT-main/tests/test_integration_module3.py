"""Integration tests for the REAL Module 3 (compliance engine) wiring.

These tests exercise the REAL chain:

    Module 1/2-style document data
        -> app.integration.module12_adapter (explicit field mapping)
        -> Core document-level Evidence
        -> REAL Module 3: compliance_engine.ComplianceEngine with the
           canonical rules and the REAL provider adapters
        -> ComplianceResult[] + authoritative Verification[]
        -> REAL Module 4 engines (identity reconciliation over the
           Module 3 records + cross-document consistency)
        -> grounded explanations
        -> the EXISTING Core DocumentScoringEngine (Module 5)

Nothing is mocked at the engine level. The only injection is the
adapters' own documented transport seam (``StaticTransport``), which is
how the Core's own tests exercise the real adapter + parser + rule code
paths. Provider outages (the default in-process transport) stay
UNAVAILABLE / UNVERIFIABLE — never fabricated into passes or failures.
"""

from __future__ import annotations

import pytest

from compliance_engine.models import Capability
from compliance_engine.models.result import ComplianceStatus
from compliance_engine.models.verification import VerificationStatus
from compliance_engine.verification.gstn_adapter import GSTNAdapter
from compliance_engine.verification.pan_adapter import PanAdapter
from compliance_engine.verification.transport import (
    SourceResponseEnvelope,
    StaticTransport,
)
from compliance_engine.verification.udyam_adapter import UdyamAdapter

from app.integration import module4_service
from app.integration.module12_adapter import build_bidder_evidence
from app.integration.module3_service import (
    build_compliance_engine,
    derive_requirements,
    run_module3_for_bidder,
)
from tests.helpers import doc, flags_of, load_fixture, run_fixture_full

BIDDER = "b-m3"


def _business_fixture() -> dict:
    """A bidder that submitted GST + PAN + Udyam identifiers."""
    return {
        "bidder_id": BIDDER,
        "submission_id": "sub-m3-001",
        "documents": [
            doc("GST_DOC", "gst_certificate", gstin="27AAACI1234F1Z5"),
            doc("PAN_DOC", "pan_card", pan="AAACI1234F"),
            doc("UDYAM_DOC", "udyam_certificate", udyam="UDYAM-MH-12-0012345"),
        ],
    }


def _envelope(payload: dict | None = None, status_code: int = 200):
    return SourceResponseEnvelope(status_code=status_code, raw_response=payload)


def _configured_engine(
    *,
    gst_payload: dict | None,
    pan_payload: dict | None,
    udyam_payload: dict | None,
):
    """The REAL engine + REAL adapters, each with a configured transport.

    The transports are the adapters' own documented test seam: the
    real adapter, parser and rule code all execute; only the network is
    replaced by the deterministic in-memory transport.
    """
    providers = {}
    if gst_payload is not None:
        providers[Capability.GST] = GSTNAdapter(
            transport=StaticTransport(
                {"27AAACI1234F1Z5": _envelope(gst_payload)}
            )
        )
    if pan_payload is not None:
        providers[Capability.PAN_INCOME_TAX] = PanAdapter(
            transport=StaticTransport(
                {"AAACI1234F": _envelope(pan_payload)},
                query_key=lambda q: q.pan,
            )
        )
    if udyam_payload is not None:
        providers[Capability.UDYAM] = UdyamAdapter(
            transport=StaticTransport(
                {"UDYAM-MH-12-0012345": _envelope(udyam_payload)},
                query_key=lambda q: q.udyam_registration_number,
            )
        )
    return build_compliance_engine(providers=providers)


_ACME = "ACME ENTERPRISES PRIVATE LIMITED"


# TEST 1 — requirements are derived ONLY from evidence actually submitted.
def test_module3_requirements_follow_real_evidence_only():
    fixture = _business_fixture()
    evidence = build_bidder_evidence(fixture["bidder_id"], fixture["documents"])
    requirement_ids = [r.requirement_id for r in derive_requirements(evidence)]
    assert requirement_ids == [
        "m3-req-gst-registration",
        "m3-req-pan-validation",
        "m3-req-udyam-registration",
    ]

    # No triggering evidence -> no requirements -> no fabricated results.
    empty_evidence = build_bidder_evidence(
        "b-no-evidence",
        [doc("EPFO_DOC", "epfo_certificate", epfo="MHPUN0123456")],
    )
    assert derive_requirements(empty_evidence) == []
    outcome = run_module3_for_bidder("b-no-evidence", empty_evidence)
    assert outcome["compliance_results"] == []
    assert outcome["verification_records"] == []


# TEST 2 — REAL adapter path: VERIFIED provider -> PASS compliance result
# with a genuine Verification record (source, data, evidence linkage).
def test_module3_verified_produces_real_pass_and_verification():
    engine = _configured_engine(
        gst_payload={"registration_status": "ACTIVE", "legal_name": _ACME},
        pan_payload={"pan_status": "ACTIVE", "name_on_pan": _ACME},
        udyam_payload={
            "registration_status": "ACTIVE",
            "enterprise_name": _ACME,
        },
    )
    fixture = _business_fixture()
    evidence = build_bidder_evidence(fixture["bidder_id"], fixture["documents"])
    outcome = run_module3_for_bidder(
        fixture["bidder_id"], evidence, compliance_engine=engine
    )

    by_capability = {
        r["capability"]: r for r in outcome["compliance_results"]
    }
    assert set(by_capability) == {"GST", "PAN_INCOME_TAX", "UDYAM"}
    for result in by_capability.values():
        assert result["status"] == ComplianceStatus.PASS.value
        assert result["flags"] == []
        assert result["evidence_refs"], "must cite the triggering evidence"

    records = outcome["verification_records"]
    assert len(records) == 3
    for record in records:
        assert record["status"] == VerificationStatus.VERIFIED.value
        assert record["queried_identifier"]
    # The GST rule enriches its Verification with the originating
    # Evidence/document (existing rule behaviour); PAN/Udyam rules do
    # not, so those audit fields stay honestly None.
    gst_record = next(r for r in records if r["capability"] == "GST")
    assert gst_record["evidence_id"] == "GST_DOC:gstin"
    assert gst_record["document_id"] == "GST_DOC"
    assert gst_record["data"]["legal_name"] == _ACME
    assert gst_record["source"] == GSTNAdapter.SOURCE
    for record in records:
        if record["capability"] != "GST":
            assert record["evidence_id"] is None  # never fabricated
            assert record["document_id"] is None


# TEST 3 — default (unconfigured) providers honestly report UNAVAILABLE;
# the rules keep that UNVERIFIABLE — never a fake FAIL, never a fake PASS.
def test_module3_unavailable_never_becomes_failure_or_pass():
    fixture = _business_fixture()
    evidence = build_bidder_evidence(fixture["bidder_id"], fixture["documents"])
    outcome = run_module3_for_bidder(fixture["bidder_id"], evidence)  # defaults

    for result in outcome["compliance_results"]:
        assert result["status"] == ComplianceStatus.UNVERIFIABLE.value
        assert ComplianceStatus.FAIL.value != result["status"]
        assert ComplianceStatus.PASS.value != result["status"]
        assert "unavailable" in result["reason"].lower()
    for record in outcome["verification_records"]:
        assert record["status"] == VerificationStatus.UNAVAILABLE.value
    # Nothing is fabricated: no VERIFIED record ever appears by default.
    assert not any(
        r["status"] == VerificationStatus.VERIFIED.value
        for r in outcome["verification_records"]
    )


# TEST 4 — a provider transport error (5xx) also stays UNVERIFIABLE.
def test_module3_provider_error_is_not_a_compliance_failure():
    # Rebuild with an erroring GST transport (500 = source outage).
    erroring = build_compliance_engine(
        providers={
            Capability.GST: GSTNAdapter(
                transport=StaticTransport(
                    {"27AAACI1234F1Z5": _envelope(status_code=500)}
                )
            )
        }
    )
    evidence = build_bidder_evidence(
        BIDDER, [doc("GST_DOC", "gst_certificate", gstin="27AAACI1234F1Z5")]
    )
    outcome = run_module3_for_bidder(BIDDER, evidence, compliance_engine=erroring)
    result = outcome["compliance_results"][0]
    assert result["status"] == ComplianceStatus.UNVERIFIABLE.value
    assert outcome["verification_records"][0]["status"] == (
        VerificationStatus.UNAVAILABLE.value
    )
    assert result["flags"] == []  # GST rule: outage is never a violation


# TEST 5 — Module 4 identity reconciliation consumes the REAL Module 3
# Verification[] records and flags a cross-source identity mismatch.
def test_identity_reconciliation_uses_real_module3_records():
    engine = _configured_engine(
        gst_payload={"registration_status": "ACTIVE", "legal_name": _ACME},
        pan_payload={
            "pan_status": "ACTIVE",
            "name_on_pan": "UNRELATED DEMO TRADING COMPANY LIMITED",
        },
        udyam_payload={
            "registration_status": "ACTIVE",
            "enterprise_name": _ACME,
        },
    )
    fixture = _business_fixture()
    result, _evidence, module3 = run_fixture_full(fixture, compliance_engine=engine)

    assert "CROSS_SOURCE_IDENTITY_MISMATCH" in flags_of(result)
    finding = next(
        f
        for f in result["findings"]
        if f["flag_id"] == "CROSS_SOURCE_IDENTITY_MISMATCH"
    )
    # The finding cites the REAL verification IDs produced by Module 3.
    real_verification_ids = {
        v["verification_id"] for v in module3["verification_records"]
    }
    assert set(finding["verification_refs"]) <= real_verification_ids
    assert len(finding["verification_refs"]) == 2

    # The explanation is grounded in the real Module 3 records.
    explanation = next(
        e
        for e in result["explanations"]
        if e["flag_id"] == "CROSS_SOURCE_IDENTITY_MISMATCH"
    )
    assert set(explanation["grounding"]["verification_refs"]) == set(
        finding["verification_refs"]
    )
    # And in the real evidence the GST-side verification was triggered
    # by (the PAN rule does not enrich its record with evidence refs —
    # existing behaviour — so only the GST-side evidence ref appears).
    assert set(explanation["grounding"]["evidence_refs"]) == {
        "GST_DOC:gstin",
    }
    assert explanation["grounding"]["document_refs"] == ["GST_DOC"]


# TEST 6 — full Module 2 -> 3 -> 4 -> 5 flow with consistent, verified
# sources: no flags, a real score, and the Module 3 artefacts forwarded.
def test_full_pipeline_consistent_sources_clean_scored():
    engine = _configured_engine(
        gst_payload={"registration_status": "ACTIVE", "legal_name": _ACME},
        pan_payload={"pan_status": "ACTIVE", "name_on_pan": _ACME},
        udyam_payload={
            "registration_status": "ACTIVE",
            "enterprise_name": _ACME,
        },
    )
    fixture = _business_fixture()
    result, evidence, module3 = run_fixture_full(fixture, compliance_engine=engine)

    assert result["findings"] == []
    assert result["flags"] == []
    assert len(result["compliance_results"]) == 3
    assert len(result["verification_records"]) == 3
    assert result["verification_records_used"] == 3

    scoring = result["scoring"]
    assert scoring is not None
    # The SAME documents Module 4 verified were scored by Module 5, plus
    # the EXISTING policy's expected FINANCIAL document for the PAN
    # capability (the bidder submitted none — honestly scored missing).
    scored_by_id = {d["document_id"]: d for d in scoring["documents"]}
    assert {d for d in scored_by_id if d} == {"GST_DOC", "PAN_DOC", "UDYAM_DOC"}
    financial = next(
        d for d in scoring["documents"] if d["document_type"] == "FINANCIAL"
    )
    assert financial["document_id"] is None
    assert financial["present"] is False
    assert financial["score"] == 0.0

    # Each submitted document passed compliance + verification with the
    # REAL Module 3 data flowing through the existing scorer.
    for doc_id in ("GST_DOC", "PAN_DOC", "UDYAM_DOC"):
        detail = scored_by_id[doc_id]
        assert detail["compliance_statuses"] == [ComplianceStatus.PASS.value]
        assert detail["verification_statuses"] == [VerificationStatus.VERIFIED.value]
        assert detail["finding_flag_ids"] == []
        assert detail["score"] == 100.0

    # Document-level provenance chain is intact end-to-end: the SAME
    # document ids the Evidence carries are what Module 5 scored.
    evidence_doc_ids = {e.document_id for e in evidence}
    assert evidence_doc_ids == {d for d in scored_by_id if d}


# TEST 7 — cross-document contradiction is still detected in the full flow
# (Module 3 does not mask Module 4's cross-document checks).
def test_full_pipeline_cross_document_contradiction_survives():
    fixture = load_fixture("contradiction_bidder.json")
    result, _evidence, _module3 = run_fixture_full(fixture)
    assert "CROSS_DOCUMENT_ADDRESS_CONFLICT" in flags_of(result)


# TEST 8 — no duplicate extraction: when Module 2 stored per-document
# fields, the adapter maps them WITHOUT running any extractor again.
def test_adapter_maps_stored_fields_without_re_extraction(monkeypatch):
    from app.integration import module12_adapter

    def _must_not_run(*args, **kwargs):  # pragma: no cover - fails loudly
        raise AssertionError("adapter re-ran Module 2 extraction")

    monkeypatch.setattr(
        module12_adapter, "_module2_extract_document_fields", _must_not_run
    )
    documents = [
        {
            "document_id": "GST_STORED",
            "doc_type": "gst_certificate",
            "extracted_fields": {"gstin": "27AAACI1234F1Z5"},
        },
        {
            "document_id": "PAN_STORED",
            "doc_type": "pan_card",
            "extracted_fields": {"pan": "AAACI1234F"},
        },
    ]
    evidence = build_bidder_evidence("b-stored", documents)
    by_id = {e.evidence_id: e for e in evidence}
    assert by_id["GST_STORED:gstin"].value == "27AAACI1234F1Z5"
    assert by_id["PAN_STORED:pan_number"].value == "AAACI1234F"

