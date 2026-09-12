"""Processing coordinator: durable stage orchestration.

The coordinator owns *processing state* (the :class:`ProcessingStage`
pipeline) and wiring, never domain/compliance decisions (those belong to
the Compliance Engine and the AI Verification Engine).

Every stage advance is validated with
:func:`infrastructure.pipeline.validate_transition`, mirrored as an audit
event, and paired (where a downstream worker is needed) with a queued job
plus an outbox event. Resumability is durable: the submission row holds
the current stage, last completed stage, attempt count, last error, and
correlation ID, never a transient Python object.
"""

from __future__ import annotations

from dataclasses import field
from typing import Any, Callable

from pydantic import BaseModel

from infrastructure.artifacts import ArtifactStore
from infrastructure.audit import audit_event, new_event_id
from infrastructure.jobs.idempotency import make_idempotency_key
from infrastructure.jobs.models import Job, JobState
from infrastructure.jobs.queue import JobQueue
from infrastructure.persistence.records import (
    BidderRecord,
    DocumentRecord,
    OutboxEventRecord,
    SubmissionRecord,
    to_job_record,
)
from infrastructure.pipeline import ProcessingStage, validate_transition


class IngestedDocument(BaseModel):
    """One document to persist at ingestion."""

    document_id: str
    document_type: str
    content: bytes
    metadata: dict[str, Any] = field(default_factory=dict)


class ProcessingCoordinator:
    """Durable submission lifecycle + stage orchestration."""

    def __init__(
        self,
        uow_factory: Callable[[], Any],
        queue: JobQueue,
        *,
        artifact_store: ArtifactStore | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._queue = queue
        self._artifact_store = artifact_store
        self._clock = clock if clock is not None else _default_clock

    def register_bidder(self, bidder_id: str) -> BidderRecord:
        uow = self._uow_factory()
        with uow:
            existing = uow.repos.bidders.get(bidder_id)
            if existing is not None:
                return existing
            now = self._clock()
            record = BidderRecord(
                bidder_id=bidder_id, created_at=now, updated_at=now
            )
            added = uow.repos.bidders.add(record)
            uow.repos.audit.add(
                audit_event(
                    aggregate_type="BIDDER",
                    aggregate_id=bidder_id,
                    event_type="BIDDER_CREATED",
                    created_at=now,
                )
            )
            return added

    def ingest_submission(
        self,
        bidder_id: str,
        submission_id: str,
        documents: list[IngestedDocument],
        *,
        correlation_id: str | None = None,
    ) -> SubmissionRecord:
        """Create bidder + submission + documents + outbox in one txn."""
        now = self._clock()
        uow = self._uow_factory()
        with uow:
            if uow.repos.bidders.get(bidder_id) is None:
                uow.repos.bidders.add(
                    BidderRecord(
                        bidder_id=bidder_id, created_at=now, updated_at=now
                    )
                )
            submission = uow.repos.submissions.add(
                SubmissionRecord(
                    submission_id=submission_id,
                    bidder_id=bidder_id,
                    stage=ProcessingStage.INGESTED.value,
                    correlation_id=correlation_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            for doc in documents:
                artifact_id, content_hash = self._persist_document_binary(doc)
                uow.repos.documents.add(
                    DocumentRecord(
                        document_id=doc.document_id,
                        submission_id=submission_id,
                        bidder_id=bidder_id,
                        document_type=doc.document_type,
                        artifact_id=artifact_id,
                        content_hash=content_hash,
                        metadata=doc.metadata,
                        created_at=now,
                    )
                )
            uow.repos.audit.add(
                audit_event(
                    aggregate_type="SUBMISSION",
                    aggregate_id=submission_id,
                    event_type="SUBMISSION_INGESTED",
                    payload={
                        "bidder_id": bidder_id,
                        "document_ids": [d.document_id for d in documents],
                    },
                    correlation_id=correlation_id,
                    created_at=now,
                )
            )
            uow.repos.outbox.add(
                OutboxEventRecord(
                    event_id=new_event_id(),
                    aggregate_type="SUBMISSION",
                    aggregate_id=submission_id,
                    event_type="SUBMISSION_INGESTED",
                    payload={"submission_id": submission_id},
                    created_at=now,
                )
            )
            return submission

    def _persist_document_binary(
        self, doc: IngestedDocument
    ) -> tuple[str | None, str | None]:
        if self._artifact_store is None:
            return None, None
        from infrastructure.artifacts import content_hash

        record = self._artifact_store.put(
            doc.content,
            content_type="application/octet-stream",
            metadata=doc.metadata,
        )
        return record.artifact_id, content_hash(doc.content)

    def advance_stage(
        self,
        submission_id: str,
        target: ProcessingStage,
        *,
        correlation_id: str | None = None,
    ) -> SubmissionRecord:
        uow = self._uow_factory()
        with uow:
            submission = uow.repos.submissions.get(submission_id)
            if submission is None:
                raise LookupError(f"Unknown submission {submission_id!r}.")
            current = ProcessingStage(submission.stage)
            validate_transition(current, target)
            now = self._clock()
            last_completed = (
                target
                if target in _COMPLETABLE_STAGES
                else submission.last_completed_stage
            )
            updated = submission.model_copy(
                update={
                    "stage": target.value,
                    "last_completed_stage": (
                        last_completed.value
                        if isinstance(last_completed, ProcessingStage)
                        else last_completed
                    ),
                    "updated_at": now,
                    "last_error": None,
                    "last_error_kind": None,
                }
            )
            uow.repos.submissions.save(updated)
            uow.repos.audit.add(
                audit_event(
                    aggregate_type="SUBMISSION",
                    aggregate_id=submission_id,
                    event_type="STAGE_ADVANCED",
                    payload={"from": submission.stage, "to": target.value},
                    correlation_id=correlation_id,
                    created_at=now,
                )
            )
            return updated

    def fail_submission(
        self,
        submission_id: str,
        error: str,
        error_kind: str,
        *,
        correlation_id: str | None = None,
    ) -> SubmissionRecord:
        uow = self._uow_factory()
        with uow:
            submission = uow.repos.submissions.get(submission_id)
            if submission is None:
                raise LookupError(f"Unknown submission {submission_id!r}.")
            now = self._clock()
            updated = submission.model_copy(
                update={
                    "stage": ProcessingStage.FAILED.value,
                    "attempt_count": submission.attempt_count + 1,
                    "last_error": error,
                    "last_error_kind": error_kind,
                    "updated_at": now,
                }
            )
            uow.repos.submissions.save(updated)
            uow.repos.audit.add(
                audit_event(
                    aggregate_type="SUBMISSION",
                    aggregate_id=submission_id,
                    event_type="STAGE_FAILED",
                    payload={"error": error, "error_kind": error_kind},
                    correlation_id=correlation_id,
                    created_at=now,
                )
            )
            return updated

    def enqueue_stage_job(
        self,
        submission_id: str,
        stage: str,
        *,
        bidder_id: str,
        job_id: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> Job:
        """Persist + enqueue one stage job with a deterministic key."""
        now = self._clock()
        job = Job(
            job_id=job_id,
            job_type=stage,
            idempotency_key=make_idempotency_key(
                submission_id=submission_id,
                stage=stage,
                logical_input=payload or {},
            ),
            submission_id=submission_id,
            bidder_id=bidder_id,
            stage=stage,
            correlation_id=correlation_id,
            payload=payload or {},
            state=JobState.PENDING,
            created_at=now,
            updated_at=now,
        )
        uow = self._uow_factory()
        with uow:
            uow.repos.jobs.save(to_job_record(job))
        self._queue.enqueue(job)
        return job

    def resume(self, submission_id: str) -> SubmissionRecord:
        """Return the durable resumability anchor for a submission."""
        uow = self._uow_factory()
        with uow:
            submission = uow.repos.submissions.get(submission_id)
        if submission is None:
            raise LookupError(f"Unknown submission {submission_id!r}.")
        return submission


_COMPLETABLE_STAGES = frozenset(
    {
        ProcessingStage.INGESTED,
        ProcessingStage.NORMALIZED,
        ProcessingStage.VERIFIED,
        ProcessingStage.AI_ANALYZED,
        ProcessingStage.EXPLANATION_READY,
        ProcessingStage.COMPLETE,
    }
)


def _default_clock() -> float:
    import time

    return time.time()


__all__ = ["IngestedDocument", "ProcessingCoordinator"]
