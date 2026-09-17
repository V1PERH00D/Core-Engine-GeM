# Demo Guide — SIH PS 26100 GeM Bid-Compliance Platform

This guide explains how to run the deterministic, fully-offline demo and
how the pieces of the system fit together when it runs.

## 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Requires Python 3.11+. The demo itself uses only what is already in the
repository; **no network access, government credentials, LLM API key,
PostgreSQL, or Redis is required**.

## 2. Run the deterministic demo

```bash
python -m application demo                    # all five scenarios
python -m application demo --scenario failing # one scenario
python -m application demo --scenario clean --json   # full JSON result
python -m application scenarios               # list scenarios
```

## 3. What the demo executes

For each scenario the application layer
(`src/application/service.py`) runs the full durable pipeline:

```
BidderSubmission (validated at the boundary)
  -> ingestion      (bidder / submission / documents persisted;
                     document binaries would go to the ArtifactStore)
  -> evidence rows persisted
  -> ComplianceEngine.run()      -- deterministic rules + verification
                                    providers only; no AI decisions
  -> VerificationEngine.run()    -- cross-document identity, cross-bidder
                                    anomaly findings (deterministic)
  -> flag projection             -- boolean FlagStateRecord per flag, with
                                    finding/evidence/verification refs
  -> flag snapshot               -- materialize_flag_snapshot()
  -> grounded explanations       -- ExplanationEngine with the built-in
                                    deterministic fallback (no LLM)
  -> stage COMPLETE
```

Everything is persisted through the existing repositories / unit of work
(`bidders`, `submissions`, `documents`, `evidence`, `verifications`,
`compliance_results`, `findings`, `flag_states`, `flag_snapshots`,
`explanations`, `audit_events`, `outbox`).

## 4. Where the compliance result comes from

The external compliance contract is produced by the deterministic
pipeline and is exactly:

```json
{"bidder_id": "<bidder>", "flags": {"<CANONICAL_FLAG_ID>": true, "...": false}}
```

`ApplicationResult.compliance` is a two-field model (`extra="forbid"`),
so severity/risk cannot leak into the contract. Supplementary detail
(requirement statuses, verification statuses, finding IDs, explanation
IDs and text, snapshot ID, processing stage) lives in *separate* fields
and never changes the booleans.

## 5. Where flags are generated

- Rules (`src/compliance_engine/rules/`) attach canonical flag IDs to
  `ComplianceResult.flags` when a deterministic condition is met
  (e.g. `GSTIN_MISSING`, `BIS_CERTIFICATE_INVALID`).
- The AI verification engines (`src/ai_verification/`) emit
  `VerificationFinding` / `IdentityFinding` objects carrying canonical
  flag IDs (e.g. `CROSS_DOCUMENT_IDENTITY_MISMATCH`,
  `CROSS_BIDDER_DOCUMENT_REUSED`).
- `src/application/flag_projection.py` only *projects* those flags into
  durable boolean states — it computes nothing itself. All flag IDs are
  validated against the single canonical registry
  (`compliance_engine.flags.FLAG_REGISTRY`).

## 6. Where explanations are generated

`src/ai_verification/explanations/engine.py`. The demo runs with **no
model configured**, so the deterministic, facts-only fallback produces
explanations; a real model can be injected later without changing any
flag outcome. Explanations never decide pass/fail — they only explain a
flag state that the deterministic engines already produced, and every
claim is grounded in persisted evidence/verification/finding references.

## 7. How provenance is preserved

Every boolean flag state links to real finding / evidence / verification
IDs. `infrastructure.audit.build_flag_lineage` can rebuild the whole
chain for one flag:

```
submission -> documents -> evidence -> verifications
  -> compliance results -> findings -> explanations -> flag snapshot
```

Audit events carry a correlation ID end-to-end; snapshot IDs are
content-addressed (`snap:<sha256>`) and reproducible.

## 8. Demo scenarios

| scenario        | intent                                        | flags set (demo data) |
| --------------- | --------------------------------------------- | --------------------- |
| `clean`         | fully compliant bidder                        | *(none)* |
| `failing`       | deterministic failures                        | `BIS_CERTIFICATE_INVALID`, `LOCAL_CONTENT_BELOW_THRESHOLD`, `PROCUREMENT_DEBARMENT_ACTIVE`, `TURNOVER_BELOW_THRESHOLD` |
| `missing`       | evidence gaps                                 | incl. `GSTIN_MISSING`, `REQUIRED_FIELD_MISSING` |
| `inconsistent`  | cross-document conflict                       | `CROSS_DOCUMENT_IDENTITY_MISMATCH` |
| `cross_bidder`  | byte-identical documents across two bidders   | `CROSS_BIDDER_DOCUMENT_REUSED` |

All bidder names, GSTINs, PANs, CINs, BIS licence numbers and documents
are clearly synthetic demo values; no real personal or company data is
used.

## 9. Which parts are synthetic/demo-only

- `src/application/demo.py: StaticDemoProvider` — returns canned
  `Verification` objects for identifiers it knows; its source IDs always
  end in `_DEMO`. These stand in for the real adapters and are the
  documented integration seams. `MockGSTProvider` / `MockPANProvider` /
  `MockUdyamProvider` follow the same pattern and already exist.
- Scenario data (bidders, documents, evidence) is entirely synthetic.
- Explanations use the deterministic fallback generator.

Nothing demo-related ever claims to be a live government response:
provider `source` strings persisted on verification records are
`*_DEMO` / `*_MOCK`.

## 10. Which government integrations require real credentials

Production verification providers already exist with explicit,
fail-safe configuration:

- GST/GSTN (`GST_*`; see `compliance_engine.verification.gst_config`)
- PAN / Income Tax (`PAN_*`; `pan_config`)
- Debarment eligibility (`DEBARMENT_*`; `debarment_config`)

When not configured, these adapters fail clearly and safely: the rules
then report `UNVERIFIABLE` (never a silent PASS or FAIL). No fake
endpoints or credentials exist anywhere in the repository.

## 11. Enabling PostgreSQL

Set `GEM_DATABASE_URL` and wire the existing PostgreSQL unit of work:

```python
import psycopg
from infrastructure.settings import InfrastructureSettings
from infrastructure.persistence.postgres import PostgresUnitOfWork

settings = InfrastructureSettings.from_env()
# ``psycopg.connect`` owns the connection; the unit of work wraps it.
service = ComplianceApplicationService(
    compliance_engine=engine,
    verification_engine=verification_engine,
    uow_factory=lambda: PostgresUnitOfWork(
        psycopg.connect(settings.require_database_url())
    ),
)
```

PostgreSQL is the durable system of record; swapping the factory changes
nothing else in the application flow.

## 12. Enabling Redis processing

Set `GEM_REDIS_URL` and pass `RedisJobQueue`:

```python
import redis
from infrastructure.jobs.redis_queue import RedisJobQueue

settings = InfrastructureSettings.from_env()
service = ComplianceApplicationService(
    ..., queue=RedisJobQueue(redis.Redis.from_url(settings.require_redis_url()))
)
job = service.enqueue_submission(submission)
worker = SubmissionWorker(service)   # run in a worker process
worker.run_until_empty()
```

Redis holds only transient coordination state (queues, leases, retries,
idempotency). The durable compliance result always lives in the durable
store (PostgreSQL in production, the in-memory store in demo/tests).

## 13. Security & privacy notes

- No credentials, no fabricated government data, no real personal data.
- The CLI prints verification **statuses** and references, never raw
  provider payloads (`VerificationRecord.data` / `raw_response`).
- Error text persisted on failed submissions may reference input
  identifiers (e.g. a GSTIN); treat submission/audit logs as sensitive.
- Submissions are validated at the boundary (`BidderSubmission`);
  unknown document references and cross-bidder evidence are rejected.
- Document content goes to the artifact store only when one is wired;
  nothing is written to disk in the demo.
