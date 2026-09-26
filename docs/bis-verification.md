# BIS / Product Certification Verification

## Purpose

Verify Bureau of Indian Standards (BIS) product certification evidence
against tender-derived requirements (matrix §15). BIS certification is
*not* universally required: it is evaluated only for requirements that
explicitly ask for it.

## Evidence model

One `Evidence` item of `document_type` `BIS` (or `BIS_CERTIFICATION` /
`BIS_PRODUCT_CERTIFICATION`) with `field_name == "certificate_number"`.

Normalized provider payload (`NormalizedBisData`): `licence_status`,
`certificate_number`, `product_description`, `scope_of_certification`,
`manufacturing_location`, `quality_grade`, `manufacturer`, `standard`,
`valid_from`, `valid_until`.

## Provider boundary

`BisAdapter` implements the existing `VerificationProvider.verify`
contract and routes through the generic `VerificationTransport` seam. The
parser derives the *domain* `VerificationStatus` from the source payload
(NOT from the transport status code).

## Rule

`BisCertificationRule` (`BIS_CERTIFICATION_001`), `required_providers = (BIS,)`.

## Parameters (`extra="forbid"`)

- `require_bis` (bool | None)
- `required_status`
- `required_standard`
- `required_product`
- `required_manufacturer`
- `required_facility_location`
- `evaluation_date` (ISO `YYYY-MM-DD`)

Only explicitly configured parameters are checked; no universal
certification requirement is assumed.

## Statuses

| Provider status | Compliance outcome            | Flag                         |
|---|---|---|
| VERIFIED        | interpreted against parameters | (per below)                  |
| INVALID         | FAIL                          | `BIS_CERTIFICATE_INVALID`    |
| NOT_FOUND       | UNVERIFIABLE                  | `BIS_CERTIFICATE_NOT_FOUND`  |
| UNAVAILABLE     | UNVERIFIABLE                  | `BIS_VERIFICATION_UNAVAILABLE` |
| ERROR           | UNVERIFIABLE                  | `BIS_VERIFICATION_UNAVAILABLE` |

Missing certificate evidence → `MISSING` + `REQUIRED_FIELD_MISSING`
(never provider `NOT_FOUND`).

## Validity semantics

Validity is evaluated only against an explicit `evaluation_date`; the
machine clock is never used. Both ends are inclusive; a future or expired
certificate fails (`BIS_CERTIFICATE_EXPIRED`, or `BIS_CERTIFICATE_INVALID`
for not-yet-valid). Malformed dates → controlled `UNVERIFIABLE`.

## Flags

`BIS_CERTIFICATE_INVALID`, `BIS_CERTIFICATE_NOT_FOUND`,
`BIS_CERTIFICATE_EXPIRED`, `BIS_PRODUCT_SCOPE_MISMATCH`,
`BIS_FACILITY_LOCATION_INELIGIBLE`, `BIS_CERTIFICATE_SUSPENDED_REVOKED`,
`BIS_VERIFICATION_UNAVAILABLE`, plus generic `REQUIRED_FIELD_MISSING`.
Manufacturer and standard mismatches produce `FAIL` without a dedicated
flag (no such canonical flag exists in the matrix).

## Persistence / Redis / audit / explanation

Standard infrastructure: `Verification`, `ComplianceResult`, finding,
boolean `FlagStateRecord`, `materialize_flag_snapshot`, and
`build_flag_lineage`. Provider unavailability is retryable via the existing
queue/lease/retry seam. Findings are explainable by the existing
`ExplanationEngine` (downstream only; never mutating the boolean flag).

## Production limitations

No authoritative BIS endpoint or authentication is implemented or claimed.
The static/deterministic transport is a test seam only; a real BIS data
source, credentials, and request/response contract are still required.