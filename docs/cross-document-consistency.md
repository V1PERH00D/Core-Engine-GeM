# Cross-Document Consistency Engine

## Purpose

`src/ai_verification/cross_document/` provides a deterministic,
auditable engine that compares field-level evidence across a
single bidder's submitted documents and surfaces meaningful
cross-document inconsistencies as findings.

The engine handles five dimensions:

* **IDENTIFIER** — tax / registration identifiers (GSTIN, PAN,
  UDYAM, CIN, UDIN, etc.).
* **ADDRESS** — registered addresses across documents.
* **DATE** — date / validity evidence (filing date, expiry, etc.).
* **PRODUCT** — product / class descriptions.
* **MANUFACTURER** — manufacturer / OEM names.

Bidder **legal-name** reconciliation belongs to the existing
`ai_verification.identity` package. This subpackage **deliberately
does not duplicate** that engine.

## Design constraints

* **Deterministic**, no AI / no embeddings / no network calls.
* **Typed Pydantic v2 models** (`extra="forbid"`, frozen where
  appropriate).
* **No provider re-querying**: the engine consumes existing
  `Evidence` artefacts only.
* **No "majority truth"** policy: the engine produces an evidence
  graph; downstream policy decides how to act.
* **No fuzzy matching** in this milestone. Identifier equality is
  normalized only by case / whitespace / edge punctuation. Address
  equality is normalized by case / whitespace / line-break / safe
  punctuation. Manufacturer equality reuses the conservative
  identity-name normalizer (no abbreviation rewriting).
* **No synonym dictionary**. Only the documented normalizations
  in `normalization.py` are applied.

## Supported field types

The engine classifies each `Evidence` field via the
`FIELD_CLASSIFICATION` matrix in `extraction.py`. Each
`(document_type, field_name)` pair maps to exactly one
`ConsistencyDimension`:

| Dimension      | Recognized fields                                                  |
|----------------|--------------------------------------------------------------------|
| `IDENTIFIER`   | `gstin`, `pan_number`, `udyam_registration_number`, `cin`, `ca_udin` |
| `ADDRESS`      | `registered_address` (across multiple document families)            |
| `DATE`         | `filing_date`, `assessment_year`, `financial_year`                  |
| `PRODUCT`      | `supplier_class`, `product_description`                             |
| `MANUFACTURER` | `manufacturer` on OEM / OEM authorization documents                  |

Fields not in the matrix are surfaced with
`FieldStatus.NOT_QUERIED` and excluded from comparison.

## Normalization rules

Each dimension has its own deterministic, versioned normalizer.
The version stamp is recorded on every produced comparison so
auditors can verify which rules were in effect.

### Identifier (`cross-document-identifier-v1`)

1. `None` / non-string / empty / whitespace-only → `None`.
2. Unicode NFKC.
3. Strip surrounding whitespace.
4. Collapse repeated internal whitespace to a single space.
5. Strip edge punctuation (`.`, `,`, `;`, `:` at start or end).
6. ASCII uppercase.

### Address (`cross-document-address-v1`)

1. `None` / non-string / empty → `None`.
2. Unicode NFKC.
3. Strip surrounding whitespace.
4. Normalize line breaks (`\r\n`, `\r` → `\n`).
5. Collapse internal whitespace per line.
6. Drop empty lines.
7. Trim each line.
8. Strip harmless edge punctuation.
9. Comma-spacing normalization.
10. Case-fold (lowercase).

No geocoding. No synonym dictionary.

### Date (`cross-document-date-v1`)

Accepts ISO-8601 (`YYYY-MM-DD`, `YYYY/MM/DD`,
`YYYY-MM-DDTHH:MM:SS`), `DD-MM-YYYY`, `DD/MM/YYYY`, and
`DD-Mon-YYYY`. Returns canonical `YYYY-MM-DD`.

### Product (`cross-document-product-v1`)

Same conservative pipeline as address minus line-break handling.
Case-folded.

### Manufacturer (`identity-name-v1`)

Reuses `ai_verification.identity.normalization.normalize_legal_name`
so the cross-document engine and the identity engine apply the
same canonical form to manufacturer names. **No** abbreviation
rewriting (e.g. `Pvt Ltd` is **not** rewritten to `Private
Limited`).

## Document compatibility rules

Not every field pair is comparable. The `are_comparable()` helper
in `extraction.py` implements the explicit rules:

| Pair                                  | Comparable? | Reason                                    |
|---------------------------------------|-------------|-------------------------------------------|
| Same identifier kind, same field name | ✅          | "Same identifier kind ... same field name" |
| Different identifier kinds (GSTIN vs PAN) | ❌    | "Incompatible identifier kinds"           |
| Different identifier fields (gstin vs pan_number) | ❌ | "Identifier field names differ"      |
| Dates with same role + same document family | ✅ | "Same date role ... compatible families" |
| Dates with different roles            | ❌          | "Date fields are not comparable"          |
| Dates with unknown roles on both sides | ❌         | "Date fields are not comparable"          |
| Same field name (address / product / manufacturer) | ✅ | "Address / Product / Manufacturer fields share ..." |
| Different dimensions                  | ❌          | "Dimensions differ"                       |
| One side missing / invalid / unavailable | ❌       | "Left/Right field is unavailable"         |

The compatibility reason is preserved verbatim on every
`PairwiseComparison.comparability_reason` so the auditor can see
*why* a pair was or was not compared.

## Status semantics

The engine distinguishes source / field status with a small
typed taxonomy (`FieldStatus`):

| Status                  | Meaning                                                        |
|-------------------------|----------------------------------------------------------------|
| `NOT_QUERIED`           | Field is not classifiable into a supported dimension.           |
| `AVAILABLE`             | Field is present, valid, and ready to participate in comparison.|
| `MISSING`               | Field's `Evidence.value` is `None`. Never becomes a mismatch.   |
| `UNAVAILABLE`           | Provider / extraction layer failed to retrieve the field.       |
| `INVALID`               | Field is present but cannot be normalized for its dimension.    |
| `INSUFFICIENT_EVIDENCE` | Used by the comparison layer when a pair cannot be compared.      |

**Missing and unavailable evidence never become a consistency
mismatch.** A document with no extracted field for a dimension
contributes no negative assertion.

## Comparison classifications

| Dimension     | Outcomes                                                                         |
|---------------|----------------------------------------------------------------------------------|
| Identifier    | `MATCH_EXACT`, `MATCH_NORMALIZED`, `MISMATCH`, `INSUFFICIENT_EVIDENCE`            |
| Address       | `EXACT`, `NORMALIZED_MATCH`, `MISMATCH`, `INSUFFICIENT_EVIDENCE`                 |
| Date          | `MATCH`, `MISMATCH`, `VALIDITY_CONFLICT`, `INSUFFICIENT_EVIDENCE`                 |
| Product       | `EXACT`, `NORMALIZED_MATCH`, `MISMATCH`, `INSUFFICIENT_EVIDENCE`                 |
| Manufacturer  | `MATCH_EXACT`, `MATCH_NORMALIZED`, `MISMATCH`, `INSUFFICIENT_EVIDENCE`            |

A `MISMATCH` outcome is a material inconsistency. `MATCH_*`
outcomes are intentionally silent (no finding). `INSUFFICIENT_EVIDENCE`
is also silent.

`VALIDITY_CONFLICT` (date dimension only) is emitted when the
comparison is supplied with an explicit `evaluation_date_iso` and
both compared dates predate it. The engine never uses
machine-clock time inside its decision logic; callers must pass
an explicit evaluation date when they want validity reasoning.

## Confidence handling

* The base confidence of a finding is `0.9` for `MISMATCH` and
  `0.95` for `VALIDITY_CONFLICT`.
* When the evidence-quality assessment for either side is
  `DEGRADED`, confidence drops by `0.1`; when `UNKNOWN`, by `0.2`.
* The confidence is clamped to `[0.0, 1.0]`.
* Exact identifier equality is **never suppressed** by OCR-quality
  concerns: the comparison is based on the normalized identifier
  value, which is exact regardless of OCR confidence.

## Evidence-quality integration

The engine reuses the existing `ai_verification.evidence_quality`
subsystem. Each `FieldObservation` carries:

* `quality_state`, `quality_score`, `quality_reasons` (populated
  when a quality lookup is supplied).

The `PairwiseComparison` propagates the per-side quality metadata
so downstream consumers can audit the OCR confidence that
backed each side of the comparison.

The engine never invents quality state. When no quality lookup is
supplied the comparison carries `quality_state=None` and the
confidence formula assumes no degradation.

## Finding semantics

Each mismatching comparison produces one
`VerificationFinding`. The flag ID is dimension-specific:

| Dimension      | Flag ID                                  | Severity |
|----------------|------------------------------------------|----------|
| Identifier     | `CROSS_DOCUMENT_IDENTIFIER_CONFLICT`     | CRITICAL |
| Address        | `CROSS_DOCUMENT_ADDRESS_CONFLICT`        | HIGH     |
| Date           | `CROSS_DOCUMENT_DATE_SEQUENCE_INVALID`   | HIGH     |
| Product        | `CROSS_DOCUMENT_PRODUCT_MISMATCH`        | MEDIUM   |
| Manufacturer   | `CROSS_DOCUMENT_MANUFACTURER_MISMATCH`   | MEDIUM   |

Every finding carries:

* `bidder_id`
* `flag_id`, `severity` (copied from the canonical flag registry)
* `confidence` (deterministic, propagated from comparison)
* `explanation` (deterministic, free of secrets, preserves original
  and normalized values)
* `evidence_refs` (both sides' `evidence_id`, verbatim)
* `verification_refs` (both sides' identifiers)
* `finding_id` (`cross-document:{bidder_id}:{dimension}:{left}:{right}`)

Findings never claim fraud, forgery, collusion, illegality, or
intentional misrepresentation. They state that the supplied
evidence is inconsistent.

## Identity-engine boundary

`ai_verification.identity` reconciles bidder **legal names**
across sources (GST, PAN, Udyam, MCA). It uses
`NAME_NORMALIZATION_VERSION = identity-name-v1`.

`ai_verification.cross_document` analyzes **field-level**
consistency across documents (identifiers, addresses, dates,
products, manufacturers). Manufacturer-name normalization reuses
the identity package's conservative algorithm so that
`Acme Industries Ltd` produced by the identity engine and by
the cross-document engine canonicalize to the same string.

## Cross-bidder boundary

`ai_verification.cross_bidder` analyzes **document-level**
relationships across bidders (near-duplicate detection, address
sharing, etc.). It uses document-level similarity thresholds and
the `SimilarityTrace` model.

`ai_verification.cross_document` analyzes **field-level**
consistency across documents belonging to a single bidder. It
uses field-level normalization and the `PairwiseComparison`
model.

The two engines share no semantics: cross-bidder looks at
"are these two bidders the same entity based on document
overlap"; cross-document looks at "is this single bidder's
evidence internally consistent across documents".

## Bidder risk integration

The risk engine's flag-to-category mapping is updated by this
milestone. Cross-document flags map to `RiskCategory.IDENTITY`
because they describe evidence-consistency, which is closer to
identity-style verification than to document reuse.

The risk aggregation formula is unchanged: cross-document
findings flow through the existing `BidderRiskEngine.assess()`
entry point alongside the existing findings.

## Limitations

* No fuzzy / semantic / embedding-based matching in this milestone.
* Identifier comparison is restricted to the documented kinds.
  Adding new identifier kinds requires updating the
  `IdentifierKind` enum **and** the `FIELD_CLASSIFICATION` matrix.
* Date validity reasoning only triggers when the caller passes
  an explicit `evaluation_date_iso`.
* Manufacturer mismatch is reported separately from bidder legal
  name mismatch, by design.
* No transliterated Indian-language support beyond Unicode NFKC.

## Future work (intentionally separate)

* Per-document provenance weighting (beyond the current
  evidence-quality integration).
* Optional fuzzy identifier matching (gated on evidence quality).
* Cross-bidder identity reconciliation reusing the same engine.
