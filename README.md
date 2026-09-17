# GeM Bid Compliance Verification Platform

Complete solution for SIH Problem Statement 26100:
**AI-Powered Integrated Bid Compliance Verification Platform for GeM Procurement.**

This repository is the full system: evidence ingestion, government-side
verification seams, deterministic rule evaluation, boolean compliance flags,
snapshots, grounded explanations, and auditability. It is not split into
separate Stream A / Stream B codebases.

Capability scope is defined in `docs/final-capability-matrix.md` (the authoritative,
final capability record). `docs/capability-matrix.md` is retained as the original
requirement-elicitation artifact and as the flag-registry parity reference; do not
invent requirements beyond these documents.

Key properties:

- **Boolean-only compliance contract** — the external result is exactly
  `{"bidder_id": "...", "flags": {"<CANONICAL_FLAG_ID>": true/false}}` over the
  canonical registry (`compliance_engine.flags.FLAG_REGISTRY`). No severity, no
  risk score, no AI decision.
- **AI is explanation-only** — explanations ground a flag state that the
  deterministic engines already produced; they never create or mutate flags.
- **PostgreSQL** is the durable system of record; **Redis** is transient
  coordination (queue, leases, retries, idempotency); the **ArtifactStore** holds
  source artifacts.
- **The procurement officer is the final decision-maker**; the platform produces
  verified evidence and boolean flags only.

## Layout

```text
src/compliance_engine/   # rules, verification adapters, canonical flag registry
src/ai_verification/     # cross-document/cross-bidder analysis + grounded explanations
src/infrastructure/      # persistence (PostgreSQL/in-memory), Redis jobs, artifacts, audit
src/application/         # runnable end-to-end orchestration + demo CLI (no compliance logic)
tests/                   # pytest suite
fixtures/upstream/       # sample upstream extraction payloads
fixtures/government/     # sample government/authoritative responses
docs/                    # capability specification, demo guide, architecture
```

## Development

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
python -m application demo   # deterministic end-to-end demo (no network)
```

## Running the demo

The application layer in `src/application/` wires the existing engines and
infrastructure into a runnable end-to-end flow with a tiny CLI:

```bash
python -m application scenarios              # list demo scenarios
python -m application demo                   # run all five scenarios
python -m application demo --scenario failing --json
```

The demo is deterministic and fully offline: static demo providers stand
in for the government integration seams (source IDs end in `_DEMO`), the
explanation engine uses its deterministic fallback (no LLM key), and all
state lives in the in-memory store. See `docs/demo-guide.md` for details,
including how to enable PostgreSQL (`GEM_DATABASE_URL`) and Redis
(`GEM_REDIS_URL`) for the production wiring.
