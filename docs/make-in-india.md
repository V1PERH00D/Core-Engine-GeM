# Make-in-India / Local Content

## Purpose

Evaluate Make-in-India / local-content eligibility (matrix §10). This is a
**provider-free** evidence rule: the threshold always comes from the tender;
there is no universal local-content percentage. Indian origin is never
inferred merely from an Indian company name/address.

## Evidence model

`document_type` `MAKE_IN_INDIA` / `LOCAL_CONTENT` /
`MAKE_IN_INDIA_LOCAL_CONTENT` with fields `local_content_percentage`,
`country_of_origin`, `manufacturing_location`, and any required certificate
field name.

## Rule

`MakeInIndiaRule` (`MAKE_IN_INDIA_001`), `required_providers = ()`.

Operator comparison reuses
`compliance_engine.financial.thresholds.evaluate_threshold` with
`ComparisonOperator` (`>=`, `>`, `=`, `<=`, `<`).

## Parameters (`extra="forbid"`)

- `minimum_local_content_percentage` (float | None)
- `local_content_operator` (default `">="`)
- `required_country_of_origin`
- `required_manufacturing_location`
- `required_certificate`
- `evaluation_date`

## Statuses / flags

| Condition | Compliance | Flag |
|---|---|---|
| missing evidence | MISSING | `LOCAL_CONTENT_EVIDENCE_MISSING` |
| malformed percentage | UNVERIFIABLE | (none) |
| contradictory percentages | UNVERIFIABLE | `LOCAL_CONTENT_CLAIM_INCONSISTENT` |
| below threshold | FAIL | `LOCAL_CONTENT_BELOW_THRESHOLD` |
| origin mismatch | FAIL | `SOURCING_LOCATION_MISMATCH` |
| location mismatch | FAIL | `MANUFACTURING_LOCATION_INELIGIBLE` |
| no threshold configured | NOT_CHECKED | (none) |
| unsupported operator | UNVERIFIABLE | (none) |
| pass | PASS | (none) |

## Storage / audit / explanation

Evidence → `ComplianceResult` → finding → boolean `FlagStateRecord` →
snapshot → `build_flag_lineage`. Findings explainable by `ExplanationEngine`
(downstream only).

## Production limitations

No authoritative local-content portal (e.g. DGFT) is integrated or claimed;
the calculation is a deterministic evidence threshold-evaluation only.