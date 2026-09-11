"""Durable job-queue mirror.

Redis (or the in-memory queue) coordinates the *transient* lease and
work schedule; PostgreSQL holds the *durable* job history. This wrapper
implements :class:`~infrastructure.jobs.queue.JobQueue` and forwards
every mutation to the wrapped queue, then mirrors the resulting job into
the durable :class:`JobRepository` so a crash never loses the history of
what ran, failed, or succeeded.

Idempotent replay is safe: the durable ``JobRepository`` upserts on
``job_id``, and the unique ``idempotency_key`` prevents duplicate
durable records for the same logical work.
"""

from __future__ import annotations

from infrastructure.jobs.models import DEFAULT_LEASE_SECONDS, Job
from infrastructure.jobs.queue import JobQueue
from infrastructure.persistence.records import to_job_record


class DurableJobQueue:
    """Wraps a queue and mirrors every state change to durable storage."""

    def __init__(self, queue: JobQueue, uow_factory) -> None:
        self._queue = queue
        self._uow_factory = uow_factory

    def _mirror(self, job: Job) -> None:
        uow = self._uow_factory()
        with uow:
            uow.repos.jobs.save(to_job_record(job))

    def enqueue(self, job: Job) -> Job:
        result = self._queue.enqueue(job)
        self._mirror(result)
        return result

    def claim(
        self, worker_id: str, *, lease_seconds: float = DEFAULT_LEASE_SECONDS
    ) -> Job | None:
        result = self._queue.claim(worker_id, lease_seconds=lease_seconds)
        if result is not None:
            self._mirror(result)
        return result

    def renew_lease(
        self, job_id: str, worker_id: str, *, lease_seconds: float
    ) -> bool:
        return self._queue.renew_lease(
            job_id, worker_id, lease_seconds=lease_seconds
        )

    def ack(self, job_id: str, worker_id: str) -> Job:
        result = self._queue.ack(job_id, worker_id)
        self._mirror(result)
        return result

    def fail(
        self,
        job_id: str,
        worker_id: str,
        *,
        error: str,
        error_kind: str,
        retryable: bool,
        retry_delay_seconds: float = 0.0,
    ) -> Job:
        result = self._queue.fail(
            job_id,
            worker_id,
            error=error,
            error_kind=error_kind,
            retryable=retryable,
            retry_delay_seconds=retry_delay_seconds,
        )
        self._mirror(result)
        return result

    def cancel(self, job_id: str) -> Job:
        result = self._queue.cancel(job_id)
        self._mirror(result)
        return result

    def recover_stale(self) -> list[Job]:
        result = self._queue.recover_stale()
        for job in result:
            self._mirror(job)
        return result

    def get(self, job_id: str) -> Job | None:
        return self._queue.get(job_id)

    def find_by_idempotency_key(self, key: str) -> Job | None:
        return self._queue.find_by_idempotency_key(key)


__all__ = ["DurableJobQueue"]