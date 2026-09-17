"""Async processing path: queue -> claim -> process -> persisted result.

Runs against the in-memory queue, which honours the same lease/retry
contract as the Redis adapter. No Redis or PostgreSQL is required.
"""

from __future__ import annotations

import pytest

from compliance_engine.models import Capability
from compliance_engine.verification.base import MockGSTProvider

from application.demo import demo_providers
from application.worker import SubmissionWorker
from infrastructure.errors import FailureKind
from infrastructure.jobs.models import JobState
from infrastructure.pipeline import ProcessingStage
from tests.application.conftest import gst_submission, make_service


def test_enqueue_claim_process_acknowledge_complete(store, clock, queue):
    service = make_service(store, clock, queue=queue)
    submission = gst_submission(
        "bidder-async", gstin=MockGSTProvider.GSTIN_VERIFIED
    )

    job = service.enqueue_submission(submission)
    assert job.state is JobState.PENDING

    worker = SubmissionWorker(service, queue=queue, worker_id="worker-test")
    outcome = worker.run_once()
    clock.advance(1.0)
    assert outcome["state"] == JobState.SUCCEEDED.value
    assert outcome["bidder_id"] == "bidder-async"

    persisted = queue.get(job.job_id)
    assert persisted.state is JobState.SUCCEEDED

    # The durable result is available after the async run.
    result = service.reconstruct_result("bidder-async")
    assert result is not None
    assert result.processing.stage == ProcessingStage.COMPLETE.value
    assert all(
        isinstance(v, bool) for v in result.compliance.flags.values()
    )


def test_worker_is_idempotent_for_duplicate_enqueue(store, clock, queue):
    service = make_service(store, clock, queue=queue)
    submission = gst_submission(
        "bidder-dup", gstin=MockGSTProvider.GSTIN_VERIFIED
    )
    job_first = service.enqueue_submission(submission)
    job_second = service.enqueue_submission(submission)
    assert job_first.job_id == job_second.job_id


def _flaky_service(store, clock, queue):
    """Service whose GST provider fails once with PROVIDER_UNAVAILABLE."""

    class _Flaky:
        def __init__(self) -> None:
            self.calls = 0
            self.healthy = MockGSTProvider()

        def verify(self, bidder_id, identifier, **kwargs):
            self.calls += 1
            if self.calls == 1:
                from infrastructure.errors import ProviderUnavailableError

                raise ProviderUnavailableError("GST demo source timed out.")
            return self.healthy.verify(bidder_id, identifier, **kwargs)

    flaky = _Flaky()
    providers = demo_providers()
    providers[Capability.GST] = flaky
    return make_service(store, clock, providers=flaky and providers, queue=queue), flaky


def test_retryable_failure_is_retried_to_completion(store, clock, queue):
    service, flaky = _flaky_service(store, clock, queue)
    submission = gst_submission(
        "bidder-retry", gstin=MockGSTProvider.GSTIN_VERIFIED
    )
    job = service.enqueue_submission(submission)

    worker = SubmissionWorker(service, queue=queue, worker_id="worker-test")

    outcome = worker.run_once()
    assert outcome["state"] == JobState.RETRYABLE.value
    assert outcome["error_kind"] == FailureKind.PROVIDER_UNAVAILABLE.value

    retried = queue.get(job.job_id)
    assert retried.state is JobState.RETRYABLE

    # The submission was marked FAILED with the classified kind.
    from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork

    with InMemoryUnitOfWork(store) as uow:
        record = uow.repos.submissions.get(submission.submission_id)
    assert record.stage == ProcessingStage.FAILED.value
    assert record.last_error_kind == FailureKind.PROVIDER_UNAVAILABLE.value

    # Advance past the deterministic backoff and retry: full recovery.
    clock.advance(2.0)
    outcome = worker.run_once()
    assert outcome["state"] == JobState.SUCCEEDED.value

    result = service.reconstruct_result("bidder-retry")
    assert result is not None
    assert result.processing.stage == ProcessingStage.COMPLETE.value
    assert all(isinstance(v, bool) for v in result.compliance.flags.values())


def test_programming_error_is_never_retried(store, clock, queue):
    class _Broken:
        def verify(self, bidder_id, identifier, **kwargs):
            raise TypeError("intentional programming error in test provider")

    providers = demo_providers()
    providers[Capability.GST] = _Broken()
    service = make_service(store, clock, providers=providers, queue=queue)
    submission = gst_submission(
        "bidder-boom", gstin=MockGSTProvider.GSTIN_VERIFIED
    )
    job = service.enqueue_submission(submission)
    worker = SubmissionWorker(service, queue=queue, worker_id="worker-test")

    with pytest.raises(TypeError):
        worker.run_once()

    failed = queue.get(job.job_id)
    assert failed.state is JobState.FAILED
    assert failed.last_error_kind == FailureKind.PROGRAMMING_ERROR.value
    # No further claim must deliver this job again.
    assert worker.run_once() is None


def test_unknown_job_type_is_failed_without_retry(store, clock, queue):
    from infrastructure.jobs.models import Job
    from infrastructure.persistence.records import to_job_record
    from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork

    job = Job(
        job_id="job:unknown",
        job_type="NOT_A_COMPLIANCE_JOB",
        created_at=clock(),
        updated_at=clock(),
    )
    with InMemoryUnitOfWork(store) as uow:
        uow.repos.jobs.save(to_job_record(job))
    queue.enqueue(job)

    service = make_service(store, clock, queue=queue)
    worker = SubmissionWorker(service, queue=queue, worker_id="worker-test")
    outcome = worker.run_once()
    assert outcome["state"] == JobState.FAILED.value
    assert outcome["retryable"] is False
