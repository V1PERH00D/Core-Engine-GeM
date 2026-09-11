# Storage Architecture

This document defines the persistence and processing backbone for the
SIH PS 26100 platform. It fixes exactly what belongs in **PostgreSQL**,
**Redis**, **transient process memory**, and the **artifact/blob store**,
and documents ownership boundaries, transaction semantics, and
serialization contracts.

The goal is a multi-stage, durable, resumable, idempotent, retry-safe
system that never relies on process memory for state that must survive a
crash.

---

## 1. Ownership boundary

| System | Role | Authoritative for | Never stores |
|---|---|---|---|
| PostgreSQL | Durable source of truth | structured records, audit, outbox, job history, flag states | raw document binaries, live leases |
| Redis | Transient coordination | queue, leases, retry scheduling, short-lived idempotency markers, intermediate buffers | the authoritative record of anything |
| Artifact store | Immutable blob storage | document binaries, large provider dumps | none (content-addressed) |
| Process memory | Working scratch only | in-flight local variables | anything that must survive a crash |

**Core rules (non-negotiable):**

- Redis is **not** the durable source of truth.
- PostgreSQL is **not** the job queue.
- The same authoritative record is never stored in both systems without a
documented reason. The one documented overlap is the processing job:
Redis holds the *coordination* shape (queue position, live lease) while
PostgreSQL holds the *durable history* (state, attempts, errors). The
`DurableJobQueue` mirror keeps them consistent.

---

## 2. PostgreSQL responsibilities

PostgreSQL holds durable structured records for bidders, submissions
(+ processing stage/state), document metadata (+ artifact reference +
content hash), evidence, verification, compliance results, findings,
explanations, processing job history, audit/event records, outbox events,
flag states and flag snapshots, and the relationships/references needed
for reproducibility.

Full DDL lives in `src/infrastructure/persistence/schema.py` as versioned
migrations applied by `apply_migrations(conn)`.

### Schema summary

| Table | Key/unique | Notes |
|---|---|---|
| `bidders` | `bidder_id` PK | root of every lineage |
| `submissions` | `submission_id` PK, FK `bidder_id` | `stage`, `last_completed_stage`, attempt/error/correlation |
| `documents` | `document_id` PK, FK `submission_id`, `bidder_id` | `artifact_id`, `content_hash`, `metadata` |
| `evidence` | `evidence_id` PK, FK `document_id` | `value`, `confidence`, `page`, `bbox` |
| `verifications` | `verification_id` PK | `data`/`query`/`raw_response` JSONB, transport status |
| `compliance_results` | `(bidder_id, requirement_id)` PK | idempotent upsert |
| `findings` | `finding_id` PK | full payload JSONB + ref lists |
| `explanations` | `explanation_id` PK | `grounding`, `generation` JSONB |
| `flag_states` | `(bidder_id, flag_id)` PK | boolean `is_set`, provenance refs |
| `flag_snapshots` | `snapshot_id` PK | `flags`, `provenance`, `content_hash` |
| `processing_jobs` | `job_id` PK, `idempotency_key` UNIQUE | `state`, attempts, lease timestamps |
| `audit_events` | `event_id` PK | append-only, indexed by aggregate + correlation |
| `outbox_events` | `event_id` PK | `published_at`, `attempts` |

Timestamps are POSIX epoch seconds (UTC floats) for parity with the
lease/queue layer. Structured-but-evolving payloads use JSONB, not dozens
of normalized SQL tables.

---

## 3. Redis responsibilities

Redis owns only transient/high-speed coordination:

- **Job queue** — pending list + retry zset + per-job payload (`jobs/redis_queue.py`).
- **Leases** — who owns a job and until when.
- **Retry state** — reschedule timing (scored by `retry_at`).
- **Idempotency markers** — fast-path `SET NX` dedup (durable idempotency
is enforced by PostgreSQL, never Redis alone).
- **Ephemeral intermediate buffers**.

Redis keys are namespaced (`gem:jobs:`, `gem:idem:`).

---

## 4. Artifact / blob storage

`src/infrastructure/artifacts/` defines an immutable, **content-addressed**
store. `artifact_id = "sha256:<hex>"`, so writing identical bytes is
idempotent and yields the same ID.

Interface (`ArtifactStore` protocol): `put`, `get`, `get_record`,
`exists`, `delete` (only where the lifecycle policy permits).

Backends (injected, no cloud credentials required):
`InMemoryArtifactStore`, `FilesystemArtifactStore`.

**Why Postgres stores references, not binaries:** large immutable blobs
bloat the DB, destroy index/row locality, and are never queried
relationally. PostgreSQL stores `artifact_id` + `content_hash` (a cheap,
verifiable pointer); the bytes live in the artifact store.

---

## 5. Repository layer

Clean seams in `src/infrastructure/persistence/repositories.py`:
Bidder, Submission, Document, Evidence, Verification, ComplianceResult,
Finding, Explanation, Job, Audit, Outbox, and Flag repositories.

Two implementations honor the **same** invariants:

- `persistence/memory.py` — in-memory, snapshot transactions, PK/unique/FK enforcement.
- `persistence/postgres.py` — psycopg3-backed.

Conventions: `add` raises `DuplicateRecordError`; `save` upserts on the
declared unique key; missing FK targets raise `MissingReferenceError`;
audit + outbox are append-only.

---

## 6. Job lifecycle, leases, retries, idempotency

### Job states

`PENDING -> RUNNING -> SUCCEEDED | FAILED | RETRYABLE | CANCELLED`.
Terminal: SUCCEEDED, FAILED, CANCELLED.

### Lease semantics

- `claim(worker)` atomically moves the next pending/due job to RUNNING,
recording `leased_by` + `lease_expires_at`.
- Only the lease holder may `ack`/`fail`/`renew_lease`.
- `recover_stale()` requeues expired leases (or fails exhausted jobs).

### Retry semantics

Failures classify into `TRANSIENT_INFRASTRUCTURE` and
`PROVIDER_UNAVAILABLE` (retryable), versus `MALFORMED_DOMAIN_DATA`,
`PERMANENT_VALIDATION`, and `PROGRAMMING_ERROR` (not retried). Exponential
backoff with a cap; attempts bounded by `max_attempts`. **Processing
failure is never converted into compliance FAIL.**

### Idempotency

Key = SHA-256 of `(submission_id, stage, logical_input)`. Redis `SET NX`
is a fast path only; durable idempotency is enforced by the Postgres
`idempotency_key` UNIQUE constraint and upsert-on-unique-key semantics.

---

## 7. Outbox pattern and transaction boundaries

Application transaction = **domain write + outbox insert** in one unit of
work. A publisher reads unpublished events, enqueues a job, and marks the
event published (`mark_published` guards double-publish). Downstream
idempotency makes at-least-once delivery safe.

| Crash point | Outcome |
|---|---|
| after commit, before publish | unpublished, retried |
| after enqueue, before mark | re-published (consumer idempotent) |
| during domain write | rolled back, no event |

No Kafka/RabbitMQ; Redis suffices.

---

## 8. Serialization

Versioned JSON-safe envelopes `{schema_version, artifact_type, data}` via
Pydantic `model_dump(mode="json")`. No pickle. See
`src/infrastructure/serialization.py` for the registry.

---

## 9. Flag snapshot contract

Downstream representation is **boolean-only**:

```json
{"bidder_id": "...", "flags": {"<CANONICAL_FLAG_ID>": true}}
```

- Stable, sorted ordering; one value per canonical flag ID.
- Explicit default semantics (absent flag = false when `known_flag_ids` supplied).
- **No severity. No risk. No risk score.**
- Provenance retained internally but omitted from the compact payload.
- Content-hashed snapshots for reproducibility.

## 10. Explanation persistence

`GroundedExplanation` carries flag ID + boolean state, concise/detailed
text, structured grounding references, and generation metadata. A
`DeterministicFallbackExplanationGenerator` grounds text when no model is
available. Explanations are explanations, never risk.

## 11. Audit lineage

Append-only `audit_events` + `build_flag_lineage` link, by real IDs:
submission -> documents -> evidence -> verification -> compliance ->
finding -> explanation -> flag snapshot. No fabricated references.

## 12. Retention / lifecycle

- PostgreSQL: durable records per application policy.
- Redis: ephemeral coordination with configured TTLs.
- Artifacts: immutable; retention configurable, never hardcoded to regulations.

## 13. Test strategy

Deterministic in-memory fakes for the normal suite (`tests/infrastructure/`);
contract tests assert adapters satisfy the same interfaces; opt-in
integration tests gated by `TEST_REDIS_URL` / `TEST_DATABASE_URL`.

## 14. Production vs test adapters

| Seam | Production | Test/local |
|---|---|---|
| Queue | `RedisJobQueue` | `InMemoryJobQueue` |
| Idempotency | `RedisIdempotencyStore` | `InMemoryIdempotencyStore` |
| Durability | `PostgresUnitOfWork` | `InMemoryUnitOfWork` |
| Artifacts | injectable | `InMemoryArtifactStore` / `FilesystemArtifactStore` |

No network calls happen in tests and no production credentials are
fabricated anywhere.
