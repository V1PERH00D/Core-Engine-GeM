"""Prompt 3: NormalizedSubmission -> ComplianceEngine -> EngineResult -> persistence.


Proves the bridge preserves submission/bidder/document provenance,
upstream file_hash (distinct from content_hash), missing_reason, and
financial evidence, using the REAL upstream fixture and the in-memory
persistence stack (no PostgreSQL required).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from compliance_engine.engine import ComplianceEngine
from compliance_engine.ingestion.upstream import normalize_submission
from compliance_engine.models import Capability, Applicability, Requirement
from compliance_engine.rules.gst import GSTRegistrationRule
from compliance_engine.verification.base import MockGSTProvider

from infrastructure.persistence.engine_persistence import persist_engine_result
from infrastructure.persistence.memory import _Store
from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "upstream"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def clock():
    value = {"t": 1000.0}

    def _clock() -> float:
        value["t"] += 1.0
        return value["t"]

    return _clock


@pytest.fixture
def uow_factory():
    store = _Store()

    def _factory() -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(store)

    return _factory


def _submission(name: str = "sample.json"):
    return normalize_submission(_load(name))


def _gst_requirement() -> Requirement:
    return Requirement(
        requirement_id="req-gst-1",
        capability=Capability.GST,
        description="Bidder must hold an active GST registration.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="ACTIVE",
        rule_id="GST_REGISTRATION_001",
    )


def _engine() -> ComplianceEngine:
    return ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: MockGSTProvider()},
    )


def test_engine_result_carries_supplied_submission_id() -> None:
    submission = _submission()
    result = _engine().run(
        evidence=submission.evidence,
        requirements=[_gst_requirement()],
        submission_id=submission.submission_id,
    )
    assert result.submission_id == submission.submission_id
    assert result.bidder_id == submission.bidder_id


def test_engine_result_submission_id_defaults_to_none() -> None:
    submission = _submission()
    result = _engine().run(
        evidence=submission.evidence, requirements=[_gst_requirement()]
    )
    assert result.submission_id is None


@pytest.fixture
def persisted(uow_factory, clock):
    submission = _submission()
    result = _engine().run(
        evidence=submission.evidence,
        requirements=[_gst_requirement()],
        submission_id=submission.submission_id,
    )
    persist_engine_result(
        submission, result, uow=uow_factory(), clock=clock,
        correlation_id="trace-p3",
    )
    return submission, result
# --------------------------------------------------------------------------
# Bridge assertions
# --------------------------------------------------------------------------


def test_submission_and_bidder_survive_end_to_end(uow_factory, persisted):
    submission, _ = persisted
    with uow_factory() as uow:
        rec = uow.repos.submissions.get(submission.submission_id)
        bidder = uow.repos.bidders.get(submission.bidder_id)
    assert rec is not None
    assert rec.submission_id == submission.submission_id
    assert rec.bidder_id == submission.bidder_id
    assert bidder is not None


def test_document_id_and_type_survive(uow_factory, persisted):
    submission, _ = persisted
    with uow_factory() as uow:
        docs = uow.repos.documents.list_by_submission(submission.submission_id)
    assert {d.document_id for d in docs} == {
        d.document_id for d in submission.documents
    }
    for doc in docs:
        normalized = next(
            d for d in submission.documents if d.document_id == doc.document_id
        )
        assert doc.document_type == normalized.doc_type
        assert doc.bidder_id == submission.bidder_id
        assert doc.submission_id == submission.submission_id


def test_upstream_file_hash_not_confused_with_content_hash(
    uow_factory, persisted
):
    submission, _ = persisted
    with uow_factory() as uow:
        docs = {
            d.document_id: d
            for d in uow.repos.documents.list_by_bidder(submission.bidder_id)
        }
    for normalized in submission.documents:
        rec = docs[normalized.document_id]
        # Upstream file_hash survives as provenance metadata...
        assert rec.metadata["file_hash"] == normalized.file_hash
        # ...and is NOT treated as the artifact content hash.
        assert rec.content_hash is None
        # Other document-level provenance survives too.
        assert rec.metadata["doc_type_confidence"] == normalized.doc_type_confidence
        assert rec.metadata["ocr_confidence"] == normalized.ocr_confidence

def test_missing_reason_survives_into_evidence_records(uow_factory, persisted):
    submission, _ = persisted
    by_id = {}
    with uow_factory() as uow:
        for doc in submission.documents:
            for rec in uow.repos.evidence.list_by_document(doc.document_id):
                by_id[rec.evidence_id] = rec
    for doc in submission.documents:
        for ev in doc.evidence:
            rec = by_id[ev.evidence_id]
            assert rec.missing_reason == ev.missing_reason
            assert rec.confidence == ev.confidence
            assert rec.page == ev.page
            assert rec.bbox == (None if ev.bbox is None else list(ev.bbox))
    # The fixture contains a NOT_APPLICABLE missing_reason somewhere.
    assert "NOT_APPLICABLE" in {
        rec.missing_reason for rec in by_id.values()
    }


def test_missing_reason_absent_in_sample_1_defaults_to_none(uow_factory, clock):
    submission = _submission("sample_1.json")
    result = _engine().run(
        evidence=submission.evidence,
        requirements=[_gst_requirement()],
        submission_id=submission.submission_id,
    )
    persist_engine_result(submission, result, uow=uow_factory(), clock=clock)
    with uow_factory() as uow:
        records = uow.repos.evidence.list_by_bidder(submission.bidder_id)
    assert records, "expected evidence records to be persisted"
    assert all(rec.missing_reason is None for rec in records)


def test_financial_evidence_survives(uow_factory, persisted):
    submission, _ = persisted
    with uow_factory() as uow:
        records = uow.repos.evidence.list_by_bidder(submission.bidder_id)
    fields = {rec.field_name: rec for rec in records}
    # List-valued annual_turnovers survive intact.
    turnovers = fields["annual_turnovers"]
    assert {row["financial_year"]: row["turnover"] for row in turnovers.value} == {
        "2022-23": 12.5,
        "2023-24": 15.8,
        "2024-25": 18.2,
    }
    # Undated scalar balance-sheet values persist as-is (no year fabricated).
    assert fields["net_worth"].value == 26.5
    assert fields["profit_after_tax"].value == 3.4

    assert fields["net_worth"].value == 26.5
    assert fields["profit_after_tax"].value == 3.4
    assert fields["current_assets"].value == 20.0
    assert fields["audited_status"].value is True


def test_compliance_result_contains_submission_id(uow_factory, persisted):
    submission, result = persisted
    with uow_factory() as uow:
        records = uow.repos.compliance_results.list_by_bidder(submission.bidder_id)
        direct = uow.repos.compliance_results.get(
            submission.submission_id, submission.bidder_id, "req-gst-1"
        )
    assert len(records) == len(result.compliance_results) == 1
    rec = records[0]
    assert rec.submission_id == submission.submission_id
    assert rec.bidder_id == submission.bidder_id
    assert rec.requirement_id == "req-gst-1"
    assert rec.status == str(result.compliance_results[0].status)
    assert rec.reason == result.compliance_results[0].reason
    assert rec.rule_id == "GST_REGISTRATION_001"
    assert direct is not None
    assert direct.result_id == rec.result_id
    # result_id is deterministic for (submission, bidder, requirement).
    from infrastructure.persistence.engine_persistence import _result_id

    assert rec.result_id == _result_id(
        submission.submission_id, submission.bidder_id, "req-gst-1"
    )


def test_verification_records_persisted(uow_factory, persisted):
    submission, result = persisted
    with uow_factory() as uow:
        records = uow.repos.verifications.list_by_bidder(submission.bidder_id)
    assert len(records) == len(result.verification_records)
    assert records, "expected at least one verification record"
    by_id = {v.verification_id: v for v in result.verification_records}
    for rec in records:
        src = by_id[rec.verification_id]
        assert rec.bidder_id == submission.bidder_id
        assert rec.status == str(src.status)
        assert rec.source == src.source
        assert rec.capability == src.capability
        # Evidence/document linkage survives the bridge.
        assert rec.evidence_id == src.evidence_id
        assert rec.document_id == src.document_id


def test_persistence_is_atomic_within_unit_of_work(uow_factory, clock, monkeypatch):
    submission = _submission()
    result = _engine().run(
        evidence=submission.evidence,
        requirements=[_gst_requirement()],
        submission_id=submission.submission_id,
    )
    store = _Store()

    def _factory():
        return InMemoryUnitOfWork(store)

    uow = _factory()

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated mid-transaction failure")

    monkeypatch.setattr(uow.repos.verifications, "save", _boom)
    with pytest.raises(RuntimeError, match="simulated mid-transaction failure"):
        persist_engine_result(submission, result, uow=uow, clock=clock)

    # Nothing survived the rolled back transaction.
    with _factory() as fresh:
        assert fresh.repos.submissions.get(submission.submission_id) is None
        assert fresh.repos.documents.list_by_bidder(submission.bidder_id) == []
        assert fresh.repos.evidence.list_by_bidder(submission.bidder_id) == []
        assert fresh.repos.compliance_results.list_by_bidder(
            submission.bidder_id
        ) == []


def test_repeated_persist_is_idempotent(uow_factory, clock):
    submission = _submission()
    engine = _engine()
    result = engine.run(
        evidence=submission.evidence,
        requirements=[_gst_requirement()],
        submission_id=submission.submission_id,
    )
    persist_engine_result(submission, result, uow=uow_factory(), clock=clock)
    persist_engine_result(submission, result, uow=uow_factory(), clock=clock)
    with uow_factory() as uow:
        assert len(
            uow.repos.documents.list_by_submission(submission.submission_id)
        ) == len(submission.documents)
        assert len(uow.repos.evidence.list_by_bidder(submission.bidder_id)) == len(
            submission.evidence
        )
        assert len(
            uow.repos.verifications.list_by_bidder(submission.bidder_id)
        ) == len(result.verification_records)
        assert len(
            uow.repos.compliance_results.list_by_bidder(submission.bidder_id)
        ) == 1


def test_same_requirement_across_submissions_is_distinct(uow_factory, clock):
    payload = _load("sample.json")
    engine = _engine()
    for sub_id in ("sub_compliant_001", "sub_compliant_002"):
        submission = normalize_submission({**payload, "submission_id": sub_id})
        result = engine.run(
            evidence=submission.evidence,
            requirements=[_gst_requirement()],
            submission_id=submission.submission_id,
        )
        persist_engine_result(submission, result, uow=uow_factory(), clock=clock)
    with uow_factory() as uow:
        records = uow.repos.compliance_results.list_by_bidder("bidder_acme_01")
    assert {r.submission_id for r in records} == {
        "sub_compliant_001",
        "sub_compliant_002",
    }


def test_missing_reason_null_maps_to_none(uow_factory, persisted):
    submission, _ = persisted
    with uow_factory() as uow:
        records = uow.repos.evidence.list_by_bidder(submission.bidder_id)
    # 'gstin' is present in the fixture with missing_reason: null.
    gstin = next(r for r in records if r.field_name == "gstin")
    assert gstin.value == "27AAACI1234F1Z5"
    assert gstin.missing_reason is None

