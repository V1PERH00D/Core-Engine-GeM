"""Worker loop for asynchronous submission processing.

The worker is deliberately thin: it claims a job from the *existing*
queue abstraction, hands the job payload to the application service's
pipeline, and acknowledges or fails the job using the existing
classification/retry machinery (:func:`infrastructure.errors.decide_failure`).
Redis (or the in-memory queue) owns only transient lease/retry state;
the durable result lives in the persistence layer.
"""

from __future__ import annotations

from typing import Any

from infrastructure.errors import FailureKind, RetryPolicy, decide_failure
from infrastructure.jobs.models import Job, JobState
from infrastructure.jobs.queue import JobQueue

from application.models import BidderSubmission
from application.service import COMPLIANCE_JOB_TYPE, ComplianceApplicationService

DEFAULT_LEASE_SECONDS = 60.0


class SubmissionWorker:
    """Claims and processes compliance jobs from the queue."""

    def __init__(
        self,
        service: ComplianceApplicationService,
        *,
        queue: JobQueue | None = None,
        worker_id: str = "worker:submission",
        retry_policy: RetryPolicy | None = None,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> None:
        self._service = service
        self._queue = queue if queue is not None else service.queue
        self._worker_id = worker_id
        self._retry_policy = retry_policy or RetryPolicy()
        self._lease_seconds = lease_seconds

    def run_once(self) -> dict[str, Any] | None:
        """Claim and process at most one job; ``None`` when idle."""
        job = self._queue.claim(
            self._worker_id, lease_seconds=self._lease_seconds
        )
        if job is None:
            return None
        return self._process(job)

    def run_until_empty(self) -> list[dict[str, Any]]:
        """Drain every currently-claimable job. Stops when idle.

        Retryable jobs whose ``retry_at`` lies in the future are not
        claimable, so this returns without waiting.
        """
        outcomes: list[dict[str, Any]] = []
        while True:
            outcome = self.run_once()
            if outcome is None:
                return outcomes
            outcomes.append(outcome)

    def _process(self, job: Job) -> dict[str, Any]:
        if job.job_type != COMPLIANCE_JOB_TYPE:
            kind = FailureKind.PERMANENT_VALIDATION.value
            self._queue.fail(
                job.job_id,
                self._worker_id,
                error=f"Unsupported job type {job.job_type!r}.",
                error_kind=kind,
                retryable=False,
            )
            return {
                "job_id": job.job_id,
                "state": JobState.FAILED.value,
                "error_kind": kind,
                "retryable": False,
            }

        try:
            submission = BidderSubmission.validate_or_raise(
                job.payload.get("submission")
            )
            result = self._service._process_existing_submission(
                submission, correlation_id=job.correlation_id
            )
        except Exception as exc:
            decision = decide_failure(
                exc, attempt=job.attempt_count, policy=self._retry_policy
            )
            self._queue.fail(
                job.job_id,
                self._worker_id,
                error=decision.message,
                error_kind=decision.kind.value,
                retryable=decision.retryable,
                retry_delay_seconds=decision.retry_delay_seconds,
            )
            if decision.kind is FailureKind.PROGRAMMING_ERROR:
                # A bug must surface loudly; the job is dead-lettered.
                raise
            return {
                "job_id": job.job_id,
                "state": (
                    JobState.RETRYABLE.value
                    if decision.retryable
                    else JobState.FAILED.value
                ),
                "error": decision.message,
                "error_kind": decision.kind.value,
                "retryable": decision.retryable,
            }

        self._queue.ack(job.job_id, self._worker_id)
        return {
            "job_id": job.job_id,
            "state": JobState.SUCCEEDED.value,
            "bidder_id": result.compliance.bidder_id,
            "snapshot_id": result.processing.snapshot_id,
        }


__all__ = ["SubmissionWorker"]
