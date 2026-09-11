"""Durable persistence (PostgreSQL + typed records + repositories).

This package owns the *durable source of truth*: structured records,
repository boundaries, the transactional unit of work, PostgreSQL
migrations, and the outbox. It never opens connections implicitly —
every adapter receives its connection/client from the caller.

The in-memory implementations (:mod:`infrastructure.persistence.memory`)
enforce the *same* invariants as PostgreSQL (primary keys, foreign keys,
unique constraints, upsert idempotency) so the test suite can run
without a database.
"""

from infrastructure.persistence.errors import (
    DuplicateRecordError,
    IntegrityError,
    MissingReferenceError,
    RecordNotFoundError,
)
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
    to_job_record,
    to_job_model,
)
from infrastructure.persistence.unit_of_work import (
    InMemoryUnitOfWork,
    UnitOfWork,
)

__all__ = [
    "AuditEventRecord",
    "BidderRecord",
    "ComplianceResultRecord",
    "DocumentRecord",
    "DuplicateRecordError",
    "EvidenceRecord",
    "ExplanationRecord",
    "FindingRecord",
    "FlagSnapshotRecord",
    "FlagStateRecord",
    "InMemoryUnitOfWork",
    "IntegrityError",
    "MissingReferenceError",
    "OutboxEventRecord",
    "ProcessingJobRecord",
    "RecordNotFoundError",
    "SubmissionRecord",
    "UnitOfWork",
    "VerificationRecord",
    "to_job_model",
    "to_job_record",
]