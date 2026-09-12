"""Audit lineage reconstruction from real IDs."""

from infrastructure.audit import build_flag_lineage
from infrastructure.persistence.records import (
    BidderRecord,
    ComplianceResultRecord,
    DocumentRecord,
    EvidenceRecord,
    ExplanationRecord,
    FindingRecord,
    FlagStateRecord,
    SubmissionRecord,
    VerificationRecord,
)


def _seed(uow):
    now = 1.0
    uow.repos.bidders.add(BidderRecord(bidder_id="b1", created_at=now, updated_at=now))
    uow.repos.submissions.add(
        SubmissionRecord(submission_id="s1", bidder_id="b1", stage="VERIFIED",
                         created_at=now, updated_at=now)
    )
    uow.repos.documents.add(
        DocumentRecord(document_id="d1", submission_id="s1", bidder_id="b1",
                       document_type="GST", created_at=now)
    )
    uow.repos.evidence.add(
        EvidenceRecord(evidence_id="e1", bidder_id="b1", document_id="d1",
                       field_name="gstin", created_at=now)
    )
    uow.repos.verifications.save(
        VerificationRecord(verification_id="v1", bidder_id="b1", capability="GST",
                           source="GSTN_MOCK", status="VERIFIED",
                           retrieved_at=now, created_at=now, evidence_id="e1",
                           document_id="d1")
    )
    uow.repos.compliance_results.save(
        ComplianceResultRecord(result_id="r1", bidder_id="b1", requirement_id="req1",
                               capability="GST", status="FAIL", reason="missing",
                               evidence_refs=["e1"], verification_refs=["v1"],
                               created_at=now, updated_at=now)
    )
    uow.repos.findings.save(
        FindingRecord(finding_id="f1", bidder_id="b1", finding_type="VERIFICATION",
                      flag_id="GSTIN_MISSING", evidence_refs=["e1"],
                      verification_refs=["v1"], created_at=now)
    )
    uow.repos.flags.save_state(
        FlagStateRecord(bidder_id="b1", flag_id="GSTIN_MISSING", is_set=True,
                        finding_refs=["f1"], evidence_refs=["e1"],
                        verification_refs=["v1"], updated_at=now)
    )
    uow.repos.explanations.save(
        ExplanationRecord(explanation_id="x1", bidder_id="b1", flag_id="GSTIN_MISSING",
                          flag_active=True, finding_refs=["f1"], concise_text="why",
                          created_at=now)
    )


def test_lineage_links_every_stage(uow):
    _seed(uow)
    lineage = build_flag_lineage(uow.repos, "b1", "GSTIN_MISSING")
    assert lineage.flag_state is not None
    assert len(lineage.findings) == 1
    assert len(lineage.evidence) == 1
    assert len(lineage.verifications) == 1
    assert len(lineage.documents) == 1
    assert len(lineage.submissions) == 1
    assert len(lineage.explanations) == 1
    assert len(lineage.compliance_results) == 1


def test_lineage_uses_real_ids_only(uow):
    _seed(uow)
    lineage = build_flag_lineage(uow.repos, "b1", "GSTIN_MISSING")
    # Every reference resolves to a persisted record.
    assert lineage.documents[0].document_id == "d1"
    assert lineage.evidence[0].evidence_id == "e1"
    assert lineage.verifications[0].verification_id == "v1"
    assert lineage.findings[0].finding_id == "f1"
    assert lineage.submissions[0].submission_id == "s1"


def test_lineage_empty_for_missing_flag(uow):
    _seed(uow)
    lineage = build_flag_lineage(uow.repos, "b1", "ADDRESS_MISMATCH")
    assert lineage.flag_state is None
    assert lineage.findings == []


def test_lineage_no_fabricated_references(uow):
    _seed(uow)
    lineage = build_flag_lineage(uow.repos, "b1", "GSTIN_MISSING")
    ids = {f.finding_id for f in lineage.findings}
    # finding references that point at nothing are not fabricated.
    assert "missing" not in ids