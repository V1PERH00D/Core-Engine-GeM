# Financial Capacity Verification + Financial Evidence Consistency Engine

This document describes the complete vertical slice for Financial Capacity
(PS 26100 §7) implemented in the compliance engine.

---

## 1. Supported Financial Fields

All monetary values use **INR crore** as the explicit unit (suffix `_inr_cr`).
No rupees, lakhs, or crores are mixed silently.

| Field | Model | Type | Unit | Notes |
|-------|-------|------|------|-------|
| Annual turnover | `TurnoverPoint` | `float >= 0` | INR_CRORE | Per financial year |
| Net worth | `NetWorth` | `float` (can be negative) | INR_CRORE | Per financial year |
| Solvency | `Solvency` | `bool` | — | Per financial year |
| Total assets | `BalanceSheet` | `float >= 0` | INR_CRORE | Optional |
| Total liabilities | `BalanceSheet` | `float >= 0` | INR_CRORE | Optional |
| Profit after tax | `BalanceSheet` | `float` | INR_CRORE | Optional |
| Current assets | `BalanceSheet` | `float >= 0` | INR_CRORE | Optional |
| Current liabilities | `BalanceSheet` | `float >= 0` | INR_CRORE | Optional |
| Working capital | `BalanceSheet` | `float` | INR_CRORE | Optional |
| Audited status | `AuditInfo` | `bool` | — | Optional |
| Auditor name | `AuditInfo` | `str` | — | Optional |
| Auditor firm | `AuditInfo` | `str` | — | Optional |
| CA UDIN | `AuditInfo` | `str` | — | Preserved for future verifier |
| Certificate type | `AuditInfo` | `str` | — | Optional |
| Certificate date | `AuditInfo` | `str` | — | Optional |
| CA name | `AuditInfo` | `str` | — | Optional |
| CA membership number | `AuditInfo` | `str` | — | Optional |
| Certificate subject | `AuditInfo` | `str` | — | Optional |

All models are **frozen** (`frozen=True`), forbid extra fields
(`extra="forbid"`), and reject `NaN` / `inf` (`allow_inf_nan=False`).

---

## 2. Money / Unit Conventions

* Every monetary field is suffixed `_inr_cr`.
* The `MoneyUnit.INR_CRORE` enum documents the unit.
* No automatic conversion from rupees/lakhs/crores — the upstream
  extractor must supply values already in INR crore.

---

## 3. Financial Year Normalization

Supported input formats (deterministic):

| Input | Canonical |
|-------|-----------|
| `FY2023-24` | `2023-24` |
| `FY 2023-24` | `2023-24` |
| `fy2023-24` | `2023-24` |
| `2023-24` | `2023-24` |
| `2023-2024` | `2023-24` |
| `2023/24` | `2023-24` |
| `2023 - 24` | `2023-24` |

Rejected (return `None`): bare `2023`, `2023-25`, `2023-2025`,
non-numeric, empty, `None`, `bool`.

Canonical form: `YYYY-YY` where `YY = (YYYY + 1) % 100`.

---

## 4. Turnover Modes & Exact Formulas

A requirement may specify `turnover_mode`:

| Mode | Formula |
|------|---------|
| `AVERAGE_ANNUAL` | `sum(selected_years) / count(selected_years)` |
| `MINIMUM_YEAR` | `min(selected_years)` |

When multiple required years are present and no mode is given,
the rule returns `UNVERIFIABLE` — it never silently picks one.

Only the required financial years (after canonical normalization) are
selected; no nearby or latest year is substituted.

---

## 5. Threshold Semantics

**There is NO universal turnover or net-worth threshold.**

Thresholds **must** come from the tender / requirement parameters:

* `minimum_turnover_inr_cr`
* `minimum_net_worth_inr_cr`

Missing threshold → `NOT_CHECKED` (not a failure).

---

## 6. Supported Comparison Operators

| Operator | Enum | Behavior |
|----------|------|----------|
| `>=` | `GE` | Greater or equal |
| `>` | `GT` | Strictly greater |
| `=` | `EQ` | Equality within `1e-9 * max(1, |threshold|)` |
| `<=` | `LE` | Less or equal |
| `<` | `LT` | Strictly less |

Unknown / missing operator → `UNVERIFIABLE`.

---

## 7. Net Worth Rules

* If `minimum_net_worth_inr_cr` is present and evidence exists:
  - value >= threshold → `PASS`
  - value < threshold → `FAIL` + `NET_WORTH_BELOW_THRESHOLD`
* Missing threshold → `NOT_CHECKED`
* Missing evidence → `MISSING`
* Wrong financial year → `FAIL` + `FINANCIAL_YEAR_MISMATCH`

---

## 8. Solvency Rules

* `require_positive_solvency: true` → evidence must have `is_solvency_positive: true` → `PASS`; `false` → `FAIL` + `SOLVENCY_REQUIREMENT_FAILED`
* `require_positive_solvency: false` → `NOT_APPLICABLE`
* Missing parameter → `NOT_CHECKED`
* Missing evidence → `MISSING`
* **Solvency is never inferred from net worth** unless the spec explicitly says so.

---

## 9. Audit Requirement Semantics

* `require_audited: true`
  - `audited: true` → `PASS`
  - `audited: false` → `FAIL` + `AUDIT_EVIDENCE_MISSING`
  - `audited: None` → `MISSING`
* `require_ca_udin: true` → requires `ca_udin` on audit evidence
* Neither required → `NOT_APPLICABLE`
* No audit evidence at all → `MISSING`

---

## 10. Balance Sheet Completeness

Required fields come from `required_balance_sheet_fields` parameter.

* Missing any listed field → `FAIL` + `BALANCE_SHEET_INCOMPLETE`
* Optional fields are never treated as mandatory
* When `current_assets` and `current_liabilities` are both present,
  derived working capital is `current_assets - current_liabilities`.
  If the sheet also supplies `working_capital_inr_cr` and it differs
  from derived by more than `0.01` crore (₹1 lakh) →
  `FAIL` + `FINANCIAL_DATA_INCONSISTENCY`

---

## 11. Arithmetic Consistency Formulas

* **Working capital** = `current_assets_inr_cr - current_liabilities_inr_cr`
  (only when both inputs present)
* Tolerance: `0.01` crore (₹1 lakh) absolute.
* No inference: missing inputs → derived is `None`, no contradiction.

---

## 12. Financial Consistency Comparison / Tolerance

`check_financial_consistency()` compares same metric + same canonical year
across different documents.

* Tolerance: **0.01 crore (₹1 lakh)** absolute difference.
* Only compares records with `document_id` differing.
* Metrics checked:
  - `turnover_inr_cr`
  - `net_worth_inr_cr`
  - `total_assets_inr_cr`
  - `total_liabilities_inr_cr`
  - `profit_after_tax_inr_cr`
  - `current_assets_inr_cr`
  - `current_liabilities_inr_cr`
* Different years are never compared.
* Findings are `FINANCIAL_DATA_INCONSISTENCY` (HIGH).

---

## 13. Turnover Trend Anomaly Logic

`detect_turnover_trend_anomaly()` runs on ≥ 3 distinct years:

* **Gap anomaly**: missing intermediate year in a contiguous span
  → `TURNOVER_TREND_ANOMALY` (MEDIUM, WARNING).
* **Abrupt transition**: year-over-year ratio > 10.0 (either direction)
  → `TURNOVER_TREND_ANOMALY` (MEDIUM, WARNING).
* **Never** uses words: fraud, manipulation, falsification, deliberate.
* < 3 years → no anomaly.

---

## 14. Exact Flag Mapping

| Flag ID | Severity | When |
|---------|----------|------|
| `TURNOVER_BELOW_THRESHOLD` | HIGH | Turnover < threshold |
| `TURNOVER_PERIOD_MISMATCH` | MEDIUM | Required years not covered |
| `TURNOVER_DATA_MISSING` | MEDIUM | Some required years absent |
| `TURNOVER_TREND_ANOMALY` | MEDIUM | Gap or abrupt jump (WARNING) |
| `NET_WORTH_BELOW_THRESHOLD` | HIGH | Net worth < threshold |
| `SOLVENCY_REQUIREMENT_FAILED` | HIGH | Positive solvency required but false |
| `SOLVENCY_THRESHOLD_NOT_MET` | HIGH | Legacy flag (unused) |
| `FINANCIAL_YEAR_MISMATCH` | MEDIUM | Evidence year ≠ required year |
| `FINANCIAL_DATA_INCONSISTENCY` | HIGH | Cross-doc numeric diff > tolerance |
| `BALANCE_SHEET_INCOMPLETE` | MEDIUM | Required BS field missing |
| `AUDIT_EVIDENCE_MISSING` | MEDIUM | Audited/CA required but missing |
| `AUDITED_STATUS_MISSING` | MEDIUM | Legacy flag (unused) |
| `FINANCIAL_CAPACITY_MISSING` | HIGH | No financial evidence at all |
| `FINANCIAL_VERIFICATION_UNAVAILABLE` | MEDIUM | Legacy flag (unused) |
| `FINANCIAL_YEAR_MISSING` | HIGH | Legacy flag (unused) |
| `FINANCIAL_PROFILE_ANOMALY` | MEDIUM | Cross-bidder duplicate signal |

---

## 15. Requirement Parameter Schema

```json
{
  "focus": "TURNOVER | NET_WORTH | SOLVENCY | AUDIT | BALANCE_SHEET",
  "minimum_turnover_inr_cr": 25.0,
  "turnover_operator": ">= | > | = | <= | <",
  "turnover_mode": "AVERAGE_ANNUAL | MINIMUM_YEAR",
  "required_financial_years": ["2021-22", "2022-23", "2023-24"],
  "minimum_net_worth_inr_cr": 5.0,
  "require_positive_solvency": true,
  "require_audited": true,
  "require_ca_udin": true,
  "required_ca_subject": "Financial statements as at 31-03-2024",
  "required_balance_sheet_fields": ["total_assets_inr_cr", "current_assets_inr_cr", ...]
}
```

All fields optional; `extra="forbid"` rejects typos.

---

## 16. Evidence Quality Integration

* Extraction confidence (`Evidence.confidence`) is preserved on all
  financial model fields.
* `CrossDocumentConsistencyEngine` lowers finding confidence when
  evidence quality is `DEGRADED` (-0.1) or `UNKNOWN` (-0.2).
* Missing OCR/field confidence → `confidence=None` on the model,
  **not** a financial failure.

---

## 17. Risk Engine Integration

Financial findings map to `RiskCategory.COMPLIANCE` and are actionable
(contribute to score) when status is `FAIL` or `WARNING`.

| Flag | Risk Category | Severity |
|------|---------------|----------|
| `TURNOVER_BELOW_THRESHOLD` | COMPLIANCE | HIGH |
| `NET_WORTH_BELOW_THRESHOLD` | COMPLIANCE | HIGH |
| `SOLVENCY_REQUIREMENT_FAILED` | COMPLIANCE | HIGH |
| `FINANCIAL_DATA_INCONSISTENCY` | COMPLIANCE | HIGH |
| `AUDIT_EVIDENCE_MISSING` | COMPLIANCE | MEDIUM |
| `FINANCIAL_YEAR_MISMATCH` | COMPLIANCE | MEDIUM |
| `TURNOVER_PERIOD_MISMATCH` | COMPLIANCE | MEDIUM |
| `TURNOVER_TREND_ANOMALY` | COMPLIANCE | MEDIUM (WARNING) |
| `BALANCE_SHEET_INCOMPLETE` | COMPLIANCE | MEDIUM |
| `TURNOVER_DATA_MISSING` | COMPLIANCE | MEDIUM |

Correlated signals (same flag + same evidence) are deduplicated.
Missing evidence (`MISSING` status) does not auto-become high risk.

---

## 18. Cross-Document Integration

The financial slice **reuses** the existing `CrossDocumentConsistencyEngine`:

* `normalize_financial_profile(evidence)` → `FinancialProfile`
* `check_financial_consistency(profile)` → `ConsistencyFinding[]`
* `consistency_finding_to_verification_finding()` → `VerificationFinding`
* `detect_turnover_trend_anomaly()` → `TrendAnomaly`
* `trend_anomaly_to_verification_finding()` → `VerificationFinding`

No second cross-document engine is created. Financial comparisons
remain traceable to actual `Evidence` refs.

---

## 19. CA / UDIN Compatibility

Financial models preserve these fields for a future verifier:

* `ca_udin`
* `certificate_type`
* `certificate_date`
* `ca_name`
* `ca_membership_number`
* `certificate_subject`

The rule can require `require_ca_udin: true` and will fail if absent.
**No UDIN authenticity is claimed** — this is a compatibility seam.

---

## 20. Explanation Examples

> "The tender requires average annual turnover >= ₹25 crore for
> FY2021-22 through FY2023-24. The available turnover evidence
> averages ₹18.4 crore across the required years."

> "The tender requires net worth >= ₹10 crore for 2023-24. The
> available net worth evidence records ₹5.0 crore, which falls
> below the requirement."

> "Turnover changed abruptly between 2022-23 (₹1.0 crore) and
> 2023-24 (₹100 crore). The year-over-year magnitude change
> exceeds the documented review threshold and warrants
> investigation."

---

## 21. Focused Test Count

| Test Module | Tests |
|-------------|-------|
| `test_years.py` | 8 |
| `test_financial_models.py` | 21 |
| `test_arithmetic.py` | 6 |
| `test_thresholds.py` | 15 |
| `test_normalization.py` | 10 |
| `test_evaluation.py` | 36 |
| `test_consistency.py` | 11 |
| `test_trend.py` | 7 |
| `test_engine_integration.py` | 12 |
| `test_risk_integration.py` | 11 |
| `test_quality_integration.py` | 6 |
| `test_audit_explanations.py` | 7 |
| **Total (new)** | **150** |

Note: some overlap with rewritten `test_financial.py` (12 tests).

---

## 22. Final Full-Suite Count

**1270 tests passed** (1062 baseline + 208 new financial tests).

---

## 23. Limitations

* No universal financial threshold exists — tender context supplies
  all thresholds.
* Financial anomaly ≠ fraud — trend anomaly is a WARNING only.
* Missing evidence ≠ failed financial requirement → `MISSING` or
  `NOT_CHECKED` depending on whether parameters are present.
* Provider unavailability ≠ financial failure — the rule is
  provider-free and runs without any external lookup.
* CA/UDIN authenticity is **not** verified — fields are preserved
  for a future authoritative verifier.
* The upstream evidence schema is not yet fixed; `normalize_financial_profile`
  provides a typed seam. Values are never fabricated when fields are absent.
* Cross-document consistency uses a fixed absolute tolerance (₹1 lakh);
  relative tolerance is not applied.
* Turnover trend detection uses a documented heuristic (10x ratio),
  not a statistical model.
