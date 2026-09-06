# Bidder-Level Compliance Risk Aggregation

This document describes the deterministic, auditable bidder-level
risk-aggregation layer in :mod:`ai_verification.risk`.

The purpose of this layer is **not** to discover new anomalies. The
purpose is to answer:

> Given all evidence already produced for this bidder, what risk
> signals exist, how strong is each signal, what evidence supports
> it, and what is the aggregate bidder risk state?

The engine consumes already-produced outputs from the Compliance
Engine, the AI Verification Engine, the identity reconciliation
sub-system, the cross-bidder detector, and the evidence-quality
subsystem, and produces a deterministic
:class:`BidderRiskAssessment`.

The layer never calls the network, never invents identifiers, and
never uses an LLM for scoring or explanation. All numeric constants
live in :mod:`ai_verification.risk.policy`.

---

## 1. Architecture

```
src/ai_verification/risk/
    __init__.py        -- public API
    policy.py          -- centralized constants
    severity.py        -- severity -> numeric weight mapping
    models.py          -- typed Pydantic models
    correlation.py     -- deterministic correlation keys
    signals.py         -- signal extraction from existing artefacts
    aggregation.py     -- dedup, score, risk state machine
    explanation.py     -- deterministic explanation builder
    engine.py          -- BidderRiskEngine orchestrator
```

The layer is split into focused modules so each concern is auditable
and testable in isolation. Callers only depend on
``BidderRiskEngine.assess``; the rest of the package is internal.

---

## 2. Signal categories

The risk engine uses a small controlled taxonomy of categories,
defined in :class:`ai_verification.risk.models.RiskCategory`:

| Category | Meaning |
|---|---|
| ``COMPLIANCE`` | A per-requirement compliance outcome indicates a real issue. |
| ``IDENTITY`` | A cross-source identity mismatch was detected. |
| ``DOCUMENT_REUSE`` | A cross-bidder document reuse / near-duplicate was detected. |
| ``EVIDENCE_QUALITY`` | Evidence quality is degraded or unknown. |
| ``VERIFICATION_AVAILABILITY`` | Verification / provider availability is constrained. |

The last two categories are *not actionable*: they only contribute to
uncertainty. Actionable signals (COMPLIANCE, IDENTITY, DOCUMENT_REUSE)
drive the aggregate score.

Findings are mapped into these categories by their canonical flag ID
(see :func:`ai_verification.risk.correlation._category_for_flag`).

---

## 3. Severity weighting

The risk engine consumes the canonical
:class:`compliance_engine.flags.registry.FlagSeverity` taxonomy.

The numeric mapping lives in :mod:`ai_verification.risk.policy` and
:func:`ai_verification.risk.severity.severity_weight`:

| Severity | Weight |
|---|---|
| ``CRITICAL`` | ``1.00`` |
| ``HIGH`` | ``0.90`` |
| ``MEDIUM`` | ``0.60`` |
| ``LOW`` | ``0.30`` |
| ``INFO`` | ``0.10`` |

The mapping is deliberately weighted toward the upper end so that
even a single HIGH-severity signal is enough on its own to drive a
HIGH_RISK assessment, and a single MEDIUM-severity signal is enough
on its own to drive a REVIEW assessment.

---

## 4. Exact aggregation formula

The aggregate bidder risk score in ``[0, 1]`` is computed as:

```
aggregate_score = clamp(
    strongest_score * (1.0 + boost),
    0.0,
    1.0,
)
```

where:

```
boost = min(
    num_independent_supporting * SUPPORTING_BOOST_PER_SIGNAL,
    SUPPORTING_BOOST_CAP,
)

SUPPORTING_BOOST_PER_SIGNAL = 0.05
SUPPORTING_BOOST_CAP       = 0.30
```

* ``strongest_score`` is the maximum ``score`` over all *actionable*
  deduplicated signals. Actionable means the signal's
  ``is_actionable`` flag is ``True``. Availability-only signals do
  not contribute.
* ``num_independent_supporting`` is the number of deduplicated
  *actionable* signals whose correlation key is *distinct* from the
  strongest signal's correlation key.

The formula guarantees:

1. The strongest signal always dominates the result.
2. Supporting independent signals add at most
   ``SUPPORTING_BOOST_CAP`` of additional score.
3. Ten weak LOW signals cannot outweigh one HIGH signal: the HIGH
   signal still produces the strongest_score and the cap bounds the
   supporting contribution.
4. Correlated/duplicate signals cannot inflate the score beyond a
   bounded amount because deduplication collapses them first.

---

## 5. Correlation and deduplication

Two signals describe the same underlying event iff they have the same
:class:`CorrelationKey`. The correlation key is built from *only*
identifiers that already exist on the source artefacts:

* bidder ID,
* risk category,
* canonical flag ID (when present),
* verification IDs (sorted, deduplicated),
* evidence IDs (sorted, deduplicated),
* document IDs (sorted, deduplicated),
* related bidder IDs (sorted, deduplicated).

The correlation key intentionally **excludes** the finding ID: two
detectors can independently emit findings for the same underlying
event with different IDs, and the risk engine must treat them as one
contribution.

The deduplication algorithm:

1. Sort all signals by ``signal_id`` (deterministic order).
2. Group by ``CorrelationKey``.
3. Within each group, sort by ``-score``, ``-severity_rank``,
   ``signal_id`` and keep the strongest.
4. The number of suppressed duplicates is exposed on the assessment
   as ``deduplicated_signal_count``.

---

## 6. Risk states and thresholds

The aggregate score maps to a discrete :class:`RiskState`:

| State | Condition |
|---|---|
| ``CLEAR`` | aggregate score < 0.30 and no INDETERMINATE condition. |
| ``REVIEW`` | 0.30 <= aggregate score <= 0.60 and no INDETERMINATE condition. |
| ``HIGH_RISK`` | aggregate score > 0.60 and no INDETERMINATE condition. |
| ``INDETERMINATE`` | critical required evidence is unavailable OR evidence quality is UNKNOWN with no actionable signals. |

The thresholds are exactly:

```
REVIEW_THRESHOLD  = 0.30
HIGH_RISK_THRESHOLD = 0.60
```

The decision order is:

1. Apply INDETERMINATE conditions.
2. If there are no actionable signals, return CLEAR.
3. Compute the state from the aggregate score and the strongest
   signal's severity. If the strongest signal's severity is below
   ``MEDIUM``, the bidder is CLEAR (a single INFO / LOW signal
   cannot drive HIGH_RISK).
4. Otherwise:
    * HIGH_RISK if score > 0.60,
    * REVIEW if score >= 0.30,
    * CLEAR otherwise.

---

## 7. Uncertainty semantics

The risk engine distinguishes *risk* from *uncertainty* explicitly.

| Source of uncertainty | Effect |
|---|---|
| UNAVAILABLE / ERROR / NOT_FOUND verification | Emits a ``VERIFICATION_AVAILABILITY`` signal with ``is_actionable=False``. The signal is exposed in the assessment but does NOT contribute to the score. |
| Evidence quality UNKNOWN | Emits an ``EVIDENCE_QUALITY`` signal with ``is_actionable=False``. |
| Critical-required capability not verified | Forces INDETERMINATE when there are no actionable signals. |

The rule "missing critical evidence → INDETERMINATE" only applies
when verifications were *attempted* but the critical capabilities
came back unavailable. If no verifications were attempted at all
AND there are no signals, the bidder is CLEAR (nothing to assess).

A HIGH or CRITICAL actionable signal can keep the score-driven
state even when some critical capabilities are unavailable: the
risk engine never silently overwrites a strong risk signal with
"we couldn't verify everything".

---

## 8. Evidence-quality handling

The risk engine consumes the existing
:class:`ai_verification.evidence_quality.assessment.EvidenceQualityAssessment`
artefacts. It does **not** re-compute quality scores. It maps the
``QualityState`` into risk-signals:

* ``GOOD`` → no signal emitted.
* ``DEGRADED`` → ``EVIDENCE_QUALITY`` signal with
  ``severity=HIGH``, ``is_actionable=False``,
  ``reason_code=EVIDENCE_QUALITY_DEGRADED``.
* ``UNKNOWN`` → ``EVIDENCE_QUALITY`` signal with
  ``severity=HIGH``, ``is_actionable=False``,
  ``reason_code=EVIDENCE_QUALITY_UNKNOWN``.

Important guarantees:

* The signal does NOT lower an EXACT byte reuse finding -- exact
  reuse is unaffected by OCR quality per the existing
  :func:`ai_verification.evidence_quality.should_allow_exact_reuse`
  policy.
* Missing quality metadata alone is not a positive risk signal. If
  there are no assessments and no other signals, the bidder is CLEAR
  (assuming verifications were sufficient).
* Evidence-quality signals are tracked on the assessment and exposed
  as informational signals; they modulate the confidence reported on
  other signals and may drive the state toward INDETERMINATE, but
  they do not contribute to the aggregate score.

---

## 9. Cross-bidder attribution

Cross-bidder document reuse implicates multiple bidders. The risk
engine attributes the same finding to each affected bidder *without*
inventing separate findings. The correlation key carries the
document-pair identity (the trace's ``left_document_id`` /
``right_document_id``) so two bidders connected by the same finding
share the document-pair identity but each correlation key is bound
to a distinct ``primary_bidder_id``.

The aggregate score is computed per-bidder. The same underlying
finding contributes one signal to each affected bidder's assessment
and is never counted as "extra" supporting evidence for the other
bidder.

---

## 10. Deterministic explanation rules

The deterministic summary is generated by
:func:`ai_verification.risk.explanation.render_summary`. The rules:

1. The summary always contains the bidder ID, the risk state, and
   (when non-zero) the aggregate score.
2. When a strongest actionable signal exists, the summary mentions
   its severity and category.
3. The summary may enumerate the number of supporting signals and
   the number of correlated duplicates that were suppressed.
4. For ``INDETERMINATE`` outcomes, the summary states whether the
   cause is missing critical evidence or unknown evidence quality.
5. The summary **never** claims fraud, intent, collusion, or
   illegality.

Example shapes:

> Bidder bidder-1: HIGH_RISK (score 0.81) driven by a HIGH-severity
> document reuse signal; 1 supporting signal.

> Bidder bidder-1: INDETERMINATE; critical required evidence is missing.

---

## 11. Backward compatibility

The bidder risk layer is fully backward-compatible with the existing
project:

* The :class:`compliance_engine.models.verification.Verification`
  contract is unchanged.
* The :class:`ai_verification.models.contracts.VerificationFinding`
  contract is unchanged.
* The :class:`compliance_engine.models.IdentityFinding` contract is
  unchanged.
* The :class:`ai_verification.evidence_quality.assessment.EvidenceQualityAssessment`
  contract is unchanged.
* The cross-bidder detector, identity reconciliation engine, and
  semantic similarity threshold (0.85) are unchanged.

The risk engine only **consumes** these artefacts; it never mutates
them and never calls the network.

---

## 12. Limitations

* The risk layer does **not** make a fraud / illegality determination.
  HIGH_RISK is a judgement based on the evidence present.
* The risk layer does **not** decide eligibility. It only produces a
  structured, auditable risk picture suitable for downstream policy.
* The risk layer does **not** infer bidder identity from the
  bidder_id field; it relies on the upstream systems to populate
  bidder_id correctly.
* INDETERMINATE reflects the engine's epistemic uncertainty. It is
  not equivalent to "the bidder is risky".

---

## 13. Explicit non-claim

> A bidder risk assessment produced by this layer is NOT a fraud
> determination. It is a structured, deterministic summary of the
> evidence available at the time of the run. Any decision about
> eligibility, fraud, or collusion belongs to a human reviewer
> following project policy.
