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


def doc(document_id: str, doc_type: str, **fields) -> dict:
    """A Module 1/2-style processed document (Module 2 field names)."""
    return {
        "document_id": document_id,
        "doc_type": doc_type,
        "extracted_fields": fields,
    }


def flags_of(result: dict) -> set[str]:
    return set(result["flags"])
