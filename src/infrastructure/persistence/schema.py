"""PostgreSQL relational schema and migration mechanism.

Timestamps are stored as ``DOUBLE PRECISION`` POSIX epoch seconds (UTC)
for parity with the queue/lease layer and determinism; structured,
evolving payloads are stored as ``JSONB``. Large document binaries are
*not* stored here — only their artifact reference and content hash (see
``docs/storage-architecture.md``).

Ownership rule: PostgreSQL is the durable source of truth. Redis is the
transient coordination layer. The outbox table is the reliable hand-off
between a committed domain transaction and the queue publisher.
"""

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION: int = 1


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


_MIGRATION_0001 = """
CREATE TABLE IF NOT EXISTS bidders (
    bidder_id TEXT PRIMARY KEY,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS submissions (
    submission_id TEXT PRIMARY KEY,
    bidder_id TEXT NOT NULL REFERENCES bidders(bidder_id),
    stage TEXT NOT NULL,
    last_completed_stage TEXT,
    correlation_id TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_error_kind TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_submissions_bidder
    ON submissions (bidder_id);

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    submission_id TEXT REFERENCES submissions(submission_id),
    bidder_id TEXT NOT NULL REFERENCES bidders(bidder_id),
    document_type TEXT NOT NULL,
    artifact_id TEXT,
    content_hash TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_submission
    ON documents (submission_id);
CREATE INDEX IF NOT EXISTS idx_documents_bidder ON documents (bidder_id);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    bidder_id TEXT NOT NULL REFERENCES bidders(bidder_id),
    document_id TEXT NOT NULL REFERENCES documents(document_id),
    field_name TEXT NOT NULL,
    document_type TEXT,
    value JSONB,
    confidence DOUBLE PRECISION,
    page INTEGER,
    bbox JSONB,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_bidder ON evidence (bidder_id);
CREATE INDEX IF NOT EXISTS idx_evidence_document ON evidence (document_id);

CREATE TABLE IF NOT EXISTS verifications (
    verification_id TEXT PRIMARY KEY,
    bidder_id TEXT NOT NULL REFERENCES bidders(bidder_id),
    capability TEXT NOT NULL,
    source TEXT NOT NULL,
    queried_identifier TEXT,
    status TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    query JSONB,
    raw_response JSONB,
    retrieved_at DOUBLE PRECISION NOT NULL,
    latency_ms INTEGER,
    correlation_id TEXT,
    transport_status_code INTEGER,
    evidence_id TEXT REFERENCES evidence(evidence_id),
    document_id TEXT REFERENCES documents(document_id),
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verifications_bidder
    ON verifications (bidder_id);
CREATE INDEX IF NOT EXISTS idx_verifications_correlation
    ON verifications (correlation_id);

CREATE TABLE IF NOT EXISTS compliance_results (
    result_id TEXT NOT NULL,
    bidder_id TEXT NOT NULL REFERENCES bidders(bidder_id),
    requirement_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    expected JSONB,
    actual JSONB,
    rule_id TEXT,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    verification_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (bidder_id, requirement_id)
);
CREATE INDEX IF NOT EXISTS idx_compliance_bidder
    ON compliance_results (bidder_id);

CREATE TABLE IF NOT EXISTS findings (
    finding_id TEXT PRIMARY KEY,
    bidder_id TEXT NOT NULL REFERENCES bidders(bidder_id),
    finding_type TEXT NOT NULL,
    flag_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    verification_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    related_bidder_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_bidder ON findings (bidder_id);
CREATE INDEX IF NOT EXISTS idx_findings_flag
    ON findings (bidder_id, flag_id);

CREATE TABLE IF NOT EXISTS explanations (
    explanation_id TEXT PRIMARY KEY,
    bidder_id TEXT NOT NULL REFERENCES bidders(bidder_id),
    flag_id TEXT NOT NULL,
    flag_active BOOLEAN NOT NULL,
    finding_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    concise_text TEXT NOT NULL,
    detailed_text TEXT,
    grounding JSONB NOT NULL DEFAULT '[]'::jsonb,
    generation JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_explanations_flag
    ON explanations (bidder_id, flag_id);

CREATE TABLE IF NOT EXISTS flag_states (
    bidder_id TEXT NOT NULL REFERENCES bidders(bidder_id),
    flag_id TEXT NOT NULL,
    is_set BOOLEAN NOT NULL,
    source TEXT,
    finding_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    verification_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    correlation_id TEXT,
    updated_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (bidder_id, flag_id)
);

CREATE TABLE IF NOT EXISTS flag_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    bidder_id TEXT NOT NULL REFERENCES bidders(bidder_id),
    snapshot_version TEXT NOT NULL,
    flags JSONB NOT NULL DEFAULT '{}'::jsonb,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_hash TEXT NOT NULL,
    correlation_id TEXT,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_bidder
    ON flag_snapshots (bidder_id);

CREATE TABLE IF NOT EXISTS processing_jobs (
    job_id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    submission_id TEXT REFERENCES submissions(submission_id),
    bidder_id TEXT,
    job_type TEXT NOT NULL,
    stage TEXT,
    correlation_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    state TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    leased_by TEXT,
    lease_expires_at DOUBLE PRECISION,
    retry_at DOUBLE PRECISION,
    last_error TEXT,
    last_error_kind TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_submission
    ON processing_jobs (submission_id);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON processing_jobs (state);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    correlation_id TEXT,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_aggregate
    ON audit_events (aggregate_type, aggregate_id);
CREATE INDEX IF NOT EXISTS idx_audit_correlation
    ON audit_events (correlation_id);

CREATE TABLE IF NOT EXISTS outbox_events (
    event_id TEXT PRIMARY KEY,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at DOUBLE PRECISION NOT NULL,
    published_at DOUBLE PRECISION,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_outbox_unpublished
    ON outbox_events (published_at) WHERE published_at IS NULL;
"""

_MIGRATION_0002 = """
ALTER TABLE explanations ADD COLUMN IF NOT EXISTS schema_version INTEGER;
ALTER TABLE explanations ADD COLUMN IF NOT EXISTS grounding_version INTEGER;
ALTER TABLE explanations ADD COLUMN IF NOT EXISTS validation_status TEXT;
ALTER TABLE explanations ADD COLUMN IF NOT EXISTS fallback_used BOOLEAN;
ALTER TABLE explanations ADD COLUMN IF NOT EXISTS input_hash TEXT;
ALTER TABLE explanations ADD COLUMN IF NOT EXISTS evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE explanations ADD COLUMN IF NOT EXISTS verification_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE explanations ADD COLUMN IF NOT EXISTS document_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE explanations ADD COLUMN IF NOT EXISTS comparison_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE explanations ADD COLUMN IF NOT EXISTS trace_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE explanations ADD COLUMN IF NOT EXISTS content JSONB;
ALTER TABLE explanations ADD COLUMN IF NOT EXISTS uncertainties JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE explanations ADD COLUMN IF NOT EXISTS review_actions JSONB NOT NULL DEFAULT '[]'::jsonb;
"""


MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, name="initial_schema", sql=_MIGRATION_0001),
    Migration(version=2, name="explanation_metadata", sql=_MIGRATION_0002),
)


def latest_version() -> int:
    return MIGRATIONS[-1].version


__all__ = ["Migration", "MIGRATIONS", "SCHEMA_VERSION", "latest_version"]