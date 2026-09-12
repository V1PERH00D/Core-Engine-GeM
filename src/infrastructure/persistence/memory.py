"""In-memory repository implementations honouring the durable invariants.

These reproduce PostgreSQL's PRIMARY KEY / UNIQUE / FOREIGN KEY
semantics deterministically so the normal test suite runs with no
database. Every write returns a deep copy; callers cannot mutate stored
state through a returned record.
"""

from __future__ import annotations

import copy
import threading
from typing import Any

from infrastructure.persistence.errors import (
    DuplicateRecordError,
    MissingReferenceError,
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
)


class _Store:
    """All durable tables held in process memory."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.bidders: dict[str, BidderRecord] = {}
        self.submissions: dict[str, SubmissionRecord] = {}
        self.documents: dict[str, DocumentRecord] = {}
        self.evidence: dict[str, EvidenceRecord] = {}
        self.verifications: dict[str, VerificationRecord] = {}
        self.compliance_results: dict[tuple[str, str], ComplianceResultRecord] = {}
        self.findings: dict[str, FindingRecord] = {}
        self.explanations: dict[str, ExplanationRecord] = {}
        self.jobs: dict[str, ProcessingJobRecord] = {}
        self.jobs_by_idem: dict[str, str] = {}
        self.audit_events: list[AuditEventRecord] = []
        self.outbox: dict[str, OutboxEventRecord] = {}
        self.flag_states: dict[tuple[str, str], FlagStateRecord] = {}
        self.flag_snapshots: dict[str, FlagSnapshotRecord] = {}

    def tables(self) -> dict[str, Any]:
        return {
            "bidders": self.bidders,
            "submissions": self.submissions,
            "documents": self.documents,
            "evidence": self.evidence,
            "verifications": self.verifications,
            "compliance_results": self.compliance_results,
            "findings": self.findings,
            "explanations": self.explanations,
            "jobs": self.jobs,
            "jobs_by_idem": self.jobs_by_idem,
            "audit_events": self.audit_events,
            "outbox": self.outbox,
            "flag_states": self.flag_states,
            "flag_snapshots": self.flag_snapshots,
        }

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.tables())

    def restore(self, snap: dict[str, Any]) -> None:
        current = self.tables()
        for name, table in current.items():
            table.clear()
            if isinstance(snap[name], dict):
                table.update(snap[name])
            elif isinstance(snap[name], list):
                table.extend(snap[name])


class _Repo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    def _require(self, table: dict[Any, Any], key: Any, desc: str) -> Any:
        if key not in table:
            raise MissingReferenceError(f"Unknown {desc} {key!r}.")
        return table[key]
class InMemoryBidderRepository(_Repo):
    def add(self, record: BidderRecord) -> BidderRecord:
        with self._s.lock:
            if record.bidder_id in self._s.bidders:
                raise DuplicateRecordError(
                    f"Bidder {record.bidder_id!r} already exists."
                )
            self._s.bidders[record.bidder_id] = record.model_copy(deep=True)
            return record.model_copy(deep=True)

    def get(self, bidder_id: str) -> BidderRecord | None:
        with self._s.lock:
            rec = self._s.bidders.get(bidder_id)
            return None if rec is None else rec.model_copy(deep=True)


class InMemorySubmissionRepository(_Repo):
    def add(self, record: SubmissionRecord) -> SubmissionRecord:
        with self._s.lock:
            self._require(self._s.bidders, record.bidder_id, "bidder")
            if record.submission_id in self._s.submissions:
                raise DuplicateRecordError(
                    f"Submission {record.submission_id!r} already exists."
                )
            self._s.submissions[record.submission_id] = record.model_copy(deep=True)
            return record.model_copy(deep=True)

    def get(self, submission_id: str) -> SubmissionRecord | None:
        with self._s.lock:
            rec = self._s.submissions.get(submission_id)
            return None if rec is None else rec.model_copy(deep=True)

    def save(self, record: SubmissionRecord) -> SubmissionRecord:
        with self._s.lock:
            if record.submission_id not in self._s.submissions:
                self._require(self._s.bidders, record.bidder_id, "bidder")
            self._s.submissions[record.submission_id] = record.model_copy(deep=True)
            return record.model_copy(deep=True)

    def list_by_bidder(self, bidder_id: str) -> list[SubmissionRecord]:
        with self._s.lock:
            return [
                r.model_copy(deep=True)
                for r in self._s.submissions.values()
                if r.bidder_id == bidder_id
            ]


class InMemoryDocumentRepository(_Repo):
    def add(self, record: DocumentRecord) -> DocumentRecord:
        with self._s.lock:
            self._require(self._s.bidders, record.bidder_id, "bidder")
            if record.document_id in self._s.documents:
                raise DuplicateRecordError(
                    f"Document {record.document_id!r} already exists."
                )
            if record.submission_id is not None:
                self._require(
                    self._s.submissions, record.submission_id, "submission"
                )
            self._s.documents[record.document_id] = record.model_copy(deep=True)
            return record.model_copy(deep=True)

    def get(self, document_id: str) -> DocumentRecord | None:
        with self._s.lock:
            rec = self._s.documents.get(document_id)
            return None if rec is None else rec.model_copy(deep=True)

    def list_by_submission(self, submission_id: str) -> list[DocumentRecord]:
        with self._s.lock:
            return [
                r.model_copy(deep=True)
                for r in self._s.documents.values()
                if r.submission_id == submission_id
            ]

    def list_by_bidder(self, bidder_id: str) -> list[DocumentRecord]:
        with self._s.lock:
            return [
                r.model_copy(deep=True)
                for r in self._s.documents.values()
                if r.bidder_id == bidder_id
            ]


class InMemoryEvidenceRepository(_Repo):
    def add(self, record: EvidenceRecord) -> EvidenceRecord:
        with self._s.lock:
            self._require(self._s.bidders, record.bidder_id, "bidder")
            self._require(self._s.documents, record.document_id, "document")
            if record.evidence_id in self._s.evidence:
                raise DuplicateRecordError(
                    f"Evidence {record.evidence_id!r} already exists."
                )
            self._s.evidence[record.evidence_id] = record.model_copy(deep=True)
            return record.model_copy(deep=True)

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        with self._s.lock:
            rec = self._s.evidence.get(evidence_id)
            return None if rec is None else rec.model_copy(deep=True)

    def list_by_bidder(self, bidder_id: str) -> list[EvidenceRecord]:
        with self._s.lock:
            return [
                r.model_copy(deep=True)
                for r in self._s.evidence.values()
                if r.bidder_id == bidder_id
            ]

    def list_by_document(self, document_id: str) -> list[EvidenceRecord]:
        with self._s.lock:
            return [
                r.model_copy(deep=True)
                for r in self._s.evidence.values()
                if r.document_id == document_id
            ]


class InMemoryVerificationRepository(_Repo):
    def save(self, record: VerificationRecord) -> VerificationRecord:
        with self._s.lock:
            self._require(self._s.bidders, record.bidder_id, "bidder")
            if record.evidence_id is not None:
                self._require(self._s.evidence, record.evidence_id, "evidence")
            if record.document_id is not None:
                self._require(self._s.documents, record.document_id, "document")
            self._s.verifications[record.verification_id] = record.model_copy(
                deep=True
            )
            return record.model_copy(deep=True)

    def get(self, verification_id: str) -> VerificationRecord | None:
        with self._s.lock:
            rec = self._s.verifications.get(verification_id)
            return None if rec is None else rec.model_copy(deep=True)

    def list_by_bidder(self, bidder_id: str) -> list[VerificationRecord]:
        with self._s.lock:
            return [
                r.model_copy(deep=True)
                for r in self._s.verifications.values()
                if r.bidder_id == bidder_id
            ]


class InMemoryComplianceResultRepository(_Repo):
    def save(self, record: ComplianceResultRecord) -> ComplianceResultRecord:
        with self._s.lock:
            self._require(self._s.bidders, record.bidder_id, "bidder")
            self._s.compliance_results[
                (record.bidder_id, record.requirement_id)
            ] = record.model_copy(deep=True)
            return record.model_copy(deep=True)

    def get(
        self, bidder_id: str, requirement_id: str
    ) -> ComplianceResultRecord | None:
        with self._s.lock:
            rec = self._s.compliance_results.get(
                (bidder_id, requirement_id)
            )
            return None if rec is None else rec.model_copy(deep=True)

    def list_by_bidder(self, bidder_id: str) -> list[ComplianceResultRecord]:
        with self._s.lock:
            return [
                r.model_copy(deep=True)
                for (b, _req), r in self._s.compliance_results.items()
                if b == bidder_id
            ]


class InMemoryFindingRepository(_Repo):
    def save(self, record: FindingRecord) -> FindingRecord:
        with self._s.lock:
            self._require(self._s.bidders, record.bidder_id, "bidder")
            self._s.findings[record.finding_id] = record.model_copy(deep=True)
            return record.model_copy(deep=True)

    def get(self, finding_id: str) -> FindingRecord | None:
        with self._s.lock:
            rec = self._s.findings.get(finding_id)
            return None if rec is None else rec.model_copy(deep=True)

    def list_by_bidder(self, bidder_id: str) -> list[FindingRecord]:
        with self._s.lock:
            return [
                r.model_copy(deep=True)
                for r in self._s.findings.values()
                if r.bidder_id == bidder_id
            ]

    def list_by_flag(
        self, bidder_id: str, flag_id: str
    ) -> list[FindingRecord]:
        with self._s.lock:
            return [
                r.model_copy(deep=True)
                for r in self._s.findings.values()
                if r.bidder_id == bidder_id and r.flag_id == flag_id
            ]


class InMemoryExplanationRepository(_Repo):
    def save(self, record: ExplanationRecord) -> ExplanationRecord:
        with self._s.lock:
            self._require(self._s.bidders, record.bidder_id, "bidder")
            for ref in record.finding_refs:
                self._require(self._s.findings, ref, "finding")
            self._s.explanations[record.explanation_id] = record.model_copy(
                deep=True
            )
            return record.model_copy(deep=True)

    def get(self, explanation_id: str) -> ExplanationRecord | None:
        with self._s.lock:
            rec = self._s.explanations.get(explanation_id)
            return None if rec is None else rec.model_copy(deep=True)

    def list_by_flag(
        self, bidder_id: str, flag_id: str
    ) -> list[ExplanationRecord]:
        with self._s.lock:
            return [
                r.model_copy(deep=True)
                for r in self._s.explanations.values()
                if r.bidder_id == bidder_id and r.flag_id == flag_id
            ]

    def list_by_bidder(self, bidder_id: str) -> list[ExplanationRecord]:
        with self._s.lock:
            return [
                r.model_copy(deep=True)
                for r in self._s.explanations.values()
                if r.bidder_id == bidder_id
            ]
class InMemoryJobRepository(_Repo):
    def save(self, record: ProcessingJobRecord) -> ProcessingJobRecord:
        with self._s.lock:
            self._s.jobs[record.job_id] = record.model_copy(deep=True)
            if record.idempotency_key is not None:
                self._s.jobs_by_idem[record.idempotency_key] = record.job_id
            return record.model_copy(deep=True)

    def get(self, job_id: str) -> ProcessingJobRecord | None:
        with self._s.lock:
            rec = self._s.jobs.get(job_id)
            return None if rec is None else rec.model_copy(deep=True)

    def find_by_idempotency_key(
        self, key: str
    ) -> ProcessingJobRecord | None:
        with self._s.lock:
            job_id = self._s.jobs_by_idem.get(key)
            if job_id is None:
                return None
            rec = self._s.jobs.get(job_id)
            return None if rec is None else rec.model_copy(deep=True)

    def list_by_submission(
        self, submission_id: str
    ) -> list[ProcessingJobRecord]:
        with self._s.lock:
            return [
                r.model_copy(deep=True)
                for r in self._s.jobs.values()
                if r.submission_id == submission_id
            ]


class InMemoryAuditRepository(_Repo):
    def add(self, record: AuditEventRecord) -> AuditEventRecord:
        with self._s.lock:
            if any(
                e.event_id == record.event_id for e in self._s.audit_events
            ):
                raise DuplicateRecordError(
                    f"Audit event {record.event_id!r} already exists."
                )
            self._s.audit_events.append(record.model_copy(deep=True))
            return record.model_copy(deep=True)

    def list_for(
        self, aggregate_type: str, aggregate_id: str
    ) -> list[AuditEventRecord]:
        with self._s.lock:
            return [
                e.model_copy(deep=True)
                for e in self._s.audit_events
                if e.aggregate_type == aggregate_type
                and e.aggregate_id == aggregate_id
            ]

    def list_by_correlation(self, correlation_id: str) -> list[AuditEventRecord]:
        with self._s.lock:
            return [
                e.model_copy(deep=True)
                for e in self._s.audit_events
                if e.correlation_id == correlation_id
            ]


class InMemoryOutboxRepository(_Repo):
    def add(self, record: OutboxEventRecord) -> OutboxEventRecord:
        with self._s.lock:
            if record.event_id in self._s.outbox:
                raise DuplicateRecordError(
                    f"Outbox event {record.event_id!r} already exists."
                )
            self._s.outbox[record.event_id] = record.model_copy(deep=True)
            return record.model_copy(deep=True)

    def list_unpublished(self, limit: int = 100) -> list[OutboxEventRecord]:
        with self._s.lock:
            events = sorted(
                (e for e in self._s.outbox.values() if e.published_at is None),
                key=lambda e: (e.created_at, e.event_id),
            )
            return [e.model_copy(deep=True) for e in events[:limit]]

    def record_attempt(self, event_id: str) -> None:
        with self._s.lock:
            rec = self._s.outbox.get(event_id)
            if rec is None:
                raise MissingReferenceError(
                    f"Unknown outbox event {event_id!r}."
                )
            self._s.outbox[event_id] = rec.model_copy(
                update={"attempts": rec.attempts + 1}
            )

    def mark_published(self, event_id: str, published_at: float) -> bool:
        with self._s.lock:
            rec = self._s.outbox.get(event_id)
            if rec is None:
                raise MissingReferenceError(
                    f"Unknown outbox event {event_id!r}."
                )
            if rec.published_at is not None:
                return False
            self._s.outbox[event_id] = rec.model_copy(
                update={
                    "published_at": published_at,
                    "attempts": rec.attempts + 1,
                }
            )
            return True


class InMemoryFlagRepository(_Repo):
    def save_state(self, record: FlagStateRecord) -> FlagStateRecord:
        with self._s.lock:
            self._require(self._s.bidders, record.bidder_id, "bidder")
            self._s.flag_states[
                (record.bidder_id, record.flag_id)
            ] = record.model_copy(deep=True)
            return record.model_copy(deep=True)

    def get_state(self, bidder_id: str, flag_id: str) -> FlagStateRecord | None:
        with self._s.lock:
            rec = self._s.flag_states.get((bidder_id, flag_id))
            return None if rec is None else rec.model_copy(deep=True)

    def list_states(self, bidder_id: str) -> list[FlagStateRecord]:
        with self._s.lock:
            return [
                r.model_copy(deep=True)
                for (b, _f), r in self._s.flag_states.items()
                if b == bidder_id
            ]

    def save_snapshot(self, record: FlagSnapshotRecord) -> FlagSnapshotRecord:
        with self._s.lock:
            self._require(self._s.bidders, record.bidder_id, "bidder")
            self._s.flag_snapshots[record.snapshot_id] = record.model_copy(
                deep=True
            )
            return record.model_copy(deep=True)

    def get_snapshot(self, snapshot_id: str) -> FlagSnapshotRecord | None:
        with self._s.lock:
            rec = self._s.flag_snapshots.get(snapshot_id)
            return None if rec is None else rec.model_copy(deep=True)

    def list_snapshots(self, bidder_id: str) -> list[FlagSnapshotRecord]:
        with self._s.lock:
            return [
                r.model_copy(deep=True)
                for r in self._s.flag_snapshots.values()
                if r.bidder_id == bidder_id
            ]


# ---------------------------------------------------------------------------
# Repository bundle (used by the unit of work)
# ---------------------------------------------------------------------------


class InMemoryRepositories:
    def __init__(self, store: _Store) -> None:
        self.bidders = InMemoryBidderRepository(store)
        self.submissions = InMemorySubmissionRepository(store)
        self.documents = InMemoryDocumentRepository(store)
        self.evidence = InMemoryEvidenceRepository(store)
        self.verifications = InMemoryVerificationRepository(store)
        self.compliance_results = InMemoryComplianceResultRepository(store)
        self.findings = InMemoryFindingRepository(store)
        self.explanations = InMemoryExplanationRepository(store)
        self.jobs = InMemoryJobRepository(store)
        self.audit = InMemoryAuditRepository(store)
        self.outbox = InMemoryOutboxRepository(store)
        self.flags = InMemoryFlagRepository(store)


__all__ = [
    "InMemoryRepositories",
    "InMemoryBidderRepository",
    "InMemorySubmissionRepository",
    "InMemoryDocumentRepository",
    "InMemoryEvidenceRepository",
    "InMemoryVerificationRepository",
    "InMemoryComplianceResultRepository",
    "InMemoryFindingRepository",
    "InMemoryExplanationRepository",
    "InMemoryJobRepository",
    "InMemoryAuditRepository",
    "InMemoryOutboxRepository",
    "InMemoryFlagRepository",
]