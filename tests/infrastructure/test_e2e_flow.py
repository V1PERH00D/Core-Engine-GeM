"""Representative end-to-end persistence flow (no process-memory state)."""

from compliance_engine.flags import FlagSeverity

from ai_verification.explanations import (
    DeterministicFallbackExplanationGenerator,
    ExplanationRequest,
)
from ai_verification.models.contracts import VerificationFinding

from infrastructure.artifacts import InMemoryArtifactStore
from infrastructure.flags import materialize_flag_snapshot
from infrastructure.jobs.durable import DurableJobQueue
from infrastructure.jobs.queue import InMemoryJobQueue
from infrastructure.persistence.records import (
    ComplianceResultRecord,
    EvidenceRecord,
    ExplanationRecord,
    FindingRecord,
    FlagSnapshotRecord,
    FlagStateRecord,
    VerificationRecord,
)
from infrastructure.processing import IngestedDocument, ProcessingCoordinator


def test_end_to_end_flow(uow_factory, clock):
    artifact_store = InMemoryArtifactStore(clock=clock)
    queue = InMemoryJobQueue(clock=clock)
    durable_queue = DurableJobQueue(queue, uow_factory)
    coordinator = ProcessingCoordinator(
        uow_factory, durable_queue, artifact_store=artifact_store, clock=clock
    )

    # 1. Persist submission + document + evidence.
    coordinator.ingest_submission(
        "bidder-1",
        "sub-1",
        [IngestedDocument(document_id="doc-1", document_type="GST",
                          content=b"%PDF-fake", metadata={"origin": "ingestion"})],
        correlation_id="trace-1",
    )
    with uow_factory() as uow:
        uow.repos.evidence.add(
            EvidenceRecord(evidence_id="ev-1", bidder_id="bidder-1",
                           document_id="doc-1", field_name="gstin",
                           value="29ABCDE1234F1Z5", created_at=clock())
        )

    # 2. Queued processing job (mirrored durably).
    coordinator.enqueue_stage_job(
        "sub-1", "VERIFY", bidder_id="bidder-1", job_id="job-1",
        payload={"evidence_ids": ["ev-1"]}, correlation_id="trace-1",
    )
    claimed = durable_queue.claim("worker-1")
    assert claimed is not None and claimed.job_id == "job-1"

    # 3-5. Engine run -> verification + compliance + finding.
    with uow_factory() as uow:
        uow.repos.verifications.save(
            VerificationRecord(
                verification_id="v-1", bidder_id="bidder-1", capability="GST",
                source="GSTN_MOCK", queried_identifier="29ABCDE1234F1Z5",
                status="NOT_FOUND", retrieved_at=clock(), created_at=clock(),
                correlation_id="trace-1", evidence_id="ev-1", document_id="doc-1",
            )
        )
        uow.repos.compliance_results.save(
            ComplianceResultRecord(
                result_id="r-1", bidder_id="bidder-1", requirement_id="req-1",
                capability="GST", status="FAIL", reason="GSTIN not found",
                evidence_refs=["ev-1"], verification_refs=["v-1"],
                created_at=clock(), updated_at=clock(),
            )
        )
        uow.repos.findings.save(
            FindingRecord(
                finding_id="f-1", bidder_id="bidder-1",
                finding_type="VERIFICATION", flag_id="GSTIN_MISSING",
                payload={"explanation": "GSTIN not found on registry"},
                evidence_refs=["ev-1"], verification_refs=["v-1"],
                created_at=clock(),
            )
        )
        # 6. Boolean flag state (no severity).
        uow.repos.flags.save_state(
            FlagStateRecord(
                bidder_id="bidder-1", flag_id="GSTIN_MISSING", is_set=True,
                finding_refs=["f-1"], evidence_refs=["ev-1"],
                verification_refs=["v-1"], source="COMPLIANCE",
                correlation_id="trace-1", updated_at=clock(),
            )
        )
# 7. Grounded explanation.
    finding = VerificationFinding(
        finding_id="f-1", bidder_id="bidder-1", flag_id="GSTIN_MISSING",
        severity=FlagSeverity.HIGH, confidence=0.95,
        explanation="GSTIN not found on registry.", evidence_refs=["ev-1"],
    )
    explanation = DeterministicFallbackExplanationGenerator().explain(
        ExplanationRequest(bidder_id="bidder-1", flag_id="GSTIN_MISSING",
                           flag_active=True, finding=finding,
                           evidence_refs=["ev-1"], verification_refs=["v-1"])
    )
    with uow_factory() as uow:
        uow.repos.explanations.save(
            ExplanationRecord(
                explanation_id=explanation.explanation_id,
                bidder_id=explanation.bidder_id,
                flag_id=explanation.flag_id,
                flag_active=explanation.flag_active,
                finding_refs=explanation.finding_refs,
                concise_text=explanation.concise_text,
                detailed_text=explanation.detailed_text,
                grounding=[g.model_dump(mode="json") for g in explanation.grounding],
                generation=explanation.generation.model_dump(mode="json"),
                created_at=clock(),
            )
        )

    # 8. Materialize + persist the final flag snapshot.
    with uow_factory() as uow:
        states = uow.repos.flags.list_states("bidder-1")
    snapshot = materialize_flag_snapshot("bidder-1", states, clock=clock)
    with uow_factory() as uow:
        uow.repos.flags.save_snapshot(
            FlagSnapshotRecord(
                snapshot_id=snapshot.snapshot_id,
                bidder_id=snapshot.bidder_id,
                snapshot_version=str(snapshot.snapshot_version),
                flags=snapshot.flags,
                provenance=snapshot.provenance,
                content_hash=snapshot.content_hash,
                correlation_id="trace-1",
                created_at=snapshot.created_at,
            )
        )

    # 9. Downstream contract shape is exact and boolean-only.
    assert snapshot.downstream_payload() == {
        "bidder_id": "bidder-1",
        "flags": {"GSTIN_MISSING": True},
    }

    # 10. Audit lineage reconstructs the chain by real IDs.
    from infrastructure.audit import build_flag_lineage

    with uow_factory() as uow:
        lineage = build_flag_lineage(uow.repos, "bidder-1", "GSTIN_MISSING")
    assert lineage.flag_state.is_set is True
    assert [f.finding_id for f in lineage.findings] == ["f-1"]
    assert [e.evidence_id for e in lineage.evidence] == ["ev-1"]
    assert [v.verification_id for v in lineage.verifications] == ["v-1"]
    assert [d.document_id for d in lineage.documents] == ["doc-1"]
    assert [s.submission_id for s in lineage.submissions] == ["sub-1"]
    assert len(lineage.explanations) == 1


def test_flag_snapshot_is_reproducible_across_runs(uow_factory, clock):
    artifact_store = InMemoryArtifactStore(clock=clock)
    queue = InMemoryJobQueue(clock=clock)
    coordinator = ProcessingCoordinator(
        uow_factory, queue, artifact_store=artifact_store, clock=clock
    )
    coordinator.register_bidder("bidder-1")
    with uow_factory() as uow:
        uow.repos.flags.save_state(
            FlagStateRecord(bidder_id="bidder-1", flag_id="GSTIN_MISSING",
                            is_set=True, updated_at=clock())
        )
        states = uow.repos.flags.list_states("bidder-1")
    snap_a = materialize_flag_snapshot("bidder-1", states, clock=clock)
    snap_b = materialize_flag_snapshot("bidder-1", states, clock=lambda: 999.0)
    assert snap_a.snapshot_id == snap_b.snapshot_id
    assert snap_a.downstream_payload() == snap_b.downstream_payload()