"""Redis/job processing pipeline for explanation generation.

PostgreSQL owns the durable explanation record, the audit event, and the
outbox event. Redis (or the in-memory queue) owns only the transient job
lease and retry state. The pipeline therefore::

    enqueue -> QUEUED -> GENERATING -> VALIDATING -> READY

Failure semantics (never a compliance decision):

* provider unavailable / timeout -> RETRYABLE (re-enqueued via the queue)
* malformed model output       -> deterministic fallback
* grounding validation failure -> deterministic fallback
* programming error            -> FAILED (not retried)

Duplicate delivery is idempotent: the job idempotency key covers
``(bidder_id, flag_id, flag_state, grounding hash, schema version)`` and
the explanation record upserts on ``explanation_id``, so a duplicate queue
delivery can never create two durable explanation records.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Callable

from ai_verification.explanations.engine import ExplanationEngine
from ai_verification.explanations.facts import StructuredFact
from ai_verification.explanations.generator import ExplanationRequest
from ai_verification.explanations.grounding import (
    GROUNDING_SCHEMA_VERSION,
    ExplanationGrounding,
)
from ai_verification.explanations.models import (
    EXPLANATION_SCHEMA_VERSION,
    ExplanationResult,
)
from ai_verification.explanations.provider import (
    ExplanationModelTimeoutError,
    ExplanationModelUnavailableError,
)

from infrastructure.audit import audit_event
from infrastructure.errors import FailureKind
from infrastructure.jobs.idempotency import make_idempotency_key
from infrastructure.jobs.models import Job, JobState
from infrastructure.jobs.queue import JobQueue
from infrastructure.persistence.records import (
    ExplanationRecord,
    OutboxEventRecord,
)


class ExplanationJobStage(StrEnum):
    QUEUED = "QUEUED"
    GENERATING = "GENERATING"
    VALIDATING = "VALIDATING"
    READY = "READY"
    RETRYABLE = "RETRYABLE"
    FAILED = "FAILED"


EXPLANATION_JOB_TYPE: str = "EXPLANATION"
EXPLANATION_JOB_STAGE: str = "EXPLANATION"


def explanation_idempotency_key(
    *,
    bidder_id: str,
    flag_id: str,
    flag_state: bool,
    grounding_hash: str,
) -> str:
    return make_idempotency_key(
        submission_id=bidder_id,
        stage=EXPLANATION_JOB_STAGE,
        logical_input={
            "bidder_id": bidder_id,
            "flag_id": flag_id,
            "flag_state": flag_state,
            "grounding_hash": grounding_hash,
            "schema_version": EXPLANATION_SCHEMA_VERSION,
            "grounding_version": GROUNDING_SCHEMA_VERSION,
        },
    )


def explanation_job_id(bidder_id: str, flag_id: str, flag_state: bool) -> str:
    return f"expl-job:{bidder_id}:{flag_id}:{int(flag_state)}"


class ExplanationPipeline:
    """Job-oriented explanation processing stage."""

    def __init__(
        self,
        engine: ExplanationEngine,
        uow_factory: Callable[[], Any],
        queue: JobQueue,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._engine = engine
        self._uow_factory = uow_factory
        self._queue = queue
        self._clock = clock if clock is not None else _default_clock

    def enqueue(
        self,
        *,
        bidder_id: str,
        flag_id: str,
        flag_state: bool,
        grounding: ExplanationGrounding,
        facts: list[StructuredFact] | None = None,
        uncertainties: list[str] | None = None,
        locale: str | None = None,
        correlation_id: str | None = None,
    ) -> Job:
        grounding_hash = grounding.content_hash()
        now = self._clock()
        payload: dict[str, Any] = {
            "bidder_id": bidder_id,
            "flag_id": flag_id,
            "flag_state": flag_state,
            "grounding": {k: list(v) for k, v in grounding.all_refs().items()},
            "facts": [f.model_dump(mode="json") for f in (facts or [])],
            "uncertainties": list(uncertainties or []),
            "locale": locale,
        }
        job = Job(
            job_id=explanation_job_id(bidder_id, flag_id, flag_state),
            job_type=EXPLANATION_JOB_TYPE,
            idempotency_key=explanation_idempotency_key(
                bidder_id=bidder_id,
                flag_id=flag_id,
                flag_state=flag_state,
                grounding_hash=grounding_hash,
            ),
            bidder_id=bidder_id,
            stage=ExplanationJobStage.QUEUED.value,
            correlation_id=correlation_id,
            payload=payload,
            state=JobState.PENDING,
            created_at=now,
            updated_at=now,
        )
        uow = self._uow_factory()
        with uow:
            from infrastructure.persistence.records import to_job_record

            uow.repos.jobs.save(to_job_record(job))
        return self._queue.enqueue(job)

    def process_pending(self, worker_id: str) -> Job | None:
        job = self._queue.claim(worker_id)
        if job is None:
            return None
        try:
            self._run(job)
        except (ExplanationModelUnavailableError, ExplanationModelTimeoutError):
            return self._queue.fail(
                job.job_id,
                worker_id,
                error="Explanation provider unavailable/timeout.",
                error_kind=FailureKind.PROVIDER_UNAVAILABLE.value,
                retryable=True,
                retry_delay_seconds=1.0,
            )
        return self._queue.ack(job.job_id, worker_id)

    def _run(self, job: Job) -> None:
        payload = job.payload
        grounding = ExplanationGrounding(
            evidence_refs=tuple(payload.get("grounding", {}).get("evidence_refs", [])),
            verification_refs=tuple(
                payload.get("grounding", {}).get("verification_refs", [])
            ),
            document_refs=tuple(payload.get("grounding", {}).get("document_refs", [])),
            finding_refs=tuple(payload.get("grounding", {}).get("finding_refs", [])),
            comparison_refs=tuple(
                payload.get("grounding", {}).get("comparison_refs", [])
            ),
            trace_refs=tuple(payload.get("grounding", {}).get("trace_refs", [])),
        )
        facts = [
            StructuredFact.model_validate(f) for f in payload.get("facts", [])
        ]
        request = ExplanationRequest(
            bidder_id=payload["bidder_id"],
            flag_id=payload["flag_id"],
            flag_active=payload["flag_state"],
            facts=facts,
            uncertainties=list(payload.get("uncertainties", [])),
            locale=payload.get("locale"),
            correlation_id=job.correlation_id,
        )

        result = self._engine.explain_strict(request, grounding=grounding)

        self._persist(result, correlation_id=job.correlation_id)

    def _persist(
        self, result: ExplanationResult, *, correlation_id: str | None
    ) -> None:
        record = to_explanation_record(result, created_at=self._clock())
        now = self._clock()
        uow = self._uow_factory()
        with uow:
            uow.repos.explanations.save(record)
            uow.repos.audit.add(
                audit_event(
                    aggregate_type="EXPLANATION",
                    aggregate_id=result.explanation_id,
                    event_type="EXPLANATION_READY",
                    payload={
                        "bidder_id": result.bidder_id,
                        "flag_id": result.flag_id,
                        "flag_state": result.flag_state,
                        "fallback_used": result.fallback_used,
                        "validation_status": result.validation_status.value,
                    },
                    correlation_id=correlation_id,
                    created_at=now,
                )
            )
            uow.repos.outbox.add(
                OutboxEventRecord(
                    event_id=f"outbox:{result.explanation_id}",
                    aggregate_type="EXPLANATION",
                    aggregate_id=result.explanation_id,
                    event_type="EXPLANATION_READY",
                    payload={
                        "bidder_id": result.bidder_id,
                        "flag_id": result.flag_id,
                        "explanation_id": result.explanation_id,
                    },
                    created_at=now,
                )
            )
def to_explanation_record(
    result: ExplanationResult, *, created_at: float
) -> ExplanationRecord:
    """Project an :class:`ExplanationResult` into the durable record."""

    grounding_list: list[dict[str, Any]] = []
    for kind, refs in result.grounding.all_refs().items():
        for ref_id in refs:
            grounding_list.append({"kind": kind, "ref_id": ref_id, "note": None})

    return ExplanationRecord(
        explanation_id=result.explanation_id,
        bidder_id=result.bidder_id,
        flag_id=result.flag_id,
        flag_active=result.flag_state,
        finding_refs=list(result.grounding.finding_refs),
        concise_text=result.content.summary,
        detailed_text=result.content.detailed_explanation,
        grounding=grounding_list,
        generation=result.generation.model_dump(mode="json"),
        created_at=created_at,
        schema_version=result.schema_version,
        grounding_version=result.grounding.grounding_version,
        validation_status=result.validation_status.value,
        fallback_used=result.fallback_used,
        input_hash=result.grounding.content_hash(),
        evidence_refs=list(result.grounding.evidence_refs),
        verification_refs=list(result.grounding.verification_refs),
        document_refs=list(result.grounding.document_refs),
        comparison_refs=list(result.grounding.comparison_refs),
        trace_refs=list(result.grounding.trace_refs),
        content=result.content.model_dump(mode="json"),
        uncertainties=list(result.content.uncertainties),
        review_actions=list(result.content.recommended_review_actions),
    )


def _default_clock() -> float:
    import time

    return time.time()


__all__ = [
    "EXPLANATION_JOB_STAGE",
    "EXPLANATION_JOB_TYPE",
    "ExplanationJobStage",
    "ExplanationPipeline",
    "explanation_idempotency_key",
    "explanation_job_id",
    "to_explanation_record",
]