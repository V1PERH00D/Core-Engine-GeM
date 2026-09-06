# Cross-source bidder identity reconciliation

## Purpose

`src/ai_verification/identity/` is a **deterministic, auditable**
identity-consistency engine. It compares the already-normalized
identity-bearing values carried inside the Compliance Engine's
GST / PAN / Udyam / MCA `Verification` records and surfaces
meaningful cross-source identity inconsistencies as
`IdentityFinding` (Compliance Engine) and `VerificationFinding`
(AI Verification Engine) records.

It does NOT:

* Re-query any provider. It only reads `Verification` artefacts
  already produced by the upstream adapters.
* Use AI / embeddings / network calls. Every transformation is
  string-level and synchronous.
* Pronounce legal truth. No source is treated as universally
  authoritative.

## Supported source types

The engine understands exactly four capability IDs and maps them
to a small internal source vocabulary:

| Capability       | Source label | Identity-bearing field    |
|------------------|--------------|---------------------------|
| `GST` / `GSTN`   | `GST`        | `legal_name`              |
| `PAN` / `PAN_INCOME_TAX` | `PAN` | `name_on_pan`        |
| `UDYAM`          | `UDYAM`      | `enterprise_name`         |
| `MCA` / `MCA21`  | `MCA`        | `company_name`            |

Any other capability is silently skipped.

## Normalization rules

Version: `identity-name-v1` (string, exported as
`NAME_NORMALIZATION_VERSION`).

The pipeline is applied in this exact order:

1. `None` -> `None`.
2. Empty / whitespace-only -> `None`.
3. Unicode NFKC.
4. Strip surrounding whitespace.
5. Collapse repeated internal whitespace to single space.
6. Strip edge punctuation (trailing/leading `.`, `,`, `;`, `:`).
7. Case-fold (lowercase).
8. Re-collapse whitespace introduced by stripping (defensive).

Crucially, the engine does **NOT**:

* rewrite `PVT` -> `PRIVATE` or `LTD` -> `LIMITED`. Synonym
  rewrites belong to the Compliance Engine's existing cross-document
  identity anomaly detector
  (`compliance_engine.anomalies.identity.normalize_identity_name`).
  Performing them here would risk amplifying a synonym rewrite into
  a fake cross-source match.
* remove interior punctuation. "ACME-ENTERPRISES" stays distinct
  from "ACME ENTERPRISES" at this layer.
* use fuzzy / semantic / embedding-based matching. A future
  capability may add a fuzzy name matcher; this milestone keeps
  that concern strictly separated.

The original and normalized forms are both retained on every
observation (`IdentityObservation.original_name`,
`IdentityObservation.normalized_name`).

## Pairwise comparison semantics

For each distinct (left, right) pair across the four sources, the
engine emits an `IdentityPairwiseComparison` whose `outcome` is
one of:

| Outcome               | Meaning                                                        |
|-----------------------|----------------------------------------------------------------|
| `MATCH_EXACT`         | Both sides VERIFIED with names; byte-identical originals.     |
| `MATCH_NORMALIZED`    | Both sides VERIFIED with names; originals differ but normalized forms are identical. |
| `MISMATCH`            | Both sides VERIFIED with names; normalized forms differ materially. |
| `INSUFFICIENT_EVIDENCE` | Either side is not VERIFIED with a name (or is the same source). |

Sources are never paired with themselves; if two observations exist
for the same source, only the **first** one participates in
pairing. Self-pairing always returns `INSUFFICIENT_EVIDENCE`.

## Insufficient-evidence semantics

A pair is `INSUFFICIENT_EVIDENCE` whenever either observation has a
`SourceAvailability` other than `VERIFIED`, including:

* `NOT_QUERIED` - the source was never queried.
* `UNAVAILABLE` - the provider call failed (`UNAVAILABLE`,
  `ERROR`, or `INVALID` upstream status).
* `NOT_FOUND` - the source returned no record.
* `INACTIVE` - the source returned an inactive record.
* `VERIFIED_WITHOUT_NAME` - upstream said `VERIFIED` but the
  identity-bearing field was missing / null / empty.

This taxonomy is exported as `SourceAvailability` and is derived
from the upstream `VerificationStatus` so that:

* Provider failure NEVER becomes an identity mismatch.
* Missing evidence NEVER becomes a negative assertion.

## Why provider failure != mismatch

Government sources can be unreachable, rate-limited, or simply
return `NOT_FOUND`. Conflating that with a real bidder identity
mismatch would create false positives that no downstream policy
could safely act on. The engine therefore partitions outcomes into
"MISMATCH" (real evidence says the names differ) versus
"INSUFFICIENT_EVIDENCE" (we cannot conclude anything). The flag
`CROSS_SOURCE_IDENTITY_MISMATCH` is emitted **only** for the
former.

## Why no source is treated as universally authoritative

A bidder is not "MCA-truth" or "PAN-truth". Each source has a
different view of the bidder: MCA knows the registered company
name on the CIN, PAN knows the name on the PAN card, GST knows
the legal name on the registration. None of them is more
authoritative than the others in general. The engine therefore
exposes every observation and every comparison; downstream policy
decides which sources matter for which bidder type.

## Aggregation model

`IdentityReconciliationEngine.reconcile(...)` returns an
`IdentityReconciliationResult` carrying:

* `aggregation`: a per-bidder `IdentityAggregation` with
  `observations`, `comparisons`, `verified_sources`,
  `insufficient_sources`, `disagreeing_pairs`,
  `normalization_version`.
* `identity_findings`: Compliance Engine
  `IdentityFinding` records.
* `verification_findings`: AI Verification Engine
  `VerificationFinding` records.

The aggregation deliberately does NOT apply any "majority truth"
rule: a downstream policy layer decides how to act on the evidence
graph this engine produces.

## Finding / flag behaviour

The new canonical flag is `CROSS_SOURCE_IDENTITY_MISMATCH`,
registered in `compliance_engine.flags.registry` under the
`Bidder Identity` capability with `HIGH` severity.

* One `IdentityFinding` is emitted per pairwise mismatch.
* One `VerificationFinding` is emitted per pairwise mismatch,
  with `severity` copied from the registry and `confidence` set
  deterministically (0.9 for MISMATCH, 0.95 for MATCH_NORMALIZED,
  1.0 for MATCH_EXACT, 0.0 for INSUFFICIENT_EVIDENCE - though
  INSUFFICIENT_EVIDENCE never emits a finding).
* `verification_refs` carry both sides' `verification_id`.
* `evidence_refs` carry both sides' `evidence_id` (preserved
  verbatim, never fabricated).
* `explanation` is deterministic, free of secrets, and identifies
  both sources plus the original and normalized values.

## Capability matrix synchronization

`docs/capability-matrix.md` lists every flag under "Bidder Identity"
flags. The new flag is added there (Bidder Identity flag count
went from 5 to 6). The `tests/flags/test_registry.py` invariant
that the registry and the matrix match exactly is preserved.

## Integration with `VerificationEngine`

`VerificationEngine` gained a new optional constructor parameter:

```python
VerificationEngine(
    artifact_store=...,
    identity_reconciliation_engine=IdentityReconciliationEngine(),
)
```

When unset (`None`, the default), the engine behaves exactly as
it did before this milestone. When supplied, identity
reconciliation is run first (deterministic, no artifact store
required), and its findings are concatenated with the
cross-bidder findings before producing the `VerificationResult`.

## Backward compatibility

This milestone does not modify:

* `VerificationStatus`
* GST / PAN / Udyam / MCA provider contracts
* existing cross-bidder similarity thresholds (semantic threshold 0.85)
* the existing cross-bidder confidence formula
* existing exact / normalized / lexical detection behaviour
* existing quality formulas
* existing flags except adding `CROSS_SOURCE_IDENTITY_MISMATCH`

## Current limitations

* No fuzzy / semantic / embedding-based name matching.
* No handling of transliterated Indian-language names (Devanagari,
  Tamil, etc.); only NFKC is applied.
* Synonym rewrites (`PVT` -> `PRIVATE`, `LTD` -> `LIMITED`) are
  intentionally NOT applied. Future work may revisit this
  conservatively with a per-language controlled lexicon.
* Only four sources are supported: GST, PAN, UDYAM, MCA.
* No cross-bidder identity check; identity reconciliation is
  always per-bidder.
* No automatic promotion / demotion of any source as "truth".

## Future work (intentionally separate)

* Fuzzy name matcher using character / token edit distance, gated
  on the existing evidence-quality subsystem.
* Per-language controlled synonym lexicons, with the same
  audit guarantees (every rewrite logged with version + reason).
* Cross-bidder identity reconciliation reusing the same engine.
