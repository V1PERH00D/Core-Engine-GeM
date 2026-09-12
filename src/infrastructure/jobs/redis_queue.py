"""Redis-backed production adapter for the job queue.

Redis owns *transient coordination* only: the pending list, the retry
sorted-set, the per-job coordination payload, and short-lived
idempotency markers. Durable job history lives in PostgreSQL
(``processing_jobs``); the
:class:`~infrastructure.jobs.durable.DurableJobQueue` wrapper mirrors
every queue mutation there.

Key layout (all keys share the ``namespace`` prefix):

* ``{ns}:pending``   — LIST of job IDs awaiting a worker.
* ``{ns}:retry``     — ZSET of job IDs scored by ``retry_at``.
* ``{ns}:job:{id}``  — STRING holding the JSON-serialised Job.
* ``{ns}:idem:{key}``— STRING mapping an idempotency key to a job ID.

The client is injected; no connection or credentials are created here.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from infrastructure.jobs.models import (
    DEFAULT_LEASE_SECONDS,
    Job,
    JobState,
    TERMINAL_STATES,
)
from infrastructure.jobs.queue import (
    DuplicateJobError,
    JobConflictError,
    JobNotFoundError,
)

_CLAIM_LUA = """
local pending = KEYS[1]
local retry = KEYS[2]
local now = tonumber(ARGV[1])
local worker = ARGV[2]
local lease = tonumber(ARGV[3])
local prefix = ARGV[4]

local due = redis.call('ZRANGEBYSCORE', retry, '-inf', now, 'LIMIT', 0, 1)
local job_id = nil
if #due > 0 then
  job_id = due[1]
  redis.call('ZREM', retry, job_id)
else
  job_id = redis.call('RPOP', pending)
end
if not job_id then
  return nil
end
local raw = redis.call('GET', prefix .. job_id)
if not raw then
  return nil
end
local job = cjson.decode(raw)
job['state'] = 'RUNNING'
job['attempt_count'] = (job['attempt_count'] or 0) + 1
job['leased_by'] = worker
job['lease_expires_at'] = now + lease
job['updated_at'] = now
redis.call('SET', prefix .. job_id, cjson.encode(job))
return cjson.encode(job)
"""


class RedisJobQueue:
    """Production :class:`~infrastructure.jobs.queue.JobQueue` adapter.

    ``client`` is a ``redis.Redis``-compatible synchronous client.
    Ownership of the client (construction, pooling, credentials) stays
    with the caller; this adapter never fabricates connections.
    """

    def __init__(
        self,
        client: Any,
        *,
        namespace: str = "gem:jobs",
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not namespace:
            raise ValueError("namespace must be non-empty")
        self._client = client
        self._ns = namespace
        self._clock = clock if clock is not None else time.time
        self._claim_script = client.register_script(_CLAIM_LUA)

    # ------------------------------------------------------------------
    # key helpers
    # ------------------------------------------------------------------

    def _pending_key(self) -> str:
        return f"{self._ns}:pending"

    def _retry_key(self) -> str:
        return f"{self._ns}:retry"

    def _job_key(self, job_id: str) -> str:
        return f"{self._ns}:job:{job_id}"

    def _idem_key(self, key: str) -> str:
        return f"{self._ns}:idem:{key}"

    def _now(self) -> float:
        return float(self._clock())

    def _load(self, job_id: str) -> Job | None:
        raw = self._client.get(self._job_key(job_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return Job.model_validate_json(raw)

    def _store(self, job: Job) -> None:
        self._client.set(self._job_key(job.job_id), job.model_dump_json())

    def _require(self, job_id: str) -> Job:
        job = self._load(job_id)
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
        if (
            job.lease_expires_at is not None
            and job.lease_expires_at < self._now()
        ):
            raise JobConflictError(
                f"Lease for job {job.job_id!r} has expired; the job "
                "must be recovered before it can be acted on."
            )



    # ------------------------------------------------------------------
    # JobQueue implementation
    # ------------------------------------------------------------------

    def enqueue(self, job: Job) -> Job:
        if self._load(job.job_id) is not None:
            raise DuplicateJobError(
                f"Job id {job.job_id!r} is already enqueued."
            )
        now = self._now()
        if job.idempotency_key is not None:
            # SET NX: atomic first-writer-wins deduplication.
            claimed = self._client.set(
                self._idem_key(job.idempotency_key),
                job.job_id,
                nx=True,
            )
            if not claimed:
                existing_id = self._client.get(
                    self._idem_key(job.idempotency_key)
                )
                if isinstance(existing_id, bytes):
                    existing_id = existing_id.decode("utf-8")
                existing = self._load(existing_id)
                if existing is not None:
                    return existing
        job = job.model_copy(update={"updated_at": now})
        pipe = self._client.pipeline()
        pipe.set(self._job_key(job.job_id), job.model_dump_json())
        if job.state is JobState.PENDING:
            pipe.lpush(self._pending_key(), job.job_id)
        elif job.state is JobState.RETRYABLE and job.retry_at is not None:
            pipe.zadd(self._retry_key(), {job.job_id: job.retry_at})
        pipe.execute()
        return job

    def claim(
        self, worker_id: str, *, lease_seconds: float = DEFAULT_LEASE_SECONDS
    ) -> Job | None:
        result = self._claim_script(
            keys=[self._pending_key(), self._retry_key()],
            args=[
                self._now(),
                worker_id,
                lease_seconds,
                f"{self._ns}:job:",
            ],
        )
        if result is None:
            return None
        if isinstance(result, bytes):
            result = result.decode("utf-8")
        return Job.model_validate_json(result)

    def renew_lease(
        self, job_id: str, worker_id: str, *, lease_seconds: float
    ) -> bool:
        job = self._load(job_id)
        if (
            job is None
            or job.state is not JobState.RUNNING
            or job.leased_by != worker_id
        ):
            return False
        now = self._now()
        if job.lease_expires_at is not None and job.lease_expires_at < now:
            return False
        job = job.model_copy(
            update={
                "lease_expires_at": now + lease_seconds,
                "updated_at": now,
            }
        )
        self._store(job)
        return True

    def ack(self, job_id: str, worker_id: str) -> Job:
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
        self._store(updated)
        return updated


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
        job = self._require(job_id)
        self._check_lease(job, worker_id)
        now = self._now()
        can_retry = retryable and job.attempt_count < job.max_attempts
        update: dict[str, Any] = {
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
        pipe = self._client.pipeline()
        pipe.set(self._job_key(job_id), updated.model_dump_json())
        if can_retry:
            pipe.zadd(self._retry_key(), {job_id: update["retry_at"]})
        pipe.execute()
        return updated

    def cancel(self, job_id: str) -> Job:
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
        pipe = self._client.pipeline()
        pipe.set(self._job_key(job_id), updated.model_dump_json())
        pipe.lrem(self._pending_key(), 0, job_id)
        pipe.zrem(self._retry_key(), job_id)
        pipe.execute()
        return updated

    def recover_stale(self) -> list[Job]:
        now = self._now()
        recovered: list[Job] = []
        for key in self._client.scan_iter(f"{self._ns}:job:*"):
            raw = self._client.get(key)
            if raw is None:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            job = Job.model_validate_json(raw)
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
                self._store(updated)
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
                pipe = self._client.pipeline()
                pipe.set(self._job_key(job.job_id), updated.model_dump_json())
                pipe.lpush(self._pending_key(), job.job_id)
                pipe.execute()
            recovered.append(updated)
        return recovered

    def get(self, job_id: str) -> Job | None:
        return self._load(job_id)

    def find_by_idempotency_key(self, key: str) -> Job | None:
        job_id = self._client.get(self._idem_key(key))
        if job_id is None:
            return None
        if isinstance(job_id, bytes):
            job_id = job_id.decode("utf-8")
        return self._load(job_id)


class RedisIdempotencyStore:
    """Redis-backed fast-path idempotency store.

    Entries expire after ``ttl_seconds`` (default 24h). Redis is only a
    coordination cache: durable idempotency is enforced by the
    PostgreSQL unique constraint on ``processing_jobs.idempotency_key``.
    """

    def __init__(
        self,
        client: Any,
        *,
        namespace: str = "gem:idem",
        ttl_seconds: float = 86400.0,
    ) -> None:
        self._client = client
        self._ns = namespace
        self._ttl = int(ttl_seconds)

    def _key(self, key: str) -> str:
        return f"{self._ns}:{key}"

    def get_or_create(
        self, key: str, job_id: str, *, now: float
    ) -> tuple[str, bool]:
        stored = self._client.set(
            self._key(key), f"{job_id}|{now}", nx=True, ex=self._ttl
        )
        if stored:
            return job_id, True
        existing = self._client.get(self._key(key))
        if isinstance(existing, bytes):
            existing = existing.decode("utf-8")
        existing_job = (existing or "").split("|", 1)[0]
        return existing_job, False

    def get(self, key: str):
        from infrastructure.jobs.idempotency import IdempotencyRecord

        raw = self._client.get(self._key(key))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        job_id, _, created = raw.partition("|")
        return IdempotencyRecord(
            key=key, job_id=job_id, created_at=float(created or 0.0)
        )

    def delete(self, key: str) -> None:
        self._client.delete(self._key(key))


__all__ = ["RedisIdempotencyStore", "RedisJobQueue"]

