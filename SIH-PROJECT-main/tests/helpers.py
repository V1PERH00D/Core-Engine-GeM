"""Shared helpers for the Module 1/2 -> Module 4 integration tests."""

from __future__ import annotations

import json
from pathlib import Path

from app.integration import module4_service
from app.integration.module12_adapter import build_bidder_evidence

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def run_fixture(fixture: dict):
    """Fixture documents -> evidence -> Module 4 result (pure, no DB)."""
    evidence = build_bidder_evidence(
        fixture["bidder_id"],
        fixture["documents"],
        submission_id=fixture.get("submission_id"),
    )
    result = module4_service.run_bidder_verification(
        fixture["bidder_id"],
        evidence,
        evaluation_date_iso=fixture.get("evaluation_date_iso", "2025-01-15"),
    )
    return result, evidence


def run_fixture_scored(fixture: dict):
    """Fixture documents -> evidence -> Module 4 -> DocumentScoringEngine.

    This is the same invocation the Celery pipeline performs inside
    ``run_module4_for_evaluation``: the scorer receives the SAME
    document-level Evidence and findings Module 4 produced.
    """
    evidence = build_bidder_evidence(
        fixture["bidder_id"],
        fixture["documents"],
        submission_id=fixture.get("submission_id"),
    )
    result = module4_service.run_bidder_verification(
        fixture["bidder_id"],
        evidence,
        documents=fixture["documents"],
        submission_id=fixture.get("submission_id"),
        evaluation_date_iso=fixture.get("evaluation_date_iso", "2025-01-15"),
    )
    return result, evidence


def run_fixture_full(fixture: dict, *, compliance_engine=None):
    """Fixture documents -> Evidence -> REAL Module 3 -> Module 4 -> Module 5.

    This is the same invocation the Celery pipeline performs inside
    ``run_module4_for_evaluation``: Module 3 (the real compliance
    engine) runs over the document-level Evidence, its real
    ComplianceResult[]/Verification[] are handed to Module 4 (identity
    reconciliation + cross-document consistency) and forwarded to the
    DocumentScoringEngine together with the SAME evidence/findings.
    """
    from app.integration.module3_service import run_module3_for_bidder

    evidence = build_bidder_evidence(
        fixture["bidder_id"],
        fixture["documents"],
        submission_id=fixture.get("submission_id"),
    )
    module3 = run_module3_for_bidder(
        fixture["bidder_id"],
        evidence,
        submission_id=fixture.get("submission_id"),
        compliance_engine=compliance_engine,
    )
    result = module4_service.run_bidder_verification(
        fixture["bidder_id"],
        evidence,
        documents=fixture["documents"],
        submission_id=fixture.get("submission_id"),
        evaluation_date_iso=fixture.get("evaluation_date_iso", "2025-01-15"),
        compliance_results=module3["_compliance_result_objects"],
        verification_records=module3["_verification_record_objects"],
    )
    return result, evidence, module3


def doc(document_id: str, doc_type: str, **fields) -> dict:
    """A Module 1/2-style processed document (Module 2 field names)."""
    return {
        "document_id": document_id,
        "doc_type": doc_type,
        "extracted_fields": fields,
    }


def flags_of(result: dict) -> set[str]:
    return set(result["flags"])
