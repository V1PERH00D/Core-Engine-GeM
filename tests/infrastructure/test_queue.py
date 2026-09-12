"""Queue contract tests (in-memory implementation)."""

import pytest

from infrastructure.jobs.models import JobState
from infrastructure.jobs.queue import (
    DuplicateJobError,
    JobConflictError,
    JobNotFoundError,
)

from tests.infrastructure.conftest import ManualClock, make_job


def test_enqueue_and_get(queue, clock):
    job = queue.enqueue(make_job(clock, job_id="a"))
    assert job.state is JobState.PENDING
    assert queue.get("a").job_id == "a"


def test_claim_sets_running_and_lease(queue, clock):
    queue.enqueue(make_job(clock, job_id="a"))
    claimed = queue.claim("w1", lease_seconds=30)
    assert claimed.state is JobState.RUNNING
    assert claimed.leased_by == "w1"
    assert claimed.lease_expires_at == clock() + 30
    assert claimed.attempt_count == 1


def test_claim_empty_returns_none(queue):
    assert queue.claim("w1") is None


def test_second_worker_cannot_claim_same_job(queue, clock):
    queue.enqueue(make_job(clock, job_id="a"))
    queue.claim("w1")
    assert queue.claim("w2") is None


def test_enqueue_duplicate_id_raises(queue, clock):
    queue.enqueue(make_job(clock, job_id="a"))
    with pytest.raises(DuplicateJobError):
        queue.enqueue(make_job(clock, job_id="a"))


def test_idempotency_key_deduplicates(queue, clock, make_job_factory):
    queue.enqueue(make_job_factory(job_id="a", idempotency_key="k1"))
    returned = queue.enqueue(
        make_job_factory(job_id="b", idempotency_key="k1")
    )
    # Second enqueue returns the original job, no duplicate delivery.
    assert returned.job_id == "a"
    assert queue.get("b") is None


def test_renew_lease_by_owner(queue, clock):
    queue.enqueue(make_job(clock, job_id="a"))
    queue.claim("w1", lease_seconds=30)
    assert queue.renew_lease("a", "w1", lease_seconds=50) is True
    assert queue.get("a").lease_expires_at == clock() + 50


def test_renew_lease_by_non_owner_fails(queue, clock):
    queue.enqueue(make_job(clock, job_id="a"))
    queue.claim("w1")
    assert queue.renew_lease("a", "w2", lease_seconds=50) is False


def test_ack_by_owner_succeeds(queue, clock):
    queue.enqueue(make_job(clock, job_id="a"))
    queue.claim("w1")
    result = queue.ack("a", "w1")
    assert result.state is JobState.SUCCEEDED
    assert result.leased_by is None


def test_ack_by_non_owner_raises(queue, clock):
    queue.enqueue(make_job(clock, job_id="a"))
    queue.claim("w1")
    with pytest.raises(JobConflictError):
        queue.ack("a", "w2")


def test_fail_retryable_schedules_retry(queue, clock):
    queue.enqueue(make_job(clock, job_id="a", max_attempts=3))
    queue.claim("w1")
    result = queue.fail(
        "a", "w1", error="boom", error_kind="TRANSIENT_INFRASTRUCTURE",
        retryable=True, retry_delay_seconds=5,
    )
    assert result.state is JobState.RETRYABLE
    assert result.retry_at == clock() + 5
    assert result.last_error_kind == "TRANSIENT_INFRASTRUCTURE"


def test_fail_non_retryable_terminal(queue, clock):
    queue.enqueue(make_job(clock, job_id="a", max_attempts=3))
    queue.claim("w1")
    result = queue.fail(
        "a", "w1", error="bad", error_kind="PROGRAMMING_ERROR",
        retryable=False,
    )
    assert result.state is JobState.FAILED


def test_fail_attempts_exhausted_terminal(queue, clock):
    queue.enqueue(make_job(clock, job_id="a", max_attempts=1))
    queue.claim("w1")
    result = queue.fail(
        "a", "w1", error="x", error_kind="TRANSIENT_INFRASTRUCTURE",
        retryable=True,
    )
    assert result.state is JobState.FAILED


def test_retry_job_claimable_after_retry_at(queue, clock):
    queue.enqueue(make_job(clock, job_id="a", max_attempts=3))
    queue.claim("w1")
    queue.fail(
        "a", "w1", error="x", error_kind="TRANSIENT_INFRASTRUCTURE",
        retryable=True, retry_delay_seconds=5,
    )
    # Not yet claimable.
    assert queue.claim("w2") is None
    clock.advance(5)
    claimed = queue.claim("w2")
    assert claimed is not None
    assert claimed.job_id == "a"
    assert claimed.attempt_count == 2


def test_recover_stale_requeues_crashed_worker(queue, clock):
    queue.enqueue(make_job(clock, job_id="a", max_attempts=3))
    queue.claim("w1", lease_seconds=10)
    clock.advance(10)
    recovered = queue.recover_stale()
    assert len(recovered) == 1
    assert recovered[0].state is JobState.PENDING


def test_recover_stale_ignores_active_lease(queue, clock):
    queue.enqueue(make_job(clock, job_id="a", max_attempts=3))
    queue.claim("w1", lease_seconds=10)
    clock.advance(5)
    assert queue.recover_stale() == []


def test_recover_stale_fails_when_attempts_exhausted(queue, clock):
    queue.enqueue(make_job(clock, job_id="a", max_attempts=1))
    queue.claim("w1", lease_seconds=5)
    clock.advance(5)
    recovered = queue.recover_stale()
    assert recovered[0].state is JobState.FAILED


def test_cancel_non_terminal(queue, clock):
    queue.enqueue(make_job(clock, job_id="a"))
    result = queue.cancel("a")
    assert result.state is JobState.CANCELLED


def test_cancel_terminal_raises(queue, clock):
    queue.enqueue(make_job(clock, job_id="a"))
    queue.claim("w1")
    queue.ack("a", "w1")
    with pytest.raises(JobConflictError):
        queue.cancel("a")


def test_get_unknown_returns_none(queue):
    assert queue.get("nope") is None


def test_find_by_idempotency_key(queue, clock):
    queue.enqueue(make_job(clock, job_id="a", idempotency_key="k"))
    found = queue.find_by_idempotency_key("k")
    assert found is not None and found.job_id == "a"
    assert queue.find_by_idempotency_key("missing") is None


def test_ack_unknown_raises(queue):
    with pytest.raises(JobNotFoundError):
        queue.ack("nope", "w1")