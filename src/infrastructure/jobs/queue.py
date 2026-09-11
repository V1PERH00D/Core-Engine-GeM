"""Job queue contract and the in-memory implementation.

The :class:`JobQueue` protocol is the single seam used by workers and
the outbox publisher. Two implementations exist:

- :class:`InMemoryJobQueue` — deterministic, clock-injected, used by
  the unit-test suite and local development without Redis.
- :class:`~infrastructure.jobs.redis_queue.RedisJobQueue` — production
  adapter backed by Redis lists/sorted sets with atomic Lua scripts.

Lease semantics are identical in both: only the lease holder may ack,
fail, or renew; a crashed worker's job is recovered by
:meth:`JobQueue.recover_stale` once its lease expires. Enqueueing an
idempotency key that already exists returns the existing job instead
of creating a duplicate delivery.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Protocol

from infrastructure.jobs.models import (
    DEFAULT_LEASE_SECONDS,
    Job,
    JobState,
    TERMINAL_STATES,
)


class JobNotFoundError(KeyError):
    """Raised when a job ID is unknown to the queue."""


class DuplicateJobError(ValueError):
    """Raised when enqueueing a job ID that already exists."""


class JobConflictError(RuntimeError):
    """Raised when a worker acts on a job/lease it does not own."""


class JobQueue(Protocol):
    """Queue seam: enqueue, claim with lease, ack/fail/renew/recover."""

    def enqueue(self, job: Job) -> Job:
        """Enqueue ``job``; idempotency-key collisions return the original."""
        ...

    def claim(
        self, worker_id: str, *, lease_seconds: float = DEFAULT_LEASE_SECONDS
    ) -> Job | None:
        """Atomically claim the next pending job, or ``None``."""
        ...

    def renew_lease(
        self, job_id: str, worker_id: str, *, lease_seconds: float
    ) -> bool:
        """Extend the lease if ``worker_id`` currently holds it."""
        ...

    def ack(self, job_id: str, worker_id: str) -> Job:
        """Mark the job SUCCEEDED; only the lease holder may ack."""
        ...

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
        """Mark the claimed attempt failed; retryable failures reschedule."""
        ...

    def cancel(self, job_id: str) -> Job:
        """Cancel a non-terminal job."""
        ...

    def recover_stale(self) -> list[Job]:
        """Requeue RUNNING jobs whose lease has expired (crashed workers)."""
        ...

    def get(self, job_id: str) -> Job | None:
        """Return the current job state, or ``None`` if unknown."""
        ...

    def find_by_idempotency_key(self, key: str) -> Job | None:
        """Return the job registered under ``key``, or ``None``."""


class InMemoryJobQueue:
    """Deterministic in-memory :class:`JobQueue` for tests and local dev.

    * Thread-safe via a single re-entrant lock.
    * Clock is injectable (``Callable[[], float]``) so tests can move
      time deterministically.
    * All returned jobs are deep copies; mutating a returned job never
      mutates queue state.
    * Idempotency: enqueueing a job whose ``idempotency_key`` is already
      known returns the previously enqueued job unchanged.
    * Lease: a claimed job can only be acked/failed/renewed by the
      worker that holds a live lease. A crashed worker's job is moved
      back to PENDING (or FAILED when attempts are exhausted) by
      :meth:`recover_stale`.
    """

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock if clock is not None else time.time
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._pending: deque[str] = deque()
        self._by_idempotency_key: dict[str, str] = {}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _now(self) -> float:
        return float(self._clock())

    def _require(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    def _check_lease(self, job: Job, worker_id: str) -> None:
        if job.state is not JobState.RUNNING:
            raise JobConflictError(
                f"Job {job.job_id!r} is not RUNNING "
                f"(state={job.state.value})."
            )
        if job.leased_by != worker_id:
            raise JobConflictError(
                f"Job {job.job_id!r} is leased by {job.leased_by!r}, "
                f"not {worker_id!r}."
            )
        if job.lease_expires_at is not None and job.lease_expires_at < self._now():
            raise JobConflictError(
                f"Lease for job {job.job_id!r} has expired; the job must "
                "be recovered before it can be acted on."
            )

    # ------------------------------------------------------------------
    # JobQueue implementation
    # ------------------------------------------------------------------

    def enqueue(self, job: Job) -> Job:
        with self._lock:
            if job.job_id in self._jobs:
                raise DuplicateJobError(
                    f"Job id {job.job_id!r} is already enqueued."
                )
            key = job.idempotency_key
            if key is not None and key in self._by_idempotency_key:
                existing_id = self._by_idempotency_key[key]
                return self._jobs[existing_id].model_copy(deep=True)
            self._jobs[job.job_id] = job.model_copy(deep=True)
            if key is not None:
                self._by_idempotency_key[key] = job.job_id
            if job.state in (JobState.PENDING, JobState.RETRYABLE):
                self._pending.append(job.job_id)
            return job.model_copy(deep=True)

    def claim(
        self, worker_id: str, *, lease_seconds: float = DEFAULT_LEASE_SECONDS
    ) -> Job | None:
        with self._lock:
            now = self._now()
            job_id: str | None = None
            for _ in range(len(self._pending)):
                candidate = self._pending.popleft()
                job = self._jobs[candidate]
                if job.state is JobState.PENDING:
                    job_id = candidate
                    break
                if (
                    job.state is JobState.RETRYABLE
                    and job.retry_at is not None
                    and job.retry_at <= now
                ):
                    job_id = candidate
                    break
                # Not yet claimable; push back (retry jobs await retry_at).
                self._pending.append(candidate)
            if job_id is None:
                return None
            job = self._jobs[job_id]
            claimed = job.model_copy(
                update={
                    "state": JobState.RUNNING,
                    "attempt_count": job.attempt_count + 1,
                    "leased_by": worker_id,
                    "lease_expires_at": now + lease_seconds,
                    "updated_at": now,
                }
            )
            self._jobs[job_id] = claimed
            return claimed.model_copy(deep=True)

    def renew_lease(
        self, job_id: str, worker_id: str, *, lease_seconds: float
    ) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state is not JobState.RUNNING:
                return False
            if job.leased_by != worker_id:
                return False
            now = self._now()
            if job.lease_expires_at is not None and job.lease_expires_at < now:
                return False
            self._jobs[job_id] = job.model_copy(
                update={
                    "lease_expires_at": now + lease_seconds,
                    "updated_at": now,
                }
            )
            return True

    def ack(self, job_id: str, worker_id: str) -> Job:
        with self._lock:
            job = self._require(job_id)
            self._check_lease(job, worker_id)
            updated = job.model_copy(
                update={
                    "state": JobState.SUCCEEDED,
                    "leased_by": None,
                    "lease_expires_at": None,
                    "retry_at": None,
                    "updated_at": self._now(),
                }
            )
            self._jobs[job_id] = updated
            return updated.model_copy(deep=True)

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
        with self._lock:
            job = self._require(job_id)
            self._check_lease(job, worker_id)
            now = self._now()
            can_retry = retryable and job.attempt_count < job.max_attempts
            update: dict = {
                "leased_by": None,
                "lease_expires_at": None,
                "last_error": error,
                "last_error_kind": error_kind,
                "updated_at": now,
            }
            if can_retry:
                update["state"] = JobState.RETRYABLE
                update["retry_at"] = now + max(0.0, retry_delay_seconds)
            else:
                update["state"] = JobState.FAILED
                update["retry_at"] = None
            updated = job.model_copy(update=update)
            self._jobs[job_id] = updated
            if can_retry:
                self._pending.append(job_id)
            return updated.model_copy(deep=True)

    def cancel(self, job_id: str) -> Job:
        with self._lock:
            job = self._require(job_id)
            if job.state in TERMINAL_STATES:
                raise JobConflictError(
                    f"Job {job_id!r} is already in terminal state "
                    f"{job.state.value}."
                )
            updated = job.model_copy(
                update={
                    "state": JobState.CANCELLED,
                    "leased_by": None,
                    "lease_expires_at": None,
                    "retry_at": None,
                    "updated_at": self._now(),
                }
            )
            self._jobs[job_id] = updated
            return updated.model_copy(deep=True)

    def recover_stale(self) -> list[Job]:
        """Requeue RUNNING jobs whose lease has expired.

        A job whose attempts are already exhausted is moved to FAILED
        rather than requeued, mirroring the durable retry budget.
        """
        recovered: list[Job] = []
        with self._lock:
            now = self._now()
            for job_id, job in list(self._jobs.items()):
                if job.state is not JobState.RUNNING:
                    continue
                if job.lease_expires_at is None or job.lease_expires_at > now:
                    continue
                if job.attempt_count >= job.max_attempts:
                    updated = job.model_copy(
                        update={
                            "state": JobState.FAILED,
                            "leased_by": None,
                            "lease_expires_at": None,
                            "last_error": "Lease expired after final attempt.",
                            "last_error_kind": "TRANSIENT_INFRASTRUCTURE",
                            "updated_at": now,
                        }
                    )
                else:
                    updated = job.model_copy(
                        update={
                            "state": JobState.PENDING,
                            "leased_by": None,
                            "lease_expires_at": None,
                            "retry_at": None,
                            "updated_at": now,
                        }
                    )
                    self._pending.append(job_id)
                self._jobs[job_id] = updated
                recovered.append(updated.model_copy(deep=True))
        return recovered

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else job.model_copy(deep=True)

    def find_by_idempotency_key(self, key: str) -> Job | None:
        with self._lock:
            job_id = self._by_idempotency_key.get(key)
            if job_id is None:
                return None
            return self._jobs[job_id].model_copy(deep=True)

    # ------------------------------------------------------------------
    # Introspection helpers (not part of the protocol; used by tests and
    # the durable mirror for reconciliation).
    # ------------------------------------------------------------------

    def pending_count(self) -> int:
        with self._lock:
            return sum(
                1
                for job_id in self._pending
                if self._jobs[job_id].state
                in (JobState.PENDING, JobState.RETRYABLE)
            )

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return [
                job.model_copy(deep=True) for job in self._jobs.values()
            ]
        ...
