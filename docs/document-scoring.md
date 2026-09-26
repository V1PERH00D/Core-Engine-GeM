# Document Priority Scoring

The document scoring engine is a deterministic supplementary diagnostic in
`src/ai_verification/document_scoring/`. It answers:

> How complete, reliable, and important is the submitted document information,
> and which procurement review category should it receive?

It does **not** decide compliance, replace canonical boolean flags, or use an
LLM. The existing `compliance` payload remains exactly:

```json
{"bidder_id": "...", "flags": {"<CANONICAL_FLAG_ID>": true}}
```

The application exposes the result separately as `ApplicationResult.document_score`.

## 1. Score and categories

The score is in the closed range `0–100`; higher is better.

| Category | Rule |
|---|---|
| `GREEN` | Score is at least `80`, no priority document is missing, and no material finding is present. |
| `YELLOW` | Score is `50–79.99`, or an otherwise non-blocking document/type needs review. |
| `RED` | Score is below `50`, a `CRITICAL` or `HIGH` document is missing/failed, or a material `HIGH`/`CRITICAL` finding is present. |

The thresholds are configurable through `DocumentScoringPolicy`. A score is a
review aid, not an automatic acceptance/rejection decision.

## 2. Document priority policy

The default policy assigns weights to canonical document families:

| Priority | Default families | Weight |
|---|---|---:|
| `CRITICAL` | GST, PAN, Debarment, Bidder Identity | `1.00` |
| `HIGH` | Udyam/MSME, MCA21, BIS, ITR/financial, Make in India, OEM | `0.80` |
| `MEDIUM` | DigiLocker, EPFO, ESIC, Startup, NSIC, CA/UDIN | `0.55` |
| `LOW` | Unknown/supporting document types | `0.25` |

Aliases are normalized before scoring (`GSTN` → `GST`, `PAN_CARD` → `PAN`,
`ITR`/`BALANCE_SHEET` → `FINANCIAL`, and so on). Tender-specific priorities
can be supplied by constructing a new `DocumentScoringPolicy`; no scoring code
change is required.

## 3. Per-document signals

Each submitted document starts at `100`. The engine applies bounded,
explainable deductions for:

- no normalized evidence (`-35`);
- low average evidence confidence (`-15` below the policy threshold);
- deterministic compliance status (`FAIL`, `MISSING`, `UNVERIFIABLE`, or
  `WARNING`);
- authoritative verification status (`INVALID`, `NOT_FOUND`, `INACTIVE`,
  `UNAVAILABLE`, or `ERROR`);
- a canonical `HIGH` or `CRITICAL` finding associated with the document
  (`-25`);
- degraded or unknown evidence quality when a quality assessment is supplied.

A document with no evidence is not silently treated as valid. The reason codes
in `DocumentScoreDetail.reasons` make every deduction observable.

## 4. Final aggregation

The final score is the weighted mean of all scored document details:

```text
final_score = sum(document_score * document_weight) / sum(document_weight)
```

Expected document families derived from applicable requirements are added as
missing details when no submitted document represents that family. This means
a high-priority missing document cannot be hidden by many clean supporting
documents.

The engine is stateless, deterministic, and side-effect free. It performs no
network calls and does not mutate the supplied evidence, results, findings, or
verification records.

## 5. API and application output

Standalone use:

```python
from ai_verification.document_scoring import DocumentInput, DocumentScoringEngine

assessment = DocumentScoringEngine().score(
    "bidder-1",
    submission_id="sub-1",
    documents=[DocumentInput(document_id="doc-gst", document_type="GST")],
    evidence=[...],
    compliance_results=[...],
    verification_records=[...],
    findings=[...],
)
print(assessment.category, assessment.score, assessment.summary)
```

The application result contains:

```json
{
  "document_score": {
    "bidder_id": "...",
    "submission_id": "...",
    "score": 0.0,
    "category": "RED",
    "reason_codes": ["DOCUMENT_MISSING"],
    "documents": []
  }
}
```

The score is reconstructed from persisted documents, evidence, results,
verifications, and findings when a completed submission is retrieved. It is not
written into the boolean flag snapshot.

## 6. Interpretation and limitations

- `GREEN` means the document information is strong enough for the configured
  review policy; it is not a legal certification.
- `YELLOW` identifies uncertainty or incomplete supporting information and
  should normally be routed for human review.
- `RED` identifies a high-priority concern or a material document anomaly.
- Unknown document types are intentionally conservative and produce a
  `YELLOW` category unless a material finding makes them `RED`.
- The policy currently uses document type, evidence, deterministic results,
  verification records, and findings. OCR metadata, issuer signatures, expiry
  dates, and tender-specific field completeness can be added as additional
  explicit signals in a later policy version.
