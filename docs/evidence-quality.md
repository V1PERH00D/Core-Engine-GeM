# Evidence Quality and Reliability Engine

This document describes the typed evidence-quality subsystem added to
the AI Verification Engine. It complements (and does not replace) the
existing cross-bidder detection logic.

The subsystem lives at:

```
src/ai_verification/evidence_quality/
  __init__.py
  state.py            # QualityReason, QualityState enums
  signals.py          # Input observable bundles
  scoring.py          # Deterministic scoring formulas
  assessment.py       # Output assessment model
  evaluator.py        # EvidenceQualityEvaluator Protocol + Static impl
  document_meta_evaluator.py   # Default DocumentMeta-backed evaluator
  gating.py           # Conservative quality gating policy
```

## Quality dimensions

The engine tracks four orthogonal quality dimensions, each scored in
`[0.0, 1.0]`:

| Dimension            | Captures                                                        |
|----------------------|-----------------------------------------------------------------|
| `ocr_quality`        | Reliability of the OCR pipeline's text extraction.              |
| `field_quality`      | Reliability of the field-extraction pipeline (per-field conf).  |
| `completeness`       | Fraction of required fields / raw text / metadata that is present.|
| `metadata_reliability`| Reliability of the document-type confidence and metadata presence.|

## Exact quality score formula

```
overall_quality_score = (
    OCR_WEIGHT          * ocr_quality          +  # 0.30
    FIELD_WEIGHT        * field_quality        +  # 0.30
    COMPLETENESS_WEIGHT * completeness         +  # 0.25
    METADATA_WEIGHT     * metadata_reliability    # 0.15
)
```

The weights are intentionally fixed and tuned so the score is
dominated by the two extraction-quality signals and modulated by
completeness and metadata reliability. Changing the weights is a
deliberate policy change.

### Per-dimension formulas

* **OCR quality**: returned OCR confidence if present; `0.5` if OCR
  text was present but no confidence reported; `0.0` otherwise.
* **Field quality**: returned field confidence if present; `0.5` if
  every required field is present but no confidence reported; `0.0`
  if a required field is missing and no confidence reported.
* **Completeness**: `0.85 * (present_required / total_required) +
  0.10 * (raw_text_present) + 0.05 * (metadata_present)`.
* **Metadata reliability**: returned document-type confidence if
  present; `0.5` if metadata is present but no document-type
  confidence reported; `0.0` otherwise.

## Quality states

The overall score is mapped to one of three states:

* `GOOD`     -- score `>= 0.85` AND no reasons.
* `DEGRADED` -- score below 0.85, OR a non-critical reason was
  emitted. The finding may still be emitted with a conservative
  confidence.
* `UNKNOWN`  -- at least one critical reason (`DOCUMENT_TEXT_MISSING`,
  `METADATA_INCOMPLETE`). The evidence is not trustworthy enough for
  semantic reuse.

## Gating policy

The gate is conservative: it only ever *adds* suppression on top of
the existing template gate. It never weakens the existing rules.

* **EXACT** reuse: gate returns `True` regardless of quality state.
  A cryptographic byte-hash equality does not depend on OCR.
* **NORMALIZED** reuse: same as EXACT.
* **LEXICAL** reuse: not affected by the quality gate.
* **SEMANTIC** reuse: gate returns `True` only when:
  * state is `GOOD`, or
  * state is `DEGRADED` and the overall score is at or above
    `SEMANTIC_MINIMUM_QUALITY_SCORE` (0.50).
  * state `UNKNOWN` always denies.

## Difference between low quality and unknown quality

* **Low quality** (e.g. `OCR_LOW`) means the engine *knows* the
  evidence is imperfect. The numeric score drops but the state is
  `DEGRADED` and the engine can still emit the finding.
* **Unknown quality** (e.g. `DOCUMENT_TEXT_MISSING`) means the
  engine cannot establish any reliability for the evidence. The
  state is `UNKNOWN` and the gate refuses semantic emission.

This distinction is preserved end-to-end: `QualityReason` codes are
typed, and `QualityState.UNKNOWN` is a different classification from
`QualityState.DEGRADED` with a high score.

## Why exact hash reuse is not dependent on OCR

`SimilarityLayer.EXACT` compares file hashes, which are computed on
the raw bytes of the document. The OCR pipeline only contributes the
*extracted text* used by the LEXICAL and SEMANTIC layers. A perfect
hash equality cannot be inflated by OCR noise, so the gate returns
`True` regardless of `QualityState`.

## Deterministic reason codes

`QualityReason` is a `StrEnum` with stable string values. The codes
are:

| Code                       | Trigger                                                       |
|----------------------------|---------------------------------------------------------------|
| `OCR_LOW`                  | Reported OCR confidence is below 0.85.                        |
| `OCR_MISSING`              | No OCR confidence was reported.                               |
| `FIELD_CONFIDENCE_LOW`     | Reported field confidence is below 0.85.                      |
| `FIELD_CONFIDENCE_MISSING` | No field confidence was reported.                             |
| `DOCUMENT_TEXT_MISSING`    | Raw text could not be retrieved.                              |
| `REQUIRED_FIELD_MISSING`   | One or more required metadata fields are absent.              |
| `DOCUMENT_TYPE_CONFIDENCE_LOW` | Reported document-type confidence is below 0.85.          |
| `METADATA_INCOMPLETE`      | No metadata is present at all.                                |

Reasons are deduplicated while preserving declaration order in the
final assessment.

## Integration with SimilarityTrace

`QualitySignals` (in `cross_bidder/trace.py`) was extended with six
optional, backward-compatible fields:

* `quality_state`       -- the `QualityState` value
* `quality_reasons`     -- list of `QualityReason` strings
* `completeness`        -- per-pair completeness score
* `ocr_quality`         -- per-pair OCR component score
* `field_quality`       -- per-pair field component score
* `metadata_reliability` -- per-pair metadata-reliability score

The three legacy fields (`ocr_confidence`, `field_confidence`,
`quality_score`) are populated from the assessment's component
scores, so the existing cross-bidder confidence formula continues to
consume them unchanged.

## Confidence formula -- unchanged

The cross-bidder confidence formula remains authoritative:

```
S = strongest passing similarity
C = mean available corroboration
Q = min(mean OCR confidence, mean relevant field confidence)
confidence = clamp01(0.60*S + 0.25*C + 0.15*Q) * template_gate_factor
```

The new subsystem supplies the Q inputs cleanly via the assessment's
component scores. The formula, coefficients, and 0.70 emission
threshold are not modified.

## How future production extraction systems can supply richer signals

The default `DocumentMetaQualityEvaluator` consumes only the two
confidence fields already present on `DocumentMeta`
(`ocr_confidence`, `document_type_confidence`). Production extraction
systems that report per-field confidences, richer OCR confidences,
or document-type classifications should:

1. Build a custom subclass of `DocumentMetaQualityEvaluator` (or
   implement the `EvidenceQualityEvaluator` Protocol directly).
2. Populate `DocumentQualitySignals` with the richer fields:
   * `OCRQualitySignals.ocr_confidence`
   * `FieldQualitySignals.field_confidence`
   * `FieldQualitySignals.required_fields_missing`
   * `MetadataReliabilitySignals.document_type_confidence`
   * `CompletenessSignals.*`
3. Inject the evaluator via the
   `quality_evaluator` parameter on `VerificationEngine`,
   `CrossBidderOrchestrator`, `detect_cross_bidder_anomalies`,
   or `compare_two_documents`.

No LLM call, network call, or new external API is required.

## Limitations

* The default evaluator cannot distinguish "no per-field confidence
  was reported" from "per-field confidence was 0.5"; both surface as
  `FIELD_CONFIDENCE_MISSING`. Future work can introduce a richer
  `FieldQualitySignals` with explicit per-field confidences.
* The quality gate only suppresses SEMANTIC emission. EXACT,
  NORMALIZED, and LEXICAL are unaffected, so an attacker who can
  forge a normalized-text hash will still trigger a finding.
* The default `GOOD_THRESHOLD = 0.85` is conservative. The threshold
  can be tuned by callers, but the conservative default is the
  intended baseline.
