# OEM / Manufacturer Authorization

## Purpose

Evaluate OEM (Original Equipment Manufacturer) authorization evidence
(matrix §17). This is a **provider-free** rule: there is no authoritative
OEM portal contract in the project, so the rule deterministically checks
submitted evidence against explicitly configured tender requirements.

## Evidence model

`document_type` `OEM` / `OEM_AUTHORIZATION` / `OEM_AUTHORIZATION_DOCUMENT`
with fields `oem_name`, `authorized_bidder`, `authorization_type`,
`authorized_product_range`, `authorization_territory`, `valid_from`,
`valid_until`.

## Rule

`OemAuthorizationRule` (`OEM_AUTHORIZATION_001`), `required_providers = ()`.

Name matching reuses the existing identity normalizer
(`normalize_identity_name`). Name similarity by itself never establishes
legal authorization.

## Parameters (`extra="forbid"`)

- `require_authorization` (bool | None)
- `required_oem`
- `required_bidder`
- `required_authorization_type`
- `required_product`
- `required_territory`
- `evaluation_date` (ISO `YYYY-MM-DD`)

## Statuses / flags

| Condition | Compliance | Flag |
|---|---|---|
| missing evidence | MISSING | `OEM_AUTHORIZATION_NOT_PROVIDED` |
| OEM/bidder name mismatch | FAIL | `OEM_NAME_MISMATCH` |
| authorization type mismatch | FAIL | `AUTHORIZATION_TYPE_MISMATCH` |
| product range insufficient | FAIL | `AUTHORIZED_PRODUCT_RANGE_INSUFFICIENT` |
| territory mismatch | FAIL | `AUTHORIZATION_TERRITORY_MISMATCH` |
| expired | FAIL | `OEM_AUTHORIZATION_EXPIRED` |
| not yet valid | FAIL | `OEM_AUTHORIZATION_INVALID` |
| malformed dates | UNVERIFIABLE | (none) |
| all checks pass | PASS | (none) |

## Validity semantics

Explicit `evaluation_date` only (never the machine clock). Both validity
ends inclusive; malformed dates → controlled `UNVERIFIABLE`.

## Storage / audit / explanation

Evidence → `ComplianceResult` → finding → boolean `FlagStateRecord` →
snapshot → `build_flag_lineage`. Findings explainable by `ExplanationEngine`
(downstream only).

## Production limitations

No OEM portal/letter verification service is integrated or claimed; the
rule is evidence-only.