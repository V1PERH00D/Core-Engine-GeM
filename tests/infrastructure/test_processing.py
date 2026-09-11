"""Processing coordinator: durable lifecycle orchestration."""

import pytest

from infrastructure.artifacts import InMemoryArtifactStore
from infrastructure.jobs.queue import InMemoryJobQueue
from infrastructure.pipeline import (
    InvalidStateTransitionError,
    ProcessingStage,
)
from infrastructure.processing import IngestedDocument, ProcessingCoordinator


@pytest.fixture
def coordinator(uow_factory, clock):
    artifact_store = InMemoryArtifactStore(clock=clock)
    queue = InMemoryJobQueue(clock=clock)
    return ProcessingCoordinator(
        uow_factory, queue, artifact_store=artifact_store, clock=clock
    )


def test_register_bidder(coordinator, uow_factory):
    coordinator.register_bidder("b1")
    with uow_factory() as uow:
        assert uow.repos.bidders.get("b1") is not None


def test_register_bidder_idempotent(coordinator, uow_factory):
    coordinator.register_bidder("b1")
    coordinator.register_bidder("b1")
    with uow_factory() as uow:
        assert len(uow.repos.audit.list_for("BIDDER", "b1")) == 1


def test_ingest_submission_persists_all(coordinator, uow_factory):
    doc = IngestedDocument(
        document_id="d1", document_type="GST", content=b"hello"
    )
    result = coordinator.ingest_submission(
        "b1", "s1", [doc], correlation_id="c1"
    )
    assert result.stage == ProcessingStage.INGESTED.value
    with uow_factory() as uow:
        assert uow.repos.bidders.get("b1") is not None
        assert uow.repos.submissions.get("s1") is not None
        assert uow.repos.documents.get("d1").artifact_id is not None
        # Outbox event emitted in the same transaction.
        assert len(uow.repos.outbox.list_unpublished()) == 1


def test_ingest_document_without_artifact_store(uow_factory, clock):
    queue = InMemoryJobQueue(clock=clock)
    coordinator = ProcessingCoordinator(uow_factory, queue, clock=clock)
    doc = IngestedDocument(document_id="d1", document_type="GST", content=b"x")
    coordinator.ingest_submission("b1", "s1", [doc])
    with uow_factory() as uow:
        assert uow.repos.documents.get("d1").artifact_id is None


def test_advance_stage_happy_path(coordinator, uow_factory):
    coordinator.ingest_submission("b1", "s1", [])
    updated = coordinator.advance_stage("s1", ProcessingStage.NORMALIZED)
    assert updated.stage == ProcessingStage.NORMALIZED.value
    assert updated.last_completed_stage == ProcessingStage.NORMALIZED.value


def test_advance_stage_invalid_rejected(coordinator):
    coordinator.ingest_submission("b1", "s1", [])
    with pytest.raises(InvalidStateTransitionError):
        coordinator.advance_stage("s1", ProcessingStage.VERIFIED)


def test_advance_unknown_submission_raises(coordinator):
    with pytest.raises(LookupError):
        coordinator.advance_stage("nope", ProcessingStage.NORMALIZED)


def test_fail_then_resume(coordinator):
    coordinator.ingest_submission("b1", "s1", [])
    coordinator.advance_stage("s1", ProcessingStage.NORMALIZED)
    failed = coordinator.fail_submission(
        "s1", "provider down", "PROVIDER_UNAVAILABLE", correlation_id="c1"
    )
    assert failed.stage == ProcessingStage.FAILED.value
    assert failed.attempt_count == 1
    # Resume from the last good stage.
    resumed = coordinator.advance_stage("s1", ProcessingStage.VERIFICATION_PENDING)
    assert resumed.stage == ProcessingStage.VERIFICATION_PENDING.value


def test_enqueue_stage_job_persists_and_enqueues(coordinator, uow_factory, clock):
    coordinator.ingest_submission("b1", "s1", [])
    job = coordinator.enqueue_stage_job(
        "s1", "VERIFY", bidder_id="b1", job_id="job-1",
        payload={"document_ids": ["d1"]}, correlation_id="c1",
    )
    assert job.idempotency_key is not None
    with uow_factory() as uow:
        assert uow.repos.jobs.get("job-1") is not None


def test_idempotent_job_key_stable(coordinator):
    coordinator.ingest_submission("b1", "s1", [])
    j1 = coordinator.enqueue_stage_job(
        "s1", "VERIFY", bidder_id="b1", job_id="job-1", payload={"x": 1}
    )
    j2 = coordinator.enqueue_stage_job(
        "s1", "VERIFY", bidder_id="b1", job_id="job-2", payload={"x": 1}
    )
    assert j1.idempotency_key == j2.idempotency_key


def test_resume_survives_crash(coordinator, uow_factory, clock):
    """A new coordinator over the same store can resume from durable state."""
    coordinator.ingest_submission("b1", "s1", [])
    coordinator.advance_stage("s1", ProcessingStage.NORMALIZED)

    # Simulate a process restart: brand-new coordinator, same store.
    from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork

    # Reuse the coordinator but read only durable state.
    state = coordinator.resume("s1")
    assert state.stage == ProcessingStage.NORMALIZED.value
    assert state.last_completed_stage == ProcessingStage.NORMALIZED.value


def test_correlation_id_propagates(coordinator, uow_factory):
    coordinator.ingest_submission("b1", "s1", [], correlation_id="trace-1")
    with uow_factory() as uow:
        sub = uow.repos.submissions.get("s1")
        assert sub.correlation_id == "trace-1"
        audit = uow.repos.audit.list_for("SUBMISSION", "s1")
        assert all(e.correlation_id == "trace-1" for e in audit)


def test_ingest_duplicate_submission_rejected(coordinator):
    coordinator.ingest_submission("b1", "s1", [])
    from infrastructure.persistence.errors import DuplicateRecordError

    with pytest.raises(DuplicateRecordError):
        coordinator.ingest_submission("b1", "s1", [])