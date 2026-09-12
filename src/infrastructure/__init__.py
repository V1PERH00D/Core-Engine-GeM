"""Persistence and processing infrastructure for the compliance platform.

This package owns the *system* backbone — durable storage, artifact
storage, job queues, leases, retries, idempotency, transactional
outbox, audit trail and flag snapshots. It deliberately contains no
domain decision logic: the Compliance Engine and AI Verification
Engine keep owning domain semantics.

Ownership summary (see ``docs/storage-architecture.md``):

- **PostgreSQL** is the durable source of truth for structured records.
- **Redis** is the transient coordination layer (queue, leases, retry
  scheduling, short-lived idempotency markers). It is never the durable
  source of truth.
- **Artifact storage** holds immutable document binaries; Postgres
  holds only references and content hashes.
- **Process memory** holds nothing that must survive a crash.
"""

from infrastructure.persistence.records import (
    AuditEventRecord,
    BidderRecord,
    ComplianceResultRecord,
    DocumentRecord,
    EvidenceRecord,
    ExplanationRecord,
    FindingRecord,
    FlagSnapshotRecord,
    FlagStateRecord,
    OutboxEventRecord,
    ProcessingJobRecord,
    SubmissionRecord,
    VerificationRecord,
)
from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork
from infrastructure.jobs.queue import InMemoryJobQueue, JobQueue
from infrastructure.jobs.models import Job, JobState
from infrastructure.pipeline import ProcessingStage
from infrastructure.artifacts import InMemoryArtifactStore, ArtifactStore
from infrastructure.flags import BidderFlagSnapshot, materialize_flag_snapshot
from infrastructure.processing import ProcessingCoordinator
from infrastructure.outbox import OutboxPublisher
from infrastructure.settings import InfrastructureSettings

__all__ = [
    "ArtifactStore",
    "AuditEventRecord",
    "BidderFlagSnapshot",
    "BidderRecord",
    "ComplianceResultRecord",
    "DocumentRecord",
    "EvidenceRecord",
    "ExplanationRecord",
    "FindingRecord",
    "FlagSnapshotRecord",
    "FlagStateRecord",
    "InMemoryArtifactStore",
    "InMemoryJobQueue",
    "InMemoryUnitOfWork",
    "InfrastructureSettings",
    "Job",
    "JobQueue",
    "JobState",
    "OutboxEventRecord",
    "OutboxPublisher",
    "ProcessingCoordinator",
    "ProcessingJobRecord",
    "ProcessingStage",
    "SubmissionRecord",
    "VerificationRecord",
    "materialize_flag_snapshot",
]
