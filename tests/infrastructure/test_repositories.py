"""Repository persistence-contract tests (in-memory backend)."""

import pytest

from infrastructure.persistence.errors import (
    DuplicateRecordError,
    MissingReferenceError,
)
from infrastructure.persistence.records import (
    BidderRecord,
    ComplianceResultRecord,
    DocumentRecord,
    EvidenceRecord,
    ExplanationRecord,
    FindingRecord,
    FlagSnapshotRecord,
    FlagStateRecord,
    OutboxEventRecord,
    SubmissionRecord,
    VerificationRecord,
)


def _bidder(bidder_id="b1", now=1.0):
    return BidderRecord(bidder_id=bidder_id, created_at=now, updated_at=now)


def _submission(submission_id="s1", bidder_id="b1", stage="INGESTED", now=1.0):
    return SubmissionRecord(
        submission_id=submission_id,
        bidder_id=bidder_id,
        stage=stage,
        created_at=now,
        updated_at=now,
    )


def _document(document_id="d1", bidder_id="b1", submission_id="s1", now=1.0):
    return DocumentRecord(
        document_id=document_id,
        bidder_id=bidder_id,
        submission_id=submission_id,
        document_type="GST",
        created_at=now,
        metadata={"k": "v"},
    )


def test_bidder_crud(uow):
    uow.repos.bidders.add(_bidder())
    got = uow.repos.bidders.get("b1")
    assert got.bidder_id == "b1"
    assert uow.repos.bidders.get("missing") is None


def test_bidder_duplicate_raises(uow):
    uow.repos.bidders.add(_bidder())
    with pytest.raises(DuplicateRecordError):
        uow.repos.bidders.add(_bidder())


def test_submission_requires_bidder(uow):
    with pytest.raises(MissingReferenceError):
        uow.repos.submissions.add(_submission())


def test_submission_duplicate_raises(uow):
    uow.repos.bidders.add(_bidder())
    uow.repos.submissions.add(_submission())
    with pytest.raises(DuplicateRecordError):
        uow.repos.submissions.add(_submission())


def test_document_requires_submission(uow):
    uow.repos.bidders.add(_bidder())
    with pytest.raises(MissingReferenceError):
        uow.repos.documents.add(_document())


def test_document_crud_and_listing(uow):
    uow.repos.bidders.add(_bidder())
    uow.repos.submissions.add(_submission())
    uow.repos.documents.add(_document())
    assert uow.repos.documents.list_by_submission("s1")[0].document_id == "d1"
    assert uow.repos.documents.list_by_bidder("b1")[0].document_id == "d1"


def test_evidence_requires_document(uow):
    uow.repos.bidders.add(_bidder())
    with pytest.raises(MissingReferenceError):
        uow.repos.evidence.add(
            EvidenceRecord(
                evidence_id="e1", bidder_id="b1", document_id="d1",
                field_name="gstin", created_at=1.0,
            )
        )


def test_evidence_add_and_list(uow):
    uow.repos.bidders.add(_bidder())
    uow.repos.submissions.add(_submission())
    uow.repos.documents.add(_document())
    ev = EvidenceRecord(
        evidence_id="e1", bidder_id="b1", document_id="d1",
        field_name="gstin", value="29A", confidence=0.9, created_at=1.0,
    )
    uow.repos.evidence.add(ev)
    assert uow.repos.evidence.get("e1").value == "29A"
    assert uow.repos.evidence.list_by_bidder("b1")[0].field_name == "gstin"
    assert uow.repos.evidence.list_by_document("d1")[0].field_name == "gstin"


def test_evidence_duplicate_raises(uow):
    uow.repos.bidders.add(_bidder())
    uow.repos.submissions.add(_submission())
    uow.repos.documents.add(_document())
    ev = EvidenceRecord(
        evidence_id="e1", bidder_id="b1", document_id="d1",
        field_name="gstin", created_at=1.0,
    )
    uow.repos.evidence.add(ev)
    with pytest.raises(DuplicateRecordError):
        uow.repos.evidence.add(ev)


def test_verification_upsert_idempotent(uow):
    uow.repos.bidders.add(_bidder())
    v = VerificationRecord(
        verification_id="v1", bidder_id="b1", capability="GST",
        source="GSTN_MOCK", status="VERIFIED", retrieved_at=1.0, created_at=1.0,
    )
    uow.repos.verifications.save(v)
    v2 = v.model_copy(update={"status": "NOT_FOUND"})
    uow.repos.verifications.save(v2)
    assert uow.repos.verifications.get("v1").status == "NOT_FOUND"
    assert len(uow.repos.verifications.list_by_bidder("b1")) == 1


def test_verification_evidence_fk_optional(uow):
    uow.repos.bidders.add(_bidder())
    v = VerificationRecord(
        verification_id="v1", bidder_id="b1", capability="GST",
        source="GSTN_MOCK", status="VERIFIED", retrieved_at=1.0,
        created_at=1.0, evidence_id="missing",
    )
    with pytest.raises(MissingReferenceError):
        uow.repos.verifications.save(v)


def test_compliance_result_upsert_by_requirement(uow):
    uow.repos.bidders.add(_bidder())
    r = ComplianceResultRecord(
        result_id="r1", bidder_id="b1", requirement_id="req-1",
        capability="GST", status="PASS", reason="ok", created_at=1.0, updated_at=1.0,
    )
    uow.repos.compliance_results.save(r)
    r2 = r.model_copy(update={"status": "FAIL", "reason": "changed"})
    uow.repos.compliance_results.save(r2)
    assert uow.repos.compliance_results.get("b1", "req-1").status == "FAIL"
    uow.repos.compliance_results.save(
        r.model_copy(update={"requirement_id": "req-2", "result_id": "r2"})
    )
    assert len(uow.repos.compliance_results.list_by_bidder("b1")) == 2


def test_finding_upsert_idempotent(uow):
    uow.repos.bidders.add(_bidder())
    f = FindingRecord(
        finding_id="f1", bidder_id="b1", finding_type="VERIFICATION",
        flag_id="ADDRESS_MISMATCH", payload={"x": 1}, created_at=1.0,
    )
    uow.repos.findings.save(f)
    uow.repos.findings.save(f.model_copy(update={"payload": {"x": 2}}))
    assert uow.repos.findings.get("f1").payload == {"x": 2}
    assert len(uow.repos.findings.list_by_flag("b1", "ADDRESS_MISMATCH")) == 1


def test_explanation_save_and_list(uow):
    uow.repos.bidders.add(_bidder())
    uow.repos.findings.save(
        FindingRecord(
            finding_id="f1", bidder_id="b1", finding_type="VERIFICATION",
            flag_id="ADDRESS_MISMATCH", created_at=1.0,
        )
    )
    e = ExplanationRecord(
        explanation_id="x1", bidder_id="b1", flag_id="ADDRESS_MISMATCH",
        flag_active=True, finding_refs=["f1"], concise_text="why",
        created_at=1.0,
    )
    uow.repos.explanations.save(e)
    assert uow.repos.explanations.get("x1").concise_text == "why"
    assert len(uow.repos.explanations.list_by_flag("b1", "ADDRESS_MISMATCH")) == 1


def test_explanation_unknown_finding_rejected(uow):
    uow.repos.bidders.add(_bidder())
    e = ExplanationRecord(
        explanation_id="x1", bidder_id="b1", flag_id="ADDRESS_MISMATCH",
        flag_active=True, finding_refs=["missing"], concise_text="why",
        created_at=1.0,
    )
    with pytest.raises(MissingReferenceError):
        uow.repos.explanations.save(e)


def test_flag_state_upsert(uow):
    uow.repos.bidders.add(_bidder())
    s = FlagStateRecord(
        bidder_id="b1", flag_id="ADDRESS_MISMATCH", is_set=True,
        updated_at=1.0,
    )
    uow.repos.flags.save_state(s)
    uow.repos.flags.save_state(s.model_copy(update={"is_set": False}))
    assert uow.repos.flags.get_state("b1", "ADDRESS_MISMATCH").is_set is False


def test_flag_snapshot_save_and_retrieve(uow):
    uow.repos.bidders.add(_bidder())
    snap = FlagSnapshotRecord(
        snapshot_id="snap1", bidder_id="b1", snapshot_version="1",
        flags={"ADDRESS_MISMATCH": True}, provenance={}, content_hash="abc",
        created_at=1.0,
    )
    uow.repos.flags.save_snapshot(snap)
    assert uow.repos.flags.get_snapshot("snap1").flags["ADDRESS_MISMATCH"] is True
    assert len(uow.repos.flags.list_snapshots("b1")) == 1


def test_outbox_append_only(uow):
    e = OutboxEventRecord(
        event_id="o1", aggregate_type="SUBMISSION", aggregate_id="s1",
        event_type="SUBMISSION_INGESTED", created_at=1.0,
    )
    uow.repos.outbox.add(e)
    with pytest.raises(DuplicateRecordError):
        uow.repos.outbox.add(e)


def test_audit_append_and_list(uow):
    from infrastructure.audit import audit_event

    uow.repos.audit.add(
        audit_event(
            aggregate_type="SUBMISSION", aggregate_id="s1",
            event_type="SUBMISSION_INGESTED", created_at=1.0, correlation_id="c1",
        )
    )
    assert len(uow.repos.audit.list_for("SUBMISSION", "s1")) == 1
    assert len(uow.repos.audit.list_by_correlation("c1")) == 1


def test_job_repository_mirrors_idempotency(uow):
    from infrastructure.persistence.records import ProcessingJobRecord

    uow.repos.jobs.save(
        ProcessingJobRecord(
            job_id="j1", idempotency_key="k1", job_type="VERIFY",
            state="PENDING", created_at=1.0, updated_at=1.0,
        )
    )
    j2 = ProcessingJobRecord(
        job_id="j2", idempotency_key="k1", job_type="VERIFY",
        state="PENDING", created_at=1.0, updated_at=1.0,
    )
    uow.repos.jobs.save(j2)
    assert uow.repos.jobs.find_by_idempotency_key("k1").job_id == "j2"
