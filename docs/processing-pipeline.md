# Processing Pipeline

This document describes the processing state machine, its boundaries with
domain/compliance state, resumability, retries, idempotency, and crash
recovery for the SIH PS 26100 platform.

## 1. Stage model

Linear happy path (`src/infrastructure/pipeline.py`):

```
INGESTED -> NORMALIZED -> VERIFICATION_PENDING -> VERIFIED
  -> AI_ANALYSIS_PENDING -> AI_ANALYZED
  -> EXPLANATION_PENDING -> EXPLANATION_READY -> COMPLETE
```

Plus `FAILED`, reachable from every non-terminal stage; a FAILED
submission resumes to any linear stage (retry from the last good stage).
Transitions are validated with `validate_transition` — skipping stages or
leaving a terminal state is rejected; same-stage re-entry is allowed so
workers can re-run a stage idempotently.

## 2. Processing vs compliance state

Processing state (the pipeline) and compliance state (PASS/FAIL/etc.) are
different concepts. A pipeline can be COMPLETE while carrying FAIL
compliance results; a pipeline can be FAILED even though every emitted
compliance artefact is valid. A provider outage or queue failure must
never be converted into a compliance FAIL, and missing evidence remains
missing evidence.

## 3. Resumability

A process crash must not recompute everything. The submission row holds:

- current `stage`
- `last_completed_stage` (the resummability anchor)
- `attempt_count`
- `last_error` / `last_error_kind`
- `correlation_id`
- timestamps

No transient Python object is the resume mechanism.

## 4. Job lifecycle

See `jobs/models.py`. States: PENDING, RUNNING, RETRYABLE, SUCCEEDED,
FAILED, CANCELLED. The `DurableJobQueue` mirrors every queue mutation into
the Postgres `processing_jobs` table.

## 5. Leases and concurrency

A claim atomically sets `leased_by` + `lease_expires_at`. Only the lease
holder may ack/fail/renew. `recover_stale()` requeues crashed workers, so
two workers can never simultaneously believe they own the same job.

## 6. Retries

Deterministic classification (transient/provider vs malformed/permanent/
programming) with bounded attempts and capped exponential backoff.
Programming errors are not retried indefinitely. Provider-unavailable is
retryable but never a business failure.

## 7. Idempotency

Each stage derives an idempotency key from `(submission_id, stage,
logical_input)`. Operations are: idempotent (verification, findings,
explanations, flag states — upsert by unique key), append-only (audit,
outbox insertion), or deduplicated by unique constraint (jobs). Postgres
unique constraints protect durable invariants; Redis is only a fast path.

## 8. Outbox and transaction boundaries

A domain transaction writes the domain record and its outbox event together;
a separate publisher enqueues the job and marks the event published. This
avoids the “db commit succeeded, queue publish failed” problem.

## 9. Crash recovery

- Worker crash -> expired lease -> recovered by `recover_stale()`.
- Publisher crash -> outbox event unpublished/republished -> idempotent.
- Process crash -> durable submission/job state -> resume from
`last_completed_stage`.

## 10. End-to-end flow

```
submitted document
  -> persisted submission/document/evidence
  -> queued processing job (durable mirror)
  -> verification result persisted
  -> compliance result persisted
  -> AI finding / boolean flag persisted
  -> grounded explanation persisted
  -> BidderFlagSnapshot materialized (boolean-only)
  -> audit trail links every stage
```

No step depends on process-memory state for durability.
