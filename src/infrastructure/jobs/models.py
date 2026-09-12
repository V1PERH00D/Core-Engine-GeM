"""Job model and states for the processing queue.

A :class:`Job` is the unit of work moved through the queue. The same
shape is stored in Redis (as JSON) and mirrored durably in PostgreSQL
(``processing_jobs`` table) so a crash never loses the history of what
ran, failed or succeeded.

Timestamps are POSIX epoch seconds (``float``) so both backends store
them identically and tests can inject a deterministic clock.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

DEFAULT_LEASE_SECONDS: float = 60.0
DEFAULT_MAX_ATTEMPTS: int = 3


class JobState(StrEnum):
    """Lifecycle states of a queued job."""

    PENDING = "PENDING"
    """Queued and waiting to be claimed."""

    RUNNING = "RUNNING"
    """Claimed by a worker holding an active lease."""

    RETRYABLE = "RETRYABLE"
    """Failed; scheduled for another attempt at ``retry_at``."""

    SUCCEEDED = "SUCCEEDED"
    """Terminal: acknowledged by the worker that owned the lease."""

    FAILED = "FAILED"
    """Terminal: failed without remaining attempts (or non-retryable)."""

    CANCELLED = "CANCELLED"
    """Terminal: cancelled before completion."""


TERMINAL_STATES: frozenset[JobState] = frozenset(
    {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}
)


class Job(BaseModel):
    """A unit of work with lease and retry metadata.

    ``idempotency_key`` identifies the *logical* work item
    (submission + stage + logical input). Enqueueing the same key twice
    returns the existing job instead of creating a duplicate. Durable
    deduplication is additionally enforced by the PostgreSQL unique
    constraint on ``processing_jobs.idempotency_key``.
    """

    job_id: str
    job_type: str
    idempotency_key: str | None = None
    submission_id: str | None = None
    bidder_id: str | None = None
    stage: str | None = None
    correlation_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    state: JobState = JobState.PENDING
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = DEFAULT_MAX_ATTEMPTS

    leased_by: str | None = None
    lease_expires_at: float | None = None
    retry_at: float | None = None

    last_error: str | None = None
    last_error_kind: str | None = None

    created_at: float
    updated_at: float

    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES


__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "Job",
    "JobState",
    "TERMINAL_STATES",
]
