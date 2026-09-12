"""PostgreSQL repository/adapter implementations.

These honour the same repository protocols as the in-memory
implementations. They receive a :class:`psycopg.Connection` from the
caller; nothing here fabricates credentials or opens connections.

JSON columns are stored/loaded as ``JSONB`` via psycopg 3's automatic
conversion; all timestamps are POSIX epoch seconds (UTC floats) for
parity with the queue/lease layer.

The ``PostgresUnitOfWork`` wraps a single psycopg transaction so that a
domain write and its outbox insert share one commit/rollback boundary.
"""

from __future__ import annotations

from typing import Any

from infrastructure.persistence.errors import (
    DuplicateRecordError,
    IntegrityError,
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
from infrastructure.persistence.schema import MIGRATIONS


def _j(value: Any) -> Any:
    """Adapt a Python value for a JSONB column."""
    if value is None:
        return None
    try:
        from psycopg.types.json import Jsonb
    except Exception:  # pragma: no cover
        return value
    try:
        return Jsonb(value)
    except TypeError:
        return value


def _translate(exc: Exception, *, dedupe_desc: str | None = None) -> None:
    """Translate psycopg integrity errors into domain exceptions."""
    try:
        from psycopg import errors as pg_errors
    except Exception:  # pragma: no cover
        pg_errors = None

    if pg_errors is not None:
        sqlstate = getattr(exc, "sqlstate", None)
        if sqlstate is not None and hasattr(pg_errors, "UNIQUE_VIOLATION"):
            if sqlstate == pg_errors.UNIQUE_VIOLATION.sqlstate:
                raise DuplicateRecordError(
                    dedupe_desc or "Unique constraint violated."
                ) from exc
        if sqlstate is not None and hasattr(pg_errors, "FOREIGN_KEY_VIOLATION"):
            if sqlstate == pg_errors.FOREIGN_KEY_VIOLATION.sqlstate:
                raise MissingReferenceError(
                    "Foreign key constraint violated."
                ) from exc
    raise IntegrityError(str(exc)) from exc


def apply_migrations(conn: Any) -> list[int]:
    """Apply all unapplied migrations to ``conn``."""
    applied: list[int] = []
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        )
        cur.execute("SELECT version FROM schema_migrations")
        seen = {row[0] for row in cur.fetchall()}
        for migration in MIGRATIONS:
            if migration.version in seen:
                continue
            cur.execute(migration.sql)
            cur.execute(
                "INSERT INTO schema_migrations (version, name) "
                "VALUES (%s, %s)",
                (migration.version, migration.name),
            )
            applied.append(migration.version)
        conn.commit()
    return applied


class PostgresUnitOfWork:
    """Wraps a psycopg connection as a transaction boundary."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self._repos = PostgresRepositories(conn)

    @property
    def repos(self):
        return self._repos

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self.rollback()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        return False


class PostgresRepositories:
    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self.bidders = PostgresBidderRepository(conn)
        self.submissions = PostgresSubmissionRepository(conn)
        self.documents = PostgresDocumentRepository(conn)
        self.evidence = PostgresEvidenceRepository(conn)
        self.verifications = PostgresVerificationRepository(conn)
        self.compliance_results = PostgresComplianceResultRepository(conn)
        self.findings = PostgresFindingRepository(conn)
        self.explanations = PostgresExplanationRepository(conn)
        self.jobs = PostgresJobRepository(conn)
        self.audit = PostgresAuditRepository(conn)
        self.outbox = PostgresOutboxRepository(conn)
        self.flags = PostgresFlagRepository(conn)


class PostgresBidderRepository:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def add(self, record: BidderRecord) -> BidderRecord:
        with self._conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO bidders (bidder_id, created_at, updated_at) "
                    "VALUES (%s, %s, %s)",
                    (record.bidder_id, record.created_at, record.updated_at),
                )
            except Exception as exc:
                _translate(exc, dedupe_desc=f"Bidder {record.bidder_id!r}")
        return record

    def get(self, bidder_id: str) -> BidderRecord | None:
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT bidder_id, created_at, updated_at "
                "FROM bidders WHERE bidder_id = %s",
                (bidder_id,),
            )
            row = cur.fetchone()
        return None if row is None else BidderRecord(**row)


_SUBMISSION_SELECT = (
    "SELECT submission_id, bidder_id, stage, last_completed_stage, "
    "correlation_id, attempt_count, last_error, last_error_kind, "
    "created_at, updated_at FROM submissions"
)


def _submission_params(r: SubmissionRecord):
    return (
        r.submission_id,
        r.bidder_id,
        r.stage,
        r.last_completed_stage,
        r.correlation_id,
        r.attempt_count,
        r.last_error,
        r.last_error_kind,
        r.created_at,
        r.updated_at,
    )


class PostgresSubmissionRepository:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def add(self, record: SubmissionRecord) -> SubmissionRecord:
        with self._conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO submissions "
                    "(submission_id, bidder_id, stage, last_completed_stage, "
                    "correlation_id, attempt_count, last_error, last_error_kind, "
                    "created_at, updated_at) VALUES "
                    "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    _submission_params(record),
                )
            except Exception as exc:
                _translate(exc, dedupe_desc=f"Submission {record.submission_id!r}")
        return record

    def get(self, submission_id: str) -> SubmissionRecord | None:
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                _SUBMISSION_SELECT + " WHERE submission_id = %s",
                (submission_id,),
            )
            row = cur.fetchone()
        return None if row is None else SubmissionRecord(**row)

    def save(self, record: SubmissionRecord) -> SubmissionRecord:
        with self._conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO submissions "
                    "(submission_id, bidder_id, stage, last_completed_stage, "
                    "correlation_id, attempt_count, last_error, last_error_kind, "
                    "created_at, updated_at) VALUES "
                    "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (submission_id) DO UPDATE SET "
                    "stage = EXCLUDED.stage, "
                    "last_completed_stage = EXCLUDED.last_completed_stage, "
                    "correlation_id = EXCLUDED.correlation_id, "
                    "attempt_count = EXCLUDED.attempt_count, "
                    "last_error = EXCLUDED.last_error, "
                    "last_error_kind = EXCLUDED.last_error_kind, "
                    "updated_at = EXCLUDED.updated_at",
                    _submission_params(record),
                )
            except Exception as exc:
                _translate(exc)
        return record

    def list_by_bidder(self, bidder_id: str) -> list[SubmissionRecord]:
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                _SUBMISSION_SELECT + " WHERE bidder_id = %s ORDER BY created_at",
                (bidder_id,),
            )
            return [SubmissionRecord(**row) for row in cur.fetchall()]


class PostgresDocumentRepository:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def add(self, record: DocumentRecord) -> DocumentRecord:
        with self._conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO documents (document_id, submission_id, "
                    "bidder_id, document_type, artifact_id, content_hash, "
                    "metadata, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        record.document_id,
                        record.submission_id,
                        record.bidder_id,
                        record.document_type,
                        record.artifact_id,
                        record.content_hash,
                        _j(record.metadata),
                        record.created_at,
                    ),
                )
            except Exception as exc:
                _translate(exc, dedupe_desc=f"Document {record.document_id!r}")
        return record

    def _select(self):
        return (
            "SELECT document_id, submission_id, bidder_id, document_type, "
            "artifact_id, content_hash, metadata, created_at FROM documents"
        )

    def _one(self, sql, params):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return None if row is None else DocumentRecord(**row)

    def _many(self, sql, params):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return [DocumentRecord(**row) for row in cur.fetchall()]

    def get(self, document_id: str) -> DocumentRecord | None:
        return self._one(self._select() + " WHERE document_id = %s", (document_id,))

    def list_by_submission(self, submission_id: str) -> list[DocumentRecord]:
        return self._many(
            self._select() + " WHERE submission_id = %s ORDER BY created_at",
            (submission_id,),
        )

    def list_by_bidder(self, bidder_id: str) -> list[DocumentRecord]:
        return self._many(
            self._select() + " WHERE bidder_id = %s ORDER BY created_at",
            (bidder_id,),
        )


class PostgresEvidenceRepository:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def add(self, record: EvidenceRecord) -> EvidenceRecord:
        with self._conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO evidence (evidence_id, bidder_id, document_id, "
                    "field_name, document_type, value, confidence, page, bbox, "
                    "created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        record.evidence_id,
                        record.bidder_id,
                        record.document_id,
                        record.field_name,
                        record.document_type,
                        _j(record.value),
                        record.confidence,
                        record.page,
                        _j(record.bbox),
                        record.created_at,
                    ),
                )
            except Exception as exc:
                _translate(exc, dedupe_desc=f"Evidence {record.evidence_id!r}")
        return record

    _SELECT = (
        "SELECT evidence_id, bidder_id, document_id, field_name, document_type, "
        "value, confidence, page, bbox, created_at FROM evidence"
    )

    def _one(self, sql, params):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return None if row is None else EvidenceRecord(**row)

    def _many(self, sql, params):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return [EvidenceRecord(**row) for row in cur.fetchall()]

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        return self._one(self._SELECT + " WHERE evidence_id = %s", (evidence_id,))

    def list_by_bidder(self, bidder_id: str) -> list[EvidenceRecord]:
        return self._many(
            self._SELECT + " WHERE bidder_id = %s ORDER BY created_at",
            (bidder_id,),
        )

    def list_by_document(self, document_id: str) -> list[EvidenceRecord]:
        return self._many(
            self._SELECT + " WHERE document_id = %s ORDER BY created_at",
            (document_id,),
        )


class PostgresVerificationRepository:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    _SELECT = (
        "SELECT verification_id, bidder_id, capability, source, "
        "queried_identifier, status, data, query, raw_response, retrieved_at, "
        "latency_ms, correlation_id, transport_status_code, evidence_id, "
        "document_id, created_at FROM verifications"
    )

    def save(self, record: VerificationRecord) -> VerificationRecord:
        cols = (
            "verification_id, bidder_id, capability, source, queried_identifier, "
            "status, data, query, raw_response, retrieved_at, latency_ms, "
            "correlation_id, transport_status_code, evidence_id, document_id, "
            "created_at"
        )
        params = (
            record.verification_id,
            record.bidder_id,
            record.capability,
            record.source,
            record.queried_identifier,
            record.status,
            _j(record.data),
            _j(record.query),
            _j(record.raw_response),
            record.retrieved_at,
            record.latency_ms,
            record.correlation_id,
            record.transport_status_code,
            record.evidence_id,
            record.document_id,
            record.created_at,
        )
        with self._conn.cursor() as cur:
            try:
                cur.execute(
                    f"INSERT INTO verifications ({cols}) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (verification_id) DO UPDATE SET "
                    "data = EXCLUDED.data, query = EXCLUDED.query, "
                    "raw_response = EXCLUDED.raw_response, status = EXCLUDED.status",
                    params,
                )
            except Exception as exc:
                _translate(exc)
        return record

    def _one(self, sql, params):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return None if row is None else VerificationRecord(**row)

    def _many(self, sql, params):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return [VerificationRecord(**row) for row in cur.fetchall()]

    def get(self, verification_id: str) -> VerificationRecord | None:
        return self._one(self._SELECT + " WHERE verification_id = %s", (verification_id,))

    def list_by_bidder(self, bidder_id: str) -> list[VerificationRecord]:
        return self._many(
            self._SELECT + " WHERE bidder_id = %s ORDER BY retrieved_at",
            (bidder_id,),
        )


class PostgresComplianceResultRepository:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    _SELECT = (
        "SELECT result_id, bidder_id, requirement_id, capability, status, "
        "reason, expected, actual, rule_id, evidence_refs, verification_refs, "
        "flags, created_at, updated_at FROM compliance_results"
    )

    def save(self, record: ComplianceResultRecord) -> ComplianceResultRecord:
        cols = (
            "result_id, bidder_id, requirement_id, capability, status, reason, "
            "expected, actual, rule_id, evidence_refs, verification_refs, "
            "flags, created_at, updated_at"
        )
        params = (
            record.result_id,
            record.bidder_id,
            record.requirement_id,
            record.capability,
            record.status,
            record.reason,
            _j(record.expected),
            _j(record.actual),
            record.rule_id,
            _j(record.evidence_refs),
            _j(record.verification_refs),
            _j(record.flags),
            record.created_at,
            record.updated_at,
        )
        with self._conn.cursor() as cur:
            try:
                cur.execute(
                    f"INSERT INTO compliance_results ({cols}) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (bidder_id, requirement_id) DO UPDATE SET "
                    "result_id = EXCLUDED.result_id, "
                    "capability = EXCLUDED.capability, "
                    "status = EXCLUDED.status, reason = EXCLUDED.reason, "
                    "expected = EXCLUDED.expected, actual = EXCLUDED.actual, "
                    "rule_id = EXCLUDED.rule_id, "
                    "evidence_refs = EXCLUDED.evidence_refs, "
                    "verification_refs = EXCLUDED.verification_refs, "
                    "flags = EXCLUDED.flags, updated_at = EXCLUDED.updated_at",
                    params,
                )
            except Exception as exc:
                _translate(exc)
        return record

    def _one(self, sql, params):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return None if row is None else ComplianceResultRecord(**row)

    def _many(self, sql, params):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return [ComplianceResultRecord(**row) for row in cur.fetchall()]

    def get(self, bidder_id, requirement_id):
        return self._one(
            self._SELECT + " WHERE bidder_id = %s AND requirement_id = %s",
            (bidder_id, requirement_id),
        )

    def list_by_bidder(self, bidder_id):
        return self._many(
            self._SELECT + " WHERE bidder_id = %s ORDER BY requirement_id",
            (bidder_id,),
        )


class PostgresFindingRepository:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    _SELECT = (
        "SELECT finding_id, bidder_id, finding_type, flag_id, payload, "
        "evidence_refs, verification_refs, related_bidder_ids, created_at "
        "FROM findings"
    )

    def save(self, record: FindingRecord) -> FindingRecord:
        cols = (
            "finding_id, bidder_id, finding_type, flag_id, payload, "
            "evidence_refs, verification_refs, related_bidder_ids, created_at"
        )
        params = (
            record.finding_id,
            record.bidder_id,
            record.finding_type,
            record.flag_id,
            _j(record.payload),
            _j(record.evidence_refs),
            _j(record.verification_refs),
            _j(record.related_bidder_ids),
            record.created_at,
        )
        with self._conn.cursor() as cur:
            try:
                cur.execute(
                    f"INSERT INTO findings ({cols}) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (finding_id) DO UPDATE SET "
                    "payload = EXCLUDED.payload, "
                    "finding_type = EXCLUDED.finding_type, "
                    "flag_id = EXCLUDED.flag_id, "
                    "evidence_refs = EXCLUDED.evidence_refs, "
                    "verification_refs = EXCLUDED.verification_refs, "
                    "related_bidder_ids = EXCLUDED.related_bidder_ids",
                    params,
                )
            except Exception as exc:
                _translate(exc)
        return record

    def _one(self, sql, params):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return None if row is None else FindingRecord(**row)

    def _many(self, sql, params):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return [FindingRecord(**row) for row in cur.fetchall()]

    def get(self, finding_id):
        return self._one(self._SELECT + " WHERE finding_id = %s", (finding_id,))

    def list_by_bidder(self, bidder_id):
        return self._many(
            self._SELECT + " WHERE bidder_id = %s ORDER BY created_at",
            (bidder_id,),
        )

    def list_by_flag(self, bidder_id, flag_id):
        return self._many(
            self._SELECT + " WHERE bidder_id = %s AND flag_id = %s ORDER BY created_at",
            (bidder_id, flag_id),
        )


class PostgresExplanationRepository:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    _SELECT = (
        "SELECT explanation_id, bidder_id, flag_id, flag_active, finding_refs, "
        "concise_text, detailed_text, grounding, generation, created_at, "
        "schema_version, grounding_version, validation_status, fallback_used, "
        "input_hash, evidence_refs, verification_refs, document_refs, "
        "comparison_refs, trace_refs, content, uncertainties, review_actions "
        "FROM explanations"
    )

    def save(self, record: ExplanationRecord) -> ExplanationRecord:
        cols = (
            "explanation_id, bidder_id, flag_id, flag_active, finding_refs, "
            "concise_text, detailed_text, grounding, generation, created_at, "
            "schema_version, grounding_version, validation_status, fallback_used, "
            "input_hash, evidence_refs, verification_refs, document_refs, "
            "comparison_refs, trace_refs, content, uncertainties, review_actions"
        )
        params = (
            record.explanation_id,
            record.bidder_id,
            record.flag_id,
            record.flag_active,
            _j(record.finding_refs),
            record.concise_text,
            record.detailed_text,
            _j(record.grounding),
            _j(record.generation),
            record.created_at,
            record.schema_version,
            record.grounding_version,
            record.validation_status,
            record.fallback_used,
            record.input_hash,
            _j(record.evidence_refs),
            _j(record.verification_refs),
            _j(record.document_refs),
            _j(record.comparison_refs),
            _j(record.trace_refs),
            _j(record.content),
            _j(record.uncertainties),
            _j(record.review_actions),
        )
        update_cols = (
            "concise_text = EXCLUDED.concise_text, "
            "detailed_text = EXCLUDED.detailed_text, "
            "grounding = EXCLUDED.grounding, "
            "generation = EXCLUDED.generation, "
            "schema_version = EXCLUDED.schema_version, "
            "grounding_version = EXCLUDED.grounding_version, "
            "validation_status = EXCLUDED.validation_status, "
            "fallback_used = EXCLUDED.fallback_used, "
            "input_hash = EXCLUDED.input_hash, "
            "evidence_refs = EXCLUDED.evidence_refs, "
            "verification_refs = EXCLUDED.verification_refs, "
            "document_refs = EXCLUDED.document_refs, "
            "comparison_refs = EXCLUDED.comparison_refs, "
            "trace_refs = EXCLUDED.trace_refs, "
            "content = EXCLUDED.content, "
            "uncertainties = EXCLUDED.uncertainties, "
            "review_actions = EXCLUDED.review_actions"
        )
        placeholders = ",".join(["%s"] * 23)
        with self._conn.cursor() as cur:
            try:
                cur.execute(
                    f"INSERT INTO explanations ({cols}) "
                    f"VALUES ({placeholders}) "
                    f"ON CONFLICT (explanation_id) DO UPDATE SET {update_cols}",
                    params,
                )
            except Exception as exc:
                _translate(exc)
        return record

    def _one(self, sql, params):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return None if row is None else ExplanationRecord(**row)

    def _many(self, sql, params):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return [ExplanationRecord(**row) for row in cur.fetchall()]

    def get(self, explanation_id):
        return self._one(self._SELECT + " WHERE explanation_id = %s", (explanation_id,))

    def list_by_flag(self, bidder_id, flag_id):
        return self._many(
            self._SELECT + " WHERE bidder_id = %s AND flag_id = %s ORDER BY created_at",
            (bidder_id, flag_id),
        )

    def list_by_bidder(self, bidder_id):
        return self._many(
            self._SELECT + " WHERE bidder_id = %s ORDER BY created_at",
            (bidder_id,),
        )


class PostgresJobRepository:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    _SELECT = (
        "SELECT job_id, idempotency_key, submission_id, bidder_id, job_type, "
        "stage, correlation_id, payload, state, attempt_count, max_attempts, "
        "leased_by, lease_expires_at, retry_at, last_error, last_error_kind, "
        "created_at, updated_at FROM processing_jobs"
    )

    def save(self, record: ProcessingJobRecord) -> ProcessingJobRecord:
        cols = (
            "job_id, idempotency_key, submission_id, bidder_id, job_type, "
            "stage, correlation_id, payload, state, attempt_count, max_attempts, "
            "leased_by, lease_expires_at, retry_at, last_error, last_error_kind, "
            "created_at, updated_at"
        )
        params = (
            record.job_id,
            record.idempotency_key,
            record.submission_id,
            record.bidder_id,
            record.job_type,
            record.stage,
            record.correlation_id,
            _j(record.payload),
            record.state,
            record.attempt_count,
            record.max_attempts,
            record.leased_by,
            record.lease_expires_at,
            record.retry_at,
            record.last_error,
            record.last_error_kind,
            record.created_at,
            record.updated_at,
        )
        with self._conn.cursor() as cur:
            try:
                cur.execute(
                    f"INSERT INTO processing_jobs ({cols}) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (job_id) DO UPDATE SET "
                    "state = EXCLUDED.state, "
                    "attempt_count = EXCLUDED.attempt_count, "
                    "leased_by = EXCLUDED.leased_by, "
                    "lease_expires_at = EXCLUDED.lease_expires_at, "
                    "retry_at = EXCLUDED.retry_at, "
                    "last_error = EXCLUDED.last_error, "
                    "last_error_kind = EXCLUDED.last_error_kind, "
                    "updated_at = EXCLUDED.updated_at",
                    params,
                )
            except Exception as exc:
                _translate(exc)
        return record

    def _one(self, sql, params):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return None if row is None else ProcessingJobRecord(**row)

    def _many(self, sql, params):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return [ProcessingJobRecord(**row) for row in cur.fetchall()]

    def get(self, job_id):
        return self._one(self._SELECT + " WHERE job_id = %s", (job_id,))

    def find_by_idempotency_key(self, key):
        return self._one(self._SELECT + " WHERE idempotency_key = %s", (key,))

    def list_by_submission(self, submission_id):
        return self._many(
            self._SELECT + " WHERE submission_id = %s ORDER BY created_at",
            (submission_id,),
        )


class PostgresAuditRepository:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    _SELECT = (
        "SELECT event_id, aggregate_type, aggregate_id, event_type, payload, "
        "correlation_id, created_at FROM audit_events"
    )

    def add(self, record: AuditEventRecord) -> AuditEventRecord:
        with self._conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO audit_events (event_id, aggregate_type, "
                    "aggregate_id, event_type, payload, correlation_id, "
                    "created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (
                        record.event_id,
                        record.aggregate_type,
                        record.aggregate_id,
                        record.event_type,
                        _j(record.payload),
                        record.correlation_id,
                        record.created_at,
                    ),
                )
            except Exception as exc:
                _translate(exc, dedupe_desc=f"Audit event {record.event_id!r}")
        return record

    def _many(self, sql, params):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return [AuditEventRecord(**row) for row in cur.fetchall()]

    def list_for(self, aggregate_type, aggregate_id):
        return self._many(
            self._SELECT + " WHERE aggregate_type = %s AND aggregate_id = %s "
            "ORDER BY created_at",
            (aggregate_type, aggregate_id),
        )

    def list_by_correlation(self, correlation_id):
        return self._many(
            self._SELECT + " WHERE correlation_id = %s ORDER BY created_at",
            (correlation_id,),
        )


class PostgresOutboxRepository:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    _SELECT = (
        "SELECT event_id, aggregate_type, aggregate_id, event_type, payload, "
        "created_at, published_at, attempts FROM outbox_events"
    )

    def add(self, record: OutboxEventRecord) -> OutboxEventRecord:
        with self._conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO outbox_events (event_id, aggregate_type, "
                    "aggregate_id, event_type, payload, created_at, "
                    "published_at, attempts) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        record.event_id,
                        record.aggregate_type,
                        record.aggregate_id,
                        record.event_type,
                        _j(record.payload),
                        record.created_at,
                        record.published_at,
                        record.attempts,
                    ),
                )
            except Exception as exc:
                _translate(exc, dedupe_desc=f"Outbox event {record.event_id!r}")
        return record

    def list_unpublished(self, limit: int = 100):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                self._SELECT + " WHERE published_at IS NULL ORDER BY created_at LIMIT %s",
                (limit,),
            )
            return [OutboxEventRecord(**row) for row in cur.fetchall()]

    def record_attempt(self, event_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE outbox_events SET attempts = attempts + 1 "
                "WHERE event_id = %s",
                (event_id,),
            )

    def mark_published(self, event_id: str, published_at: float) -> bool:
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "UPDATE outbox_events SET published_at = %s, "
                "attempts = attempts + 1 WHERE event_id = %s "
                "AND published_at IS NULL RETURNING event_id",
                (published_at, event_id),
            )
            row = cur.fetchone()
        return row is not None


class PostgresFlagRepository:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    _STATE_SELECT = (
        "SELECT bidder_id, flag_id, is_set, source, finding_refs, evidence_refs, "
        "verification_refs, correlation_id, updated_at FROM flag_states"
    )

    _SNAPSHOT_SELECT = (
        "SELECT snapshot_id, bidder_id, snapshot_version, flags, provenance, "
        "content_hash, correlation_id, created_at FROM flag_snapshots"
    )

    def save_state(self, record: FlagStateRecord) -> FlagStateRecord:
        with self._conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO flag_states (bidder_id, flag_id, is_set, "
                    "source, finding_refs, evidence_refs, verification_refs, "
                    "correlation_id, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (bidder_id, flag_id) DO UPDATE SET "
                    "is_set = EXCLUDED.is_set, source = EXCLUDED.source, "
                    "finding_refs = EXCLUDED.finding_refs, "
                    "evidence_refs = EXCLUDED.evidence_refs, "
                    "verification_refs = EXCLUDED.verification_refs, "
                    "correlation_id = EXCLUDED.correlation_id, "
                    "updated_at = EXCLUDED.updated_at",
                    (
                        record.bidder_id,
                        record.flag_id,
                        record.is_set,
                        record.source,
                        _j(record.finding_refs),
                        _j(record.evidence_refs),
                        _j(record.verification_refs),
                        record.correlation_id,
                        record.updated_at,
                    ),
                )
            except Exception as exc:
                _translate(exc)
        return record

    def get_state(self, bidder_id, flag_id):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                self._STATE_SELECT + " WHERE bidder_id = %s AND flag_id = %s",
                (bidder_id, flag_id),
            )
            row = cur.fetchone()
        return None if row is None else FlagStateRecord(**row)

    def list_states(self, bidder_id):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                self._STATE_SELECT + " WHERE bidder_id = %s ORDER BY flag_id",
                (bidder_id,),
            )
            return [FlagStateRecord(**row) for row in cur.fetchall()]

    def save_snapshot(self, record: FlagSnapshotRecord) -> FlagSnapshotRecord:
        with self._conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO flag_snapshots (snapshot_id, bidder_id, "
                    "snapshot_version, flags, provenance, content_hash, "
                    "correlation_id, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (snapshot_id) DO NOTHING",
                    (
                        record.snapshot_id,
                        record.bidder_id,
                        record.snapshot_version,
                        _j(record.flags),
                        _j(record.provenance),
                        record.content_hash,
                        record.correlation_id,
                        record.created_at,
                    ),
                )
            except Exception as exc:
                _translate(exc)
        return record

    def get_snapshot(self, snapshot_id):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                self._SNAPSHOT_SELECT + " WHERE snapshot_id = %s",
                (snapshot_id,),
            )
            row = cur.fetchone()
        return None if row is None else FlagSnapshotRecord(**row)

    def list_snapshots(self, bidder_id):
        from psycopg.rows import dict_row
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                self._SNAPSHOT_SELECT + " WHERE bidder_id = %s ORDER BY created_at DESC",
                (bidder_id,),
            )
            return [FlagSnapshotRecord(**row) for row in cur.fetchall()]


__all__ = [
    "PostgresRepositories",
    "PostgresUnitOfWork",
    "apply_migrations",
]
