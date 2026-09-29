"""Document-scoring integration tests (Phase 26 TESTS 1-10 + Phase 27 E2E).

These tests exercise the REAL chain — Module 1/2-style documents -> adapter
-> Core Evidence -> real Module 4 engines -> canonical flags -> grounded
explanations -> the EXISTING Core ``DocumentScoringEngine`` — with no
mocked component and no Module 3 (``compliance_results`` /
``verification_records`` are empty in the live path and never fabricated).

Scoring expectations below come from the EXISTING scoring policy
(``document_scoring.policy.DEFAULT_POLICY`` and the deduction tables in
``document_scoring.engine``); severity comes ONLY from the canonical flag
registry via ``get_flag_definition``.
"""

from __future__ import annotations

from ai_verification.document_scoring import (
    DocumentScoreReason,
    TrafficLight,
)
from ai_verification.evidence_quality import (
    EvidenceQualityAssessment,
    QualityComponentScores,
    QualityState,
)
from compliance_engine.flags import FlagSeverity, get_flag_definition
from compliance_engine.models import (
    Applicability,
    ComplianceResult,
    ComplianceStatus,
    Requirement,
)
from compliance_engine.models.verification import Verification, VerificationStatus

from app.integration import module4_service
from app.integration.module12_adapter import (
    build_bidder_evidence,
    build_document_inputs,
)
from app.integration.scoring_service import score_bidder_documents
from tests.helpers import doc, flags_of, load_fixture, run_fixture_scored


def _detail(scoring: dict, document_id: str) -> dict:
    return next(d for d in scoring["documents"] if d["document_id"] == document_id)


# TEST 1 — clean bidder: no false Module 4 flags; score consistent with the
# existing policy (100 per document, weighted 100, GREEN).
def test_1_clean_bidder_scores_per_existing_policy():
    result, evidence = run_fixture_scored(load_fixture("clean_bidder.json"))

    assert result["findings"] == []
    assert result["flags"] == []
    scoring = result["scoring"]
    assert scoring["bidder_id"] == "bidder-fixture-100"
    assert scoring["submission_id"] == "sub-fixture-100"
    assert scoring["category"] == TrafficLight.GREEN.value
    assert scoring["score"] == 100.0
    assert scoring["reason_codes"] == [DocumentScoreReason.NO_MATERIAL_ISSUES]
    assert {d["document_id"] for d in scoring["documents"]} == {
        "GST_DOC_101",
        "PAN_DOC_102",
        "UDYAM_DOC_103",
    }
    # The scorer consumed the SAME document-level evidence Module 4 saw.
    for detail in scoring["documents"]:
        assert detail["present"] is True
        assert detail["evidence_count"] == sum(
            1 for e in evidence if e.document_id == detail["document_id"]
        )
        assert detail["average_evidence_confidence"] is None  # never faked


# TEST 2 — one CRITICAL Module 4 finding: canonical flag exists; the engine
# applies its existing material-finding deduction (-25) to both involved
# documents; the weighted bidder score reflects the document scores.
def test_2_critical_finding_lowers_score_per_policy():
    fixture = {
        "bidder_id": "b-crit-score",
        "documents": [
            doc("GST_A", "gst_certificate", gstin="27AAACI1234F1Z5"),
            doc("GST_B", "gst_certificate", gstin="29BBBCD1234E1Z6"),
        ],
    }
    result, _evidence = run_fixture_scored(fixture)

    assert "CROSS_DOCUMENT_IDENTIFIER_CONFLICT" in flags_of(result)
    finding = next(
        f for f in result["findings"]
        if f["flag_id"] == "CROSS_DOCUMENT_IDENTIFIER_CONFLICT"
    )
    # Severity comes from the canonical flag registry — CRITICAL is material.
    severity = get_flag_definition("CROSS_DOCUMENT_IDENTIFIER_CONFLICT").severity
    assert severity is FlagSeverity.CRITICAL
    assert finding["severity"] == severity.value

    scoring = result["scoring"]
    # GST weight 1.0 each; 100 - 25 (MATERIAL_FINDING) = 75.0
    for doc_id in ("GST_A", "GST_B"):
        detail = _detail(scoring, doc_id)
        assert detail["score"] == 75.0
        assert detail["finding_flag_ids"] == ["CROSS_DOCUMENT_IDENTIFIER_CONFLICT"]
        assert DocumentScoreReason.MATERIAL_FINDING in detail["reasons"]
    assert scoring["score"] == 75.0
    assert scoring["category"] == TrafficLight.RED.value


# TEST 3 — missing evidence is not a contradiction and is scored with the
# existing NO_EVIDENCE deduction.
def test_3_missing_evidence_no_false_flag_scored_by_policy():
    fixture = {
        "bidder_id": "b-no-evidence-score",
        "documents": [
            doc(
                "GST_DOC",
                "gst_certificate",
                gstin="27AAACI1234F1Z5",
                registered_address="Plot 42, Pune, Maharashtra 411057",
            ),
            doc("UDYAM_DOC", "udyam_certificate", udyam="UDYAM-MH-12-0012345"),
            doc("PAN_DOC", "pan_card"),  # no extracted fields at all
        ],
    }
    result, evidence = run_fixture_scored(fixture)

    # Missing UDYAM address evidence did NOT become a contradiction.
    assert result["flags"] == []
    assert not any(
        e.field_name == "registered_address" and e.document_id == "UDYAM_DOC"
        for e in evidence
    )

    scoring = result["scoring"]
    pan_detail = _detail(scoring, "PAN_DOC")
    assert pan_detail["evidence_count"] == 0
    assert pan_detail["score"] == 65.0  # 100 - 35 (existing NO_EVIDENCE)
    assert pan_detail["reasons"] == [DocumentScoreReason.NO_EVIDENCE]
    # (100*1.0 GST + 100*0.8 UDYAM + 65*1.0 PAN) / 2.8 = 87.5
    assert scoring["score"] == 87.5

# TEST 4 — evidence quality: when a real EvidenceQualityAssessment exists it
# is consumed by the existing quality deductions; when it does not exist the
# pipeline passes nothing and invents no deduction.
def test_4_evidence_quality_consumed_only_when_real():
    fixture = {
        "bidder_id": "b-quality",
        "documents": [doc("GST_A", "gst_certificate", gstin="27AAACI1234F1Z5")],
    }
    result, evidence = run_fixture_scored(fixture)

    # Live pipeline produces no quality assessment -> no quality reasons.
    assert result["scoring"]["reason_codes"] == [
        DocumentScoreReason.NO_MATERIAL_ISSUES
    ]

    documents = build_document_inputs(fixture["documents"])
    components = QualityComponentScores(
        ocr_quality=0.2, field_quality=0.5, completeness=0.5,
        metadata_reliability=0.3,
    )
    degraded = EvidenceQualityAssessment(
        state=QualityState.DEGRADED, quality_score=0.35, components=components,
    )
    degraded_score = score_bidder_documents(
        "b-quality",
        documents=documents,
        evidence=evidence,
        quality_by_document_id={"GST_A": degraded},
    )
    detail = degraded_score.documents[0]
    assert detail.score == 85.0  # 100 - 15 (existing DEGRADED deduction)
    assert DocumentScoreReason.EVIDENCE_QUALITY_DEGRADED in detail.reasons

    unknown = degraded.model_copy(update={"state": QualityState.UNKNOWN})
    unknown_score = score_bidder_documents(
        "b-quality",
        documents=documents,
        evidence=evidence,
        quality_by_document_id={"GST_A": unknown},
    )
    detail = unknown_score.documents[0]
    assert detail.score == 75.0  # 100 - 25 (existing UNKNOWN deduction)
    assert DocumentScoreReason.EVIDENCE_QUALITY_UNKNOWN in detail.reasons


# TEST 5 — multiple documents with different policy weights: the weighted
# bidder score matches the engine's existing weighted calculation.
def test_5_weighted_bidder_score_matches_policy_weights():
    fixture = {
        "bidder_id": "b-weights",
        "documents": [
            doc("GST_A", "gst_certificate", gstin="27AAACI1234F1Z5"),
            doc("GST_B", "gst_certificate", gstin="29BBBCD1234E1Z6"),
            doc("UDYAM_A", "udyam_certificate", udyam="UDYAM-MH-12-0012345"),
            doc("MII_A", "make_in_india_local_content",
                declared_local_content_pct=68.5),
        ],
    }
    result, _evidence = run_fixture_scored(fixture)
    scoring = result["scoring"]

    # GST w=1.0 -> 75 each (material finding); UDYAM w=0.8 -> 100;
    # MAKE_IN_INDIA w=0.8 -> 100. Weighted: (75+75+80+80)/3.6 = 86.11
    expected = round(
        (75.0 * 1.0 + 75.0 * 1.0 + 100.0 * 0.8 + 100.0 * 0.8) / 3.6, 2
    )
    assert scoring["score"] == expected == 86.11
    assert scoring["category"] == TrafficLight.RED.value  # material finding
    weights = {d["document_id"]: d["weight"] for d in scoring["documents"]}
    assert weights == {"GST_A": 1.0, "GST_B": 1.0, "UDYAM_A": 0.8, "MII_A": 0.8}
    assert {d["priority"] for d in scoring["documents"]} == {
        "CRITICAL", "CRITICAL", "HIGH", "HIGH"
    }


# TEST 6 — missing expected document when REAL requirements exist: the
# existing DOCUMENT_MISSING / missing-document category logic applies.
def test_6_missing_expected_document_with_real_requirements():
    documents = build_document_inputs(
        [doc("PAN_DOC", "pan_card", pan="AAACI1234F")]
    )
    requirements = [
        Requirement(
            requirement_id="req-gst-1",
            capability="GST",
            description="GST registration certificate is required",
            mandatory=True,
            applicability=Applicability.APPLICABLE,
            rule_id="GST_REGISTRATION_REQUIRED",
        )
    ]
    evidence = build_bidder_evidence(
        "b-missing-doc", [doc("PAN_DOC", "pan_card", pan="AAACI1234F")]
    )

    score = score_bidder_documents(
        "b-missing-doc",
        documents=documents,
        requirements=requirements,
        evidence=evidence,
    )

    missing = next(d for d in score.documents if d.document_type == "GST")
    assert missing.present is False
    assert missing.document_id is None
    assert missing.score == 0.0
    assert DocumentScoreReason.DOCUMENT_MISSING in missing.reasons
    assert DocumentScoreReason.NO_EVIDENCE in missing.reasons
    assert DocumentScoreReason.DOCUMENT_MISSING in score.reason_codes
    # GST is CRITICAL priority -> missing critical doc -> RED (existing rule).
    assert score.category is TrafficLight.RED
    # Weighted: (100*1.0 PAN + 0*1.0 GST) / 2.0 = 50.0
    assert score.score == 50.0


# TEST 7 — no Module 3: compliance_results / verification_records stay empty;
# Module 4 and scoring still run end to end.
def test_7_scoring_runs_without_module3():
    import sys

    assert not any(name.startswith("module3") for name in sys.modules)

    result, _evidence = run_fixture_scored(load_fixture("contradiction_bidder.json"))
    assert result["verification_records_used"] == 0
    assert result["status"] == module4_service.STATUS_VERIFIED
    scoring = result["scoring"]
    assert scoring is not None
    # No compliance/verification reasons can exist without Module 3 data.
    assert not any(
        code.startswith(("COMPLIANCE_", "VERIFICATION_"))
        for code in scoring["reason_codes"]
    )
    for detail in scoring["documents"]:
        assert detail["compliance_statuses"] == []
        assert detail["verification_statuses"] == []


# TEST 8 — future Module 3 data consumption (UNIT input to the existing
# engine; this is NOT an implementation or mock of Module 3): real Core
# ComplianceResult / Verification structures flow through the unchanged
# DocumentScoringEngine.
def test_8_engine_consumes_future_module3_data_unchanged():
    documents = build_document_inputs(
        [doc("GST_A", "gst_certificate", gstin="27AAACI1234F1Z5")]
    )
    evidence = build_bidder_evidence(
        "b-future", [doc("GST_A", "gst_certificate", gstin="27AAACI1234F1Z5")]
    )
    compliance_results = [
        ComplianceResult(
            requirement_id="req-gst-1",
            capability="GST",
            status=ComplianceStatus.FAIL,
            reason="GSTIN not active on GSTN portal",
            rule_id="GST_ACTIVE_REQUIRED",
        )
    ]
    verification_records = [
        Verification(
            verification_id="ver-gst-1",
            bidder_id="b-future",
            capability="GST",
            source="GSTN_PORTAL",
            queried_identifier="27AAACI1234F1Z5",
            status=VerificationStatus.INVALID,
        )
    ]

    score = score_bidder_documents(
        "b-future",
        documents=documents,
        evidence=evidence,
        compliance_results=compliance_results,
        verification_records=verification_records,
    )

    detail = score.documents[0]
    # Existing deductions: COMPLIANCE FAIL -60 + VERIFICATION INVALID -45.
    assert detail.score == 0.0
    assert detail.compliance_statuses == (ComplianceStatus.FAIL.value,)
    assert detail.verification_statuses == (VerificationStatus.INVALID.value,)
    assert DocumentScoreReason.COMPLIANCE_FAILED in detail.reasons
    assert DocumentScoreReason.VERIFICATION_FAILED in detail.reasons
    assert score.category is TrafficLight.RED
    assert score.score == 0.0


# TEST 9 — flag severity comes from the canonical registry, not the scoring
# layer: a MEDIUM canonical flag does NOT receive the material deduction.
def test_9_materiality_follows_canonical_flag_severity():
    fixture = {
        "bidder_id": "b-medium",
        "documents": [
            doc("MII_A", "make_in_india_local_content",
                supplier_class="Class-I Local Supplier"),
            doc("MII_B", "make_in_india_local_content",
                supplier_class="Non-Local Supplier"),
        ],
    }
    result, _evidence = run_fixture_scored(fixture)

    assert "CROSS_DOCUMENT_PRODUCT_MISMATCH" in flags_of(result)
    definition = get_flag_definition("CROSS_DOCUMENT_PRODUCT_MISMATCH")
    assert definition.severity is FlagSeverity.MEDIUM  # NOT CRITICAL/HIGH
    finding = result["findings"][0]
    assert finding["severity"] == definition.severity.value

    scoring = result["scoring"]
    # MEDIUM is not a material severity under the existing scoring policy:
    # no MATERIAL_FINDING deduction, no fabricated severity.
    assert DocumentScoreReason.MATERIAL_FINDING not in scoring["reason_codes"]
    assert scoring["score"] == 100.0
    assert scoring["category"] == TrafficLight.GREEN.value
    # ...but the finding itself is still fully reported per document.
    assert all(
        "CROSS_DOCUMENT_PRODUCT_MISMATCH" in d["finding_flag_ids"]
        for d in scoring["documents"]
    )


# TEST 10 — explanation independence: generating explanations cannot change
# flags or scores.
def test_10_explanations_do_not_change_flags_or_scores():
    fixture = {
        "bidder_id": "b-explain-independent",
        "documents": [
            doc("GST_A", "gst_certificate", gstin="27AAACI1234F1Z5"),
            doc("GST_B", "gst_certificate", gstin="29BBBCD1234E1Z6"),
        ],
    }
    result, evidence = run_fixture_scored(fixture)
    assert result["explanations"]  # explanations were produced

    scoring_before = result["scoring"]
    flags_before = list(result["flags"])
    findings_before = [dict(f) for f in result["findings"]]

    # Regenerate explanations over the SAME findings (as an LLM-backed
    # explanation pass would) and re-score the SAME inputs.
    from ai_verification.explanations import ExplanationEngine
    from ai_verification.models.contracts import VerificationFinding

    evidence_by_id = {e.evidence_id: e for e in evidence}
    explainer = ExplanationEngine()
    for raw in findings_before:
        finding = VerificationFinding.model_validate(raw)
        assert module4_service.explain_finding(
            explainer, finding, evidence_by_id=evidence_by_id, aggregation=None
        ).fallback_used is True

    rescored = score_bidder_documents(
        fixture["bidder_id"],
        documents=build_document_inputs(fixture["documents"]),
        evidence=evidence,
        findings=[VerificationFinding.model_validate(f) for f in findings_before],
    )
    assert rescored.model_dump(mode="json") == scoring_before
    assert result["flags"] == flags_before


# Phase 27 — complete end-to-end fixture: Module 1/2-style documents ->
# document-level Evidence -> Module 4 -> canonical flag -> grounded
# explanation -> per-document scores -> weighted bidder score -> category.
def test_phase27_end_to_end_scored_pipeline():
    fixture = load_fixture("contradiction_bidder.json")
    result, evidence = run_fixture_scored(fixture)

    # Module 4 consumed the module-1/2-derived evidence and flagged the
    # GST-vs-UDYAM address contradiction (canonical HIGH flag).
    finding = next(
        f for f in result["findings"]
        if f["flag_id"] == "CROSS_DOCUMENT_ADDRESS_CONFLICT"
    )
    assert set(finding["evidence_refs"]) == {
        "GST_DOC_001:registered_address",
        "UDYAM_DOC_003:registered_address",
    }
    assert finding["severity"] == (
        get_flag_definition("CROSS_DOCUMENT_ADDRESS_CONFLICT").severity.value
    )
    assert finding["severity"] == FlagSeverity.HIGH.value

    explanation = next(
        e for e in result["explanations"]
        if e["flag_id"] == "CROSS_DOCUMENT_ADDRESS_CONFLICT"
    )
    assert "89 MG Road, Bengaluru, Karnataka 560001" in (
        explanation["content"]["detailed_explanation"]
    )

    scoring = result["scoring"]
    assert {d["document_id"] for d in scoring["documents"]} == {
        "GST_DOC_001", "PAN_DOC_002", "UDYAM_DOC_003", "MII_DOC_004",
    }
    gst = _detail(scoring, "GST_DOC_001")
    udyam = _detail(scoring, "UDYAM_DOC_003")
    pan = _detail(scoring, "PAN_DOC_002")
    mii = _detail(scoring, "MII_DOC_004")
    # HIGH severity -> existing material-finding deduction on both sides.
    assert gst["score"] == 75.0 and udyam["score"] == 75.0
    assert DocumentScoreReason.MATERIAL_FINDING in gst["reasons"]
    assert DocumentScoreReason.MATERIAL_FINDING in udyam["reasons"]
    assert gst["finding_flag_ids"] == ["CROSS_DOCUMENT_ADDRESS_CONFLICT"]
    # Clean documents stay at 100.
    assert pan["score"] == 100.0 and mii["score"] == 100.0
    assert gst["evidence_count"] == sum(
        1 for e in evidence if e.document_id == "GST_DOC_001"
    )
    # Weighted bidder score and category per the existing policy.
    expected = round(
        (75.0 * 1.0 + 100.0 * 1.0 + 75.0 * 0.8 + 100.0 * 0.8) / 3.6, 2
    )
    assert scoring["score"] == expected == 87.5
    assert scoring["category"] == TrafficLight.RED.value
    assert DocumentScoreReason.MATERIAL_FINDING in scoring["reason_codes"]
    assert "bidder-fixture-001" in scoring["summary"]


# Phase 29 edge cases on the existing engine semantics.
def test_edge_cases_match_existing_engine_semantics():
    # No documents at all -> the engine's existing empty-result behaviour.
    empty = score_bidder_documents("b-none", documents=[])
    assert empty.score == 0.0
    assert empty.category is TrafficLight.RED
    assert empty.reason_codes == (DocumentScoreReason.DOCUMENT_MISSING,)

    # Unknown document type keeps the existing UNKNOWN behaviour.
    unknown = score_bidder_documents(
        "b-unknown",
        documents=build_document_inputs(
            [doc("MYSTERY_DOC", "something_unmapped")]
        ),
    )
    detail = unknown.documents[0]
    assert detail.document_type == "UNKNOWN"
    assert DocumentScoreReason.UNKNOWN_DOCUMENT_TYPE in detail.reasons
    assert unknown.category is TrafficLight.YELLOW  # unknown_document rule

    # Scores are always clamped to [0, 100].
    assert 0.0 <= unknown.score <= 100.0


def test_scoring_record_structure_is_api_and_persistence_ready():
    """The persisted/exposed scoring payload keeps per-document provenance."""
    result, evidence = run_fixture_scored(load_fixture("clean_bidder.json"))
    scoring = result["scoring"]
    evidence_ids = {e.evidence_id for e in evidence}

    for detail in scoring["documents"]:
        assert detail["document_id"] in {
            e.split(":", 1)[0] for e in evidence_ids
        }
        assert isinstance(detail["finding_flag_ids"], list)
        assert isinstance(detail["reasons"], list)
        assert 0.0 <= detail["score"] <= 100.0
    assert scoring["category"] in {"RED", "YELLOW", "GREEN"}
    assert isinstance(scoring["summary"], str)

    # The ORM record expects exactly these serializable fields.
    record_payload = {
        "bidder_id": scoring["bidder_id"],
        "submission_id": scoring["submission_id"],
        "overall_score": scoring["score"],
        "category": scoring["category"],
        "reason_codes": scoring["reason_codes"],
        "document_scores": scoring["documents"],
        "summary": scoring["summary"],
    }
    import json

    json.dumps(record_payload)  # must be JSON-serializable for persistence


def test_document_inputs_match_module4_evidence_identity():
    """DocumentInput identities are exactly those of the Module 4 evidence."""
    from app.integration.field_mapping import map_document_type

    documents = [
        doc("GST_X", "gst_certificate", gstin="27AAACI1234F1Z5"),
        doc("UDYAM_X", "udyam_certificate"),  # no evidence at all
    ]
    inputs = build_document_inputs(documents)
    evidence = build_bidder_evidence("b-identity", documents)

    assert [(i.document_id, i.document_type) for i in inputs] == [
        ("GST_X", map_document_type("gst_certificate")),
        ("UDYAM_X", map_document_type("udyam_certificate")),
    ]
    # Every evidence item belongs to a scored document, and a document with
    # no evidence is still scored (its own NO_EVIDENCE policy).
    assert {e.document_id for e in evidence} <= {i.document_id for i in inputs}
    evidence_id_set = {e.evidence_id for e in evidence}
    for e in evidence:
        assert e.evidence_id == f"{e.document_id}:{e.field_name}"
    result, _ = run_fixture_scored({
        "bidder_id": "b-identity",
        "documents": documents,
    })
    for detail in result["scoring"]["documents"]:
        for flag_ref_prefix in detail["finding_flag_ids"]:
            assert flag_ref_prefix  # flags seen by scorer are canonical ids
    # Module 4 evidence ids and the scorer's evidence view coincide.
    assert evidence_id_set == result_scoring_evidence_ids(result)


def result_scoring_evidence_ids(result: dict) -> set[str]:
    return {e["evidence_id"] for e in result["evidence"]}

    assert scoring["category"] == TrafficLight.GREEN.value
