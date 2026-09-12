"""Typed persistence records (the PostgreSQL relational shape).

These records are the *durable* representation of the domain's outputs.
They are deliberately JSON/DB friendly: timestamps are POSIX epoch
seconds (UTC floats), structured-but-evolving data lives in JSON-ready
``dict`` fields, and references are always real IDs (never fabricated).

Where a domain model already exists (``Evidence``, ``Verification``,
``ComplianceResult``, findings, ``Explanation``, traces, assessments) the
record stores the *stable, JSON-safe* projection of that model plus the
relational linkage the schema needs for foreign keys, uniqueness, and
lineage queries. The full artefact is round-tripped via
:mod:`infrastructure.serialization` so no Python object is ever pickled.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Durable relational records
# ---------------------------------------------------------------------------


class BidderRecord(BaseModel):
    """One bidder. The root of every lineage graph."""

    bidder_id: str
    created_at: float
    updated_at: float


class SubmissionRecord(BaseModel):
    """One bid's submission and its processing state.

    ``stage`` is the current :class:`ProcessingStage` value as a string;
    ``last_completed_stage`` is the last stage that completed
    successfully (the resumability anchor). Processing state is distinct
    from compliance state.
    """

    submission_id: str
    bidder_id: str
    stage: str
    last_completed_stage: str | None = None
    correlation_id: str | None = None
    attempt_count: int = Field(default=0, ge=0)
    last_error: str | None = None
    last_error_kind: str | None = None
    created_at: float
    updated_at: float


class DocumentRecord(BaseModel):
    """Metadata for one submitted document (binary lives in an artifact
    store; only the artifact reference + content hash are durable here).
    """

    document_id: str
    submission_id: str | None = None
    bidder_id: str
    document_type: str
    artifact_id: str | None = None
    content_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float


class EvidenceRecord(BaseModel):
    """One normalized field extracted from a document."""

    evidence_id: str
    bidder_id: str
    document_id: str
    field_name: str
    document_type: str | None = None
    value: Any = None
    confidence: float | None = None
    page: int | None = None
    bbox: list[float] | None = None
    created_at: float


class VerificationRecord(BaseModel):
    """One authoritative verification record.

    ``data``, ``query`` and ``raw_response`` hold JSON-safe payloads; the
    transport/status columns stay scalar and indexed for audit queries.
    """

    verification_id: str
    bidder_id: str
    capability: str
    source: str
    queried_identifier: str | None = None
    status: str
    data: dict[str, Any] = Field(default_factory=dict)
    query: dict[str, Any] | None = None
    raw_response: Any = None
    retrieved_at: float
    latency_ms: int | None = None
    correlation_id: str | None = None
    transport_status_code: int | None = None
    evidence_id: str | None = None
    document_id: str | None = None
    created_at: float


class ComplianceResultRecord(BaseModel):
    """One per-requirement compliance outcome.

    Unique on ``(bidder_id, requirement_id)`` for idempotent upsert; the
    surrogate ``result_id`` is stable across re-runs of the same
    requirement by the same bidder.
    """

    result_id: str
    bidder_id: str
    requirement_id: str
    capability: str
    status: str
    reason: str
    expected: Any = None
    actual: Any = None
    rule_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    verification_refs: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    created_at: float
    updated_at: float


class FindingRecord(BaseModel):
    """One finding (identity, cross-document, cross-bidder, or financial).

    ``finding_type`` discriminates the source domain model; ``payload``
    holds the full JSON-safe artefact. Idempotent by ``finding_id``.
    """

    finding_id: str
    bidder_id: str
    finding_type: str
    flag_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    verification_refs: list[str] = Field(default_factory=list)
    related_bidder_ids: list[str] = Field(default_factory=list)
    created_at: float


class ExplanationRecord(BaseModel):
    """One persisted explanation (grounded, not a bare string).

    See :mod:`ai_verification.explanations` for the domain model. This
    record keeps the relational linkage plus the structured grounding and
    generation metadata. Idempotent by ``explanation_id``.
    """

    explanation_id: str
    bidder_id: str
    flag_id: str
    flag_active: bool
    finding_refs: list[str] = Field(default_factory=list)
    concise_text: str
    detailed_text: str | None = None
    grounding: list[dict[str, Any]] = Field(default_factory=list)
    generation: dict[str, Any] = Field(default_factory=dict)
    created_at: float

    # Rich explanation metadata / lineage added by the explanation engine.
    schema_version: int | None = None
    grounding_version: int | None = None
    validation_status: str | None = None
    fallback_used: bool | None = None
    input_hash: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    verification_refs: list[str] = Field(default_factory=list)
    document_refs: list[str] = Field(default_factory=list)
    comparison_refs: list[str] = Field(default_factory=list)
    trace_refs: list[str] = Field(default_factory=list)
    content: dict[str, Any] | None = None
    uncertainties: list[str] = Field(default_factory=list)
    review_actions: list[str] = Field(default_factory=list)


class ProcessingJobRecord(BaseModel):
    """Durable mirror of a queued job's history/state."""

    job_id: str
    idempotency_key: str | None = None
    submission_id: str | None = None
    bidder_id: str | None = None
    job_type: str
    stage: str | None = None
    correlation_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    state: str
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    leased_by: str | None = None
    lease_expires_at: float | None = None
    retry_at: float | None = None
    last_error: str | None = None
    last_error_kind: str | None = None
    created_at: float
    updated_at: float


class AuditEventRecord(BaseModel):
    """One append-only audit event with a real aggregate pointer."""

    event_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None
    created_at: float


class OutboxEventRecord(BaseModel):
    """One transactional-outbox event awaiting publication."""

    event_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: float
    published_at: float | None = None
    attempts: int = Field(default=0, ge=0)


class FlagStateRecord(BaseModel):
    """The boolean downstream state of one canonical flag for one bidder.

    Severity and risk are intentionally absent. This is the canonical
    boolean representation consumed downstream.
    """

    bidder_id: str
    flag_id: str
    is_set: bool
    source: str | None = None
    finding_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    verification_refs: list[str] = Field(default_factory=list)
    correlation_id: str | None = None
    updated_at: float


class FlagSnapshotRecord(BaseModel):
    """One materialized, reproducible flag snapshot for a bidder."""

    snapshot_id: str
    bidder_id: str
    snapshot_version: str
    flags: dict[str, bool] = Field(default_factory=dict)
    provenance: dict[str, dict[str, Any]] = Field(default_factory=dict)
    content_hash: str
    correlation_id: str | None = None
    created_at: float


# ---------------------------------------------------------------------------
# Conversions between queue Job and durable job record
# ---------------------------------------------------------------------------


def to_job_record(job: "infrastructure.jobs.models.Job") -> ProcessingJobRecord:  # noqa: F821
    """Project a queue :class:`Job` into a durable record."""
    return ProcessingJobRecord(
        job_id=job.job_id,
        idempotency_key=job.idempotency_key,
        submission_id=job.submission_id,
        bidder_id=job.bidder_id,
        job_type=job.job_type,
        stage=job.stage,
        correlation_id=job.correlation_id,
        payload=dict(job.payload),
        state=job.state.value,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        leased_by=job.leased_by,
        lease_expires_at=job.lease_expires_at,
        retry_at=job.retry_at,
        last_error=job.last_error,
        last_error_kind=job.last_error_kind,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def to_job_model(record: ProcessingJobRecord) -> "infrastructure.jobs.models.Job":  # noqa: F821
    """Reconstruct a queue :class:`Job` from a durable record."""
    from infrastructure.jobs.models import Job

    return Job(
        job_id=record.job_id,
        idempotency_key=record.idempotency_key,
        submission_id=record.submission_id,
        bidder_id=record.bidder_id,
        job_type=record.job_type,
        stage=record.stage,
        correlation_id=record.correlation_id,
        payload=dict(record.payload),
        state=record.state,
        attempt_count=record.attempt_count,
        max_attempts=record.max_attempts,
        leased_by=record.leased_by,
        lease_expires_at=record.lease_expires_at,
        retry_at=record.retry_at,
        last_error=record.last_error,
        last_error_kind=record.last_error_kind,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


__all__ = [
    "AuditEventRecord",
    "BidderRecord",
    "ComplianceResultRecord",
    "DocumentRecord",
    "EvidenceRecord",
    "ExplanationRecord",
    "FindingRecord",
    "FlagSnapshotRecord",
    "FlagStateRecord",
    "OutboxEventRecord",
    "ProcessingJobRecord",
    "SubmissionRecord",
    "VerificationRecord",
    "to_job_model",
    "to_job_record",
]