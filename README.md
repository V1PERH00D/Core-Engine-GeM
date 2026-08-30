# GeM Bid Compliance Verification Platform

Complete solution for SIH Problem Statement 26100:
**AI-Powered Integrated Bid Compliance Verification Platform for GeM Procurement.**

This repository is the full system: evidence ingestion, government-side verification, rule evaluation, flags, scoring, and auditability. It is not split into separate Stream A / Stream B codebases.

Capability scope is defined in `docs/capability-matrix.md`. Do not invent requirements beyond that document.

## Layout

```text
src/compliance_engine/   # verification platform package
tests/                   # pytest suite
fixtures/upstream/       # sample upstream extraction payloads
fixtures/government/     # sample government/authoritative responses
docs/                    # capability specification
```

Package modules (skeleton only; no business logic yet):

- `models` — data shapes
- `ingestion` — upstream evidence intake
- `verification` — authoritative source checks
- `rules` — tender/policy evaluation
- `anomalies` — cross-document inconsistency detection
- `flags` — explainable findings
- `scoring` — bid-level aggregation
- `audit` — traceability

## Development

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
