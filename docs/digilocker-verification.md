# DigiLocker / Document Verification

## Purpose

Establish provenance/authenticity of a retrieved digital document
(matrix §16). DigiLocker is **not** a generic compliance authority: the
adapter only reports whether a referenced document resolves and verifies,
and returns document metadata for the rule to compare against the tender.

## Evidence model

One `Evidence` item of `document_type` `DIGILOCKER` (or
`DIGILOCKER_DOCUMENT` / `DIGITAL_DOCUMENT`) with
`field_name == "document_access_id"`, plus an optional
`document_hash` evidence field.

No personal Aadhaar/PAN/etc. data is stored or fabricated.

## Provider boundary

`DigiLockerAdapter` implements `VerificationProvider.verify` and routes
through the generic transport seam. Normalized payload
(`NormalizedDigiLockerData`): `document_access_id`, `document_type`,
`issuer`, `issued_on`, `document_hash`, `verification_result`.

## Rule

`DigiLockerVerificationRule` (`DIGILOCKER_VERIFICATION_001`),
`required_providers = (DIGILOCKER,)`.

## Parameters (`extra="forbid"`)

- `require_verified_document` (bool | None)
- `required_issuer`
- `required_document_type`

## Statuses

| Provider status | Compliance outcome | Flag                          |
|---|---|---|
| VERIFIED        | interpreted        | (per below)                   |
| INVALID         | FAIL               | specific failure flag (below) |
| NOT_FOUND       | UNVERIFIABLE       | `DIGITAL_DOCUMENT_NOT_FOUND`  |
| UNAVAILABLE     | UNVERIFIABLE       | `DIGILOCKER_VERIFICATION_UNAVAILABLE` |
| ERROR           | UNVERIFIABLE       | `DIGILOCKER_VERIFICATION_UNAVAILABLE` |

Invalid-document flags by `verification_result`:
`SIGNATURE_INVALID` → `DIGITAL_DOCUMENT_SIGNATURE_INVALID`,
`HASH_MISMATCH` → `DIGITAL_DOCUMENT_HASH_MISMATCH`,
`REVOKED` → `DIGITAL_DOCUMENT_REVOKED`,
`EXPIRED` → `DIGITAL_DOCUMENT_EXPIRED`,
`ISSUER_NOT_RECOGNIZED` → `ISSUING_AUTHORITY_NOT_RECOGNIZED`,
otherwise `DIGITAL_SIGNATURE_VERIFICATION_FAILED`.

An unavailable DigiLocker source never becomes a negative compliance
result.

## Flags

`DIGITAL_DOCUMENT_NOT_FOUND`, `DIGITAL_DOCUMENT_SIGNATURE_INVALID`,
`DIGITAL_DOCUMENT_HASH_MISMATCH`, `DIGITAL_DOCUMENT_REVOKED`,
`DIGITAL_DOCUMENT_EXPIRED`, `ISSUING_AUTHORITY_INVALID`,
`ISSUING_AUTHORITY_NOT_RECOGNIZED`, `DIGITAL_SIGNATURE_VERIFICATION_FAILED`,
`DIGILOCKER_VERIFICATION_UNAVAILABLE`, plus `REQUIRED_FIELD_MISSING`.

## Storage / Redis / audit / explanation

Postgres stores document hash/reference metadata; large binaries remain in
the `ArtifactStore`. Provider unavailability is retryable via the queue/lease
seam. Findings are explainable downstream via `ExplanationEngine`.

## Production limitations

No live DigiLocker API or signature-validation authority is integrated or
claimed. A real verification API and its authentication details are still
required.