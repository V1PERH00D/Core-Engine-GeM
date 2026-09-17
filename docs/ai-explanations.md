# AI Explanations — Grounded Explanation Engine

This document describes the explanation subsystem introduced by the
"Grounded AI Explanation Engine + Persisted Explanation Pipeline"
milestone. The subsystem lives under `src/ai_verification/explanations/`.

> **AI explanations do not change compliance decisions.**
> **AI explanations do not create risk scores or severity.**
> The explanation engine is *strictly downstream* of flag computation and
> boolean flag state. It only explains the state it was given.

The canonical downstream representation remains **boolean only**:

```json
{
  "bidder_id": "...",
  "flags": {
    "<CANONICAL_FLAG_ID>": true
  }
}
```

No severity. No risk score. No risk state.

---

## 1. Architecture

```
boolean flag state (upstream compliance/AI systems)
        |
        v
  ExplanationRequest  (caller supplies grounding context)
        |
        v
  ExplanationGrounding (the ONLY artefacts an explanation may cite)
        |
        +--> StrategyRegistry (flag/capability -> strategy)
        |
        v
  ExplanationEngine
     |-- model generate (injected ExplanationModel)   --+
     |-- deterministic fallback (facts only)          --|
     |-- grounding + claim validation                 <-+
        |
        v
  ExplanationResult
        |
        v
  (Redis job) ExplanationPipeline
     |-- enqueue (idempotency key)
     |-- process: QUEUED -> GENERATING -> VALIDATING -> READY
     |-- persist explanation + audit + outbox (Postgres, atomic)
        |
        v
  Durable ExplanationRecord (+ audit lineage + outbox event)
        |
        v
  Flag snapshot linkage (internal only; downstream stays boolean-only)
```

## 2. Explanation domain model

* `ExplanationRequest` (`models.py`/`generator.py`) — enough context to
  explain one flag: `bidder_id`, `flag_id`, boolean state (`flag_active`,
  aliased as `flag_state`), finding/evidence/verification/document/
  comparison/trace references, a set of `StructuredFact`s, uncertainty
  notes, and an optional locale.
* `ExplanationGrounding` (`grounding.py`) — frozen, normalised (sorted,
  deduplicated) reference tuples for the six artefact families (evidence,
  verification, document, finding, comparison, trace) plus a deterministic
  `content_hash()` used for idempotency and input-version tracking.
* `StructuredFact` (`facts.py`) — a typed fact (`FactKind`) with explicit
  `fact_id` and only-populated fields (value, actual/expected, thresholds,
  financial year, similarity score/threshold, status, quality state, …).
  Missing values are never manufactured.
* `ExplanationContent` (`content.py`) — the strict structured output:
  `summary`, `detailed_explanation`, `observed_facts[]`, `uncertainties[]`,
  reference lists, and `recommended_review_actions[]`.
* `ExplanationResult` (`models.py`) — the validated final result.
* `ExplanationGenerationMetadata` (`models.py`) — generator/provider/model
  names, schema/grounding versions, validation status, fallback flag, input
  hash.

All models use Pydantic v2 with `extra="forbid"` and `frozen=True` where
appropriate.

## 3. Grounding contract

Every claim in a generated explanation must trace to a supplied
`ExplanationGrounding`. Arbitrary reference IDs that do not appear in the
supplied context are rejected.

```
{
  "evidence_refs": [...],
  "verification_refs": [...],
  "document_refs": [...],
  "finding_refs": [...],
  "comparison_refs": [...],
  "trace_refs": [...]
}
```

## 4. Structured facts

`StructuredFact` carries only the fields actually present:

`field_name`, `value`, `source_ref`, `document_ref`, `verification_ref`,
`confidence`, `normalized_value`, `expected_value`, `actual_value`,
## 5. Claim validation (the most important component)

`GroundingValidator` checks:

A. every referenced evidence ID exists in the supplied grounding,
B. every verification ID exists in the supplied grounding,
C. every finding ID exists in the supplied grounding,
D. no unsupported identifiers are introduced (via `observed_facts`),
E–H. numbers / financial years / dates / similarity scores in the text
match submitted fact values,
I. no claim of absent evidence (unknown refs are rejected),
J. a `false` flag is explained as absence/satisfaction, not a present
condition,
K. unknown/unavailable state remains explicitly uncertain.

**Claim extraction is structured, not free-text NLP**: the model must emit
`observed_facts[]` with `fact_ref`, `statement_type`, and `source_ref`
pointing at supplied facts; the validator checks each one against the
supplied grounding and fact corpus.

`ValidationStatus` values: `VALID`, `GROUNDING_FAILED`, `CLAIM_FAILED`,
`FALLBACK`.

## 6. Hallucination defences

The validator rejects generated output that introduces new numbers, new
financial years, new dates, new identifiers (e.g. a GSTIN not present in
the facts), new document names, unsupported status claims, unsupported
legal conclusions, and first-person model framing ("the AI thinks …").
Forbidden phrases (fraud, collusion, forgery, fabrication, manipulation,
illegal, guilt, …) are always rejected. When validation fails the engine
falls back to the deterministic generator — it never "repairs" invented
facts silently.

## 7. Deterministic fallback

`ExplanationEngine` always has a facts-only fallback that works when the
LLM is absent, times out, is unavailable, returns malformed output, or
fails grounding/claim validation. It composes text strictly from the
supplied `StructuredFact`s:

> The requirement expects a value of at least 25.0 crore. The available
> evidence gives 18.4 crore.

Only numbers and years actually present are used.

## 8. LLM provider abstraction (`provider.py`)

`ExplanationModel` is a protocol (`generate(prompt, *, timeout_seconds) ->
ExplanationModelResponse`). Providers are dependency-injected and carry no
domain logic. Implementations:

* `StaticExplanationModel` — deterministic fake for tests.
* `HttpExplanationModel` — provider-agnostic HTTP seam (injected `send` +
  `parse`); no Kimi-specific semantics are hard-coded here.

Provider failures are explicit (`ExplanationModelUnavailableError`,
`ExplanationModelTimeoutError`, `MalformedModelOutputError`); there is no
silent fallback inside a provider.

## 9. Prompt / context construction (`context.py`)

The model receives ONLY: canonical flag ID, boolean state, flag
title/description, structured facts, reference IDs, and uncertainty notes.
No repository tables or arbitrary files are dumped. Facts are serialized
into clearly delimited blocks and treated strictly as data.

## 10. Prompt-injection protection

Extracted document text is treated as **data, never instructions**. The
system prompt states unconditionally that text inside
`<<<UNTRUSTED_EVIDENCE_DATA … >>>` blocks must never be obeyed. Adversarial
text cannot escape its block because the builder strips delimiter markers
from values and keeps them inside a labelled data block. See
`tests/ai_verification/explanations/test_context.py` and
`test_integration_e2e.py`.

## 11. Strategy registry (`strategies.py`)

An ordered, inspectable, extensible `StrategyRegistry` maps flag/capability
to a strategy. Strategies provide deterministic review actions and
uncertainty phrasing. Supported strategies: compliance failure / pass,
missing evidence, unavailable verification, identity mismatch,
cross-document mismatch, cross-bidder reuse, semantic near-duplicate,
evidence quality, debarment/restriction, financial threshold, financial
inconsistency, return-filing, plus a generic fallback. No scattered
`if flag_id == …` logic.

## 12. True / false semantics

* **true** — explain why the existing engine marked it true.
* **false** — explain what available evidence supports the false/absence
  state (e.g. "the verification does not establish an active
  registration; source status was NOT_FOUND").
* `UNAVAILABLE` is never converted into `FALSE`; the boolean state already
  comes from upstream policy and is faithfully described.
## 13. PostgreSQL persistence

The existing `ExplanationRepository` persists the durable
`ExplanationRecord` (bidder, flag, boolean state, structured explanation,
grounding refs, generation metadata, validation status, timestamps,
deterministic version info, input hash). The `explanations` table was
extended minimally via migration `v2 ("explanation_metadata")` with the new
grounding/metadata columns. Idempotency is enforced by the `explanation_id`
primary key (deterministic on `bidder:flag:state`) and the `processing_jobs`
`idempotency_key` uniqueness.

## 14. Redis job lifecycle (`pipeline.py`)

`ExplanationPipeline` uses the existing queue. Job stages:
`QUEUED -> GENERATING -> VALIDATING -> READY`.

| failure | outcome |
|---|---|
| provider unavailable / timeout | `RETRYABLE` (re-enqueued) |
| malformed model output | deterministic fallback |
| grounding validation failure | deterministic fallback |
| programming error | `FAILED` |

Explanation failures are **never** converted into compliance failures.

## 15. Idempotency

The job idempotency key covers `(bidder_id, flag_id, flag_state,
grounding hash, schema version, grounding version)`. A duplicate queue
delivery returns the existing job and never creates a second durable
explanation. PostgreSQL uniqueness constraints (not Redis alone) provide
durable correctness.

## 16. Outbox integration

When an explanation becomes `READY`, the durable explanation record, its
audit event, and an outbox event are persisted **atomically** in one unit
of work, then published through the existing outbox pipeline. No second
eventing mechanism.

## 17. Audit lineage

`build_flag_lineage` reconstructs
`flag -> finding -> evidence -> document -> verification -> explanation`
using only real persisted IDs. The explanation record preserves grounding
refs so a human can reconstruct *why* the explanation says what it says.

## 18. Flag snapshot relationship

`BidderFlagSnapshot.downstream_payload()` is unchanged: boolean-only.
`internal_payload(explanation_refs=...)` optionally adds an
`explanations` map for internal use only.

## 19. Storage / buffer ownership

* **Postgres** — durable explanation records, grounding/generation
  metadata, audit linkage, processing history.
* **Redis** — queued explanation jobs, active lease, retry state,
  short-lived generation state.
* **Process memory** — current prompt/context, transient pre-validation
  provider response.
* **Artifact store** — large source documents, if referenced.

Durable state is never held *only* in process memory.

## 20. Production model integration

Wire a real model by implementing `ExplanationModel` (e.g. via
`HttpExplanationModel`) and injecting it into `ExplanationEngine` /
`ExplanationPipeline`. External LLM access is fully injectable and disabled
in deterministic tests (no network calls in the normal suite).

## 21. Limitations

* Explanations are only as good as the supplied grounding and facts; the
  engine never re-discovers evidence by scraping files.
* The deterministic fallback is structured-facts-only and does not perform
  free-text reasoning.
* No production HTTP model / credentials are bundled; the repository ships
  only the provider seam and a deterministic static provider.
* Explanations never change flag state, compliance results, verification
  status, evidence values, or finding classification.
`operator`, `unit`, `financial_year`, `comparison_outcome`,
`similarity_score`, `similarity_threshold`, `quality_state`.