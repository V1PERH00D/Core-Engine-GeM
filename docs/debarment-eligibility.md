# Debarment / Procurement-Eligibility Verification

This document describes the procurement blacklist / debarment /
suspension / procurement-eligibility verification capability
introduced into the Compliance Engine.

## 1. Purpose

Bidders that are blacklisted, debarred, suspended, or otherwise
restricted by an authority cannot participate in public
procurement. The engine needs to:

1. Accept a bidder identifier from the upstream evidence layer.
2. Look the identifier up against the relevant authority.
4. Decide whether the bidder is currently eligible, restricted,
   restricted-but-expired, or unverifiable.
5. Surface the decision to the rule layer and the risk engine.

The capability distinguishes four outcomes explicitly:

* **verified eligible / no matching restriction**,
* **verified restricted**,
* **verified restricted with a known end date** (active vs.
  expired on the evaluation date),
* **no reliable conclusion** because the source is unavailable,
  incomplete, ambiguous, or not authoritative.

## 2. Terminology

| Term                          | Definition                                                                                                                            |
|-------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| Restriction status            | Business status reported by the source: `CLEAR`, `RESTRICTED`, or `UNKNOWN`. Distinct from the transport-layer `VerificationStatus`. |
| Restriction type              | Controlled category: `BLACKLIST`, `DEBARMENT`, `SUSPENSION`, `PROCUREMENT_RESTRICTION`, `OTHER`.                                     |
| Subject type                  | `INDIVIDUAL`, `ORGANIZATION`, `DIRECTOR`, `UNKNOWN`.                                                                                  |
| Match method                  | How the source matched the queried subject: `EXACT_IDENTIFIER`, `NORMALIZED_IDENTIFIER`, `EXACT_NAME`, `NORMALIZED_NAME`, `INSUFFICIENT_EVIDENCE`. |
| Evaluation date               | Caller-supplied date for the active-restriction window. NEVER derived from a machine clock inside the rule.                            |
| Subject name (original / normalized) | Source-supplied subject name preserved verbatim, plus the deterministic `identity-name-v1` normalized form.                |

## 3. Source-Agnostic Architecture

```
ComplianceEngine / DebarmentEligibilityRule
        |
        v
DebarmentAdapter.verify(bidder_id, identifier, **kwargs)
        |
        +--> builds a typed DebarmentQuery
        |
        v
VerificationTransport.send_query(query)   <-- network seam
        |
        v
SourceResponseEnvelope { status_code, raw_response, latency_ms, correlation_id }
        |
        v
DebarmentResponseParser.parse(envelope)   <-- parsing seam
        |
        v
NormalizedDebarmentData { restriction_status, restriction_type, ... }
        |
        v
Verification (data=NormalizedDebarmentData.model_dump(), query=...,
              raw_response=..., latency_ms=..., correlation_id=...)
```

### Files

* `src/compliance_engine/verification/debarment_models.py` -- enums,
  `DebarmentQuery`, `NormalizedDebarmentData`,
  `DebarmentEndpointConfig`, `DebarmentClientCredentials`,
  `DebarmentConfig`.
* `src/compliance_engine/verification/debarment_config.py` -- env-var
  driven config builder.
* `src/compliance_engine/verification/debarment_adapter.py` --
  `DebarmentAdapter`, `DebarmentResponseParser`,
  `DebarmentHttpTransport`, `StaticDebarmentHttpTransport`,
  `DebarmentDefaultHttpTransport`, `StaticDebarmentTransport`,
  `derive_match_method`.
* `src/compliance_engine/rules/debarment.py` --
  `DebarmentEligibilityRule`, `is_active_on`.

### Why a separate config / credential seam

The real future integration will require per-tenant client
credentials and an HTTPS endpoint. The
`DebarmentEndpointConfig` enforces HTTPS, `DebarmentConfig`
validates that no field is empty, and `from_env` builds the
config from environment variables without ever storing the
secret value in the object.


## 4. Matching Strategy Hierarchy

Identity matching is the hardest part of debarment verification.
The engine uses a deterministic, narrow matching strategy with
no fuzzy / embedding / LLM step:

| Precedence | Strategy                  | Description                                                                                                       |
|------------|---------------------------|-------------------------------------------------------------------------------------------------------------------|
| 1          | `EXACT_IDENTIFIER`         | Queried identifier equals source identifier byte-for-byte.                                                        |
| 2          | `NORMALIZED_IDENTIFIER`   | Queried identifier equals source identifier after `normalize_identifier` (strip + collapse whitespace + uppercase).|
| 3          | `EXACT_NAME`              | Subject name matches byte-for-byte.                                                                                |
| 4          | `NORMALIZED_NAME`         | Subject name matches after whitespace + uppercase normalization.                                                   |
| 5          | `INSUFFICIENT_EVIDENCE`   | No equality match established.                                                                                    |

Identifier matches always win over name matches. The rule layer
treats `EXACT_NAME`, `NORMALIZED_NAME`, and
`INSUFFICIENT_EVIDENCE` as "no legal match established" -- a
"similar name" is never a "confirmed legal entity".

The matcher is implemented in `derive_match_method` and is
unit-tested independently of the adapter.

## 5. Status Semantics

Transport-layer `VerificationStatus` and business restriction
status are kept strictly separate.

### Transport status (provider-side)

| HTTP / transport status | VerificationStatus | Notes                                                                          |
|-------------------------|--------------------|--------------------------------------------------------------------------------|
| 2xx + `restriction_status=CLEAR`     | `VERIFIED` | Positive "no match" result; rule emits `PASS`.                                |
| 2xx + `restriction_status=RESTRICTED`| `VERIFIED` | Source has a restriction; rule reads the dates and decides active / expired.  |
| 2xx + `restriction_status=UNKNOWN`    | `ERROR`    | Rule emits `UNVERIFIABLE`.                                                  |
| 2xx + malformed / missing payload      | `ERROR`    | Rule emits `UNVERIFIABLE`.                                                  |
| 4xx + no payload                       | `NOT_FOUND`| Rule emits `UNVERIFIABLE`.                                                  |
| 4xx + `identifier_status=INVALID`     | `INVALID`  | Rule emits `UNVERIFIABLE`.                                                  |
| 4xx + usable payload                   | `VERIFIED` | Rule reads the payload; for CLEAR -> PASS, RESTRICTED -> ACTIVE/EXPIRED.       |
| 5xx                                    | `UNAVAILABLE`| Rule emits `UNVERIFIABLE`.                                                |
| 3xx / unknown codes                    | `ERROR`    | Rule emits `UNVERIFIABLE`.                                                  |
| Transport exception / no transport     | `UNAVAILABLE`| Rule emits `UNVERIFIABLE`.                                                |

### Business restriction status (rule-side)

| Status        | Rule behaviour                                                                            |
|---------------|-------------------------------------------------------------------------------------------|
| `CLEAR`       | `PASS`. No flag.                                                                          |
| `RESTRICTED`  | Read dates; if active on evaluation_date -> `FAIL` + `PROCUREMENT_DEBARMENT_ACTIVE`.      |
|               | If expired -> `PASS` + `historical_restriction=True` on `actual`. No flag.                |
|               | If dates missing and match is identifier-based -> `UNVERIFIABLE` (no evaluation_date).    |
|               | If match is name-only -> `UNVERIFIABLE` ("similar name" is never a confirmed match).      |
| `UNKNOWN`     | `UNVERIFIABLE` + `PROCUREMENT_ELIGIBILITY_UNVERIFIABLE`.                                  |

## 6. Date / Evaluation-Date Semantics

The rule accepts an explicit `evaluation_date` either via
`Requirement.parameters["evaluation_date"]` or as a kwarg to
`rule.evaluate(..., evaluation_date=...)`. Precedence:

1. `evaluation_date` kwarg passed to `Rule.evaluate`.
2. `requirement.parameters["evaluation_date"]`.
3. `None` -- the rule must fall back to `UNKNOWN` when the
   source reports a restriction.

The rule never calls the machine clock. The pure function
`is_active_on(effective_date, end_date, evaluation_date)` is
deterministic and unit-tested independently.

Active-status semantics:

* `effective_date` is inclusive: a restriction whose
  effective_date equals the evaluation_date is active.
* `end_date` is exclusive: a restriction whose end_date equals
  the evaluation_date has already expired.
* `end_date=None` is treated as "open-ended / active" once
  effective_date is past.
* Missing `effective_date` cannot prove a restriction is
  active -- the rule emits `UNVERIFIABLE`.

## 7. Rule Behaviour

The rule id is `DEBARMENT_ELIGIBILITY_001`.

| Source outcome                     | Rule outcome                                        |
|------------------------------------|------------------------------------------------------|
| CLEAR + verified source            | PASS                                                 |
| RESTRICTED + active on eval_date   | FAIL + `PROCUREMENT_DEBARMENT_ACTIVE`                |
| RESTRICTED + expired on eval_date  | PASS + `actual["historical_restriction"] = True`     |
| UNKNOWN + verified transport       | UNVERIFIABLE + `PROCUREMENT_ELIGIBILITY_UNVERIFIABLE` |
| UNAVAILABLE / ERROR / NOT_FOUND    | UNVERIFIABLE + `PROCUREMENT_ELIGIBILITY_UNVERIFIABLE` |
| Malformed payload                  | UNVERIFIABLE + `PROCUREMENT_ELIGIBILITY_UNVERIFIABLE` |
| Name-only / insufficient match     | UNVERIFIABLE + `PROCUREMENT_ELIGIBILITY_UNVERIFIABLE` |
| Missing evidence (None value)      | MISSING + `REQUIRED_FIELD_MISSING`                    |
| No evidence at all                 | MISSING + `REQUIRED_FIELD_MISSING`                    |

Provider failure is never turned into a negative compliance
finding.

## 8. Active vs Expired Restrictions

Active restrictions drive `FAIL`. Expired restrictions still
flow through the rule, but the rule emits `PASS` and preserves
the historical restriction on `actual` so the audit trail can
show that one existed.

The risk engine treats the `PASS` outcome as a non-risk; the
historical restriction is informational provenance, not an
active-risk contribution.

## 9. Uncertainty Semantics

Uncertainty is explicit:

* `VerificationStatus.UNAVAILABLE` -> `UNVERIFIABLE` + flag.
* `VerificationStatus.NOT_FOUND` -> `UNVERIFIABLE` + flag.
* `VerificationStatus.ERROR` -> `UNVERIFIABLE` + flag.
* `VerificationStatus.INVALID` -> `UNVERIFIABLE` + flag.
* business `UNKNOWN` -> `UNVERIFIABLE` + flag.
* name-only / weak match -> `UNVERIFIABLE` + flag.

`UNKNOWN` is not `FAIL`. The flag is `MEDIUM` so the risk engine
classifies it as verification-availability uncertainty, not as a
HIGH-risk by itself.


## 10. Flags

| Flag ID                              | Severity | Capability                | When                                  |
|--------------------------------------|----------|---------------------------|----------------------------------------|
| `PROCUREMENT_DEBARMENT_ACTIVE`       | HIGH     | Blacklisting / Debarment  | Active verified debarment / restriction |
| `PROCUREMENT_ELIGIBILITY_UNVERIFIABLE`| MEDIUM  | Blacklisting / Debarment  | Source unavailable / ambiguous / weak match / unknown business status |

Existing flags in the same capability section continue to be
available for tender-level checks (clearance certificate,
integrity undertaking, etc.). This milestone introduces only
the two flags above so the registry / capability matrix
invariant is preserved.

## 11. Risk Integration

The existing `BidderRiskEngine` consumes the
`ComplianceResult` produced by the rule and translates the flag
into a `RiskSignal`.

* `PROCUREMENT_DEBARMENT_ACTIVE` (HIGH) drives a HIGH-severity
  `RiskSignal` in the COMPLIANCE category. With critical
  capabilities verified, a single active debarment is enough
  to push the aggregate score across the `HIGH_RISK_THRESHOLD`
  and drive the assessment to `RiskState.HIGH_RISK`.
* `PROCUREMENT_ELIGIBILITY_UNVERIFIABLE` (MEDIUM) is mapped to
  the `VERIFICATION_AVAILABILITY` category by the risk
  correlation layer. It contributes availability uncertainty,
  not active risk. The assessment remains in `RiskState.CLEAR`
  or `RiskState.INDETERMINATE`, never `RiskState.HIGH_RISK`,
  unless an independent HIGH-severity signal is present.
* Expired restrictions produce a `PASS` `ComplianceResult`
  with `historical_restriction=True` on `actual`; the risk
  engine does not turn this into an active-risk contribution.

The risk engine formula, scoring weights, and state machine are
unchanged. No new aggregation constants are introduced.

## 12. Identity Compatibility

The adapter's `DebarmentResponseParser._build_data` calls
`ai_verification.identity.normalization.normalize_legal_name`
to compute `subject_name_normalized`. The same version
(`identity-name-v1`) used by the GST / PAN / Udyam / MCA
identity pipeline is reused, so the audit trail and the
identity-reconciliation engine consume a single, consistent
normalization.

The adapter never duplicates the normalizer. It never
introduces a different abbreviation policy (e.g. it does not
silently rewrite `PVT` -> `PRIVATE`).

Both `subject_name_original` and `subject_name_normalized` are
preserved on every restricted record so the audit trail records
what was received and what the normalization produced.

## 13. Auditability

Every eligibility decision preserves:

* queried identifier,
* matching strategy,
* matched source subject (id, type, name),
* normalized subject data,
* restriction status,
* restriction type,
* effective_date / end_date,
* issuing_authority,
* reference_number,
* raw source response (`Verification.raw_response`),
* transport status code,
* `verification_id` (unique per call),
* `latency_ms`, `correlation_id`, `query` envelope,
* evaluation_date used by the rule,
* evidence / document linkage (when enriched by the rule).

No fabricated references. No secret leakage. The
`Verification` model is frozen; every enrichment is done via
`model_copy`.

## 14. Production Limitations

* **No live government endpoint is included.** The repository
  does not contain authoritative endpoint / authentication /
  response documentation for an official procurement-blacklist
  / debarment source. The default transport raises
  `NotImplementedError`; tests inject
  `StaticDebarmentTransport` /
  `StaticDebarmentHttpTransport`.
* **`CLEAR` means the queried source returned no applicable
  restriction.** It does NOT mean "legally eligible everywhere".
  Procurement eligibility depends on the tender's declared
  authority scope and the source's contract, both of which the
  engine preserves verbatim.
* **Name-only matches never establish a legal restriction.**
  The rule treats any match strategy that is not
  identifier-based as "no legal match established" and emits
  `UNVERIFIABLE`.
* **No embeddings. No LLM. No fuzzy matching.** Identity
  matching is strictly string-equality on normalized forms.
* **No fabricated live-government behaviour.** The capability
  is a structural foundation. A future official source can be
  plugged in once endpoint / authentication / response
  documentation is available; the contract is in place and
  audited.

## 15. How to Wire a Future Real Source

1. Implement a `DebarmentHttpTransport` (e.g. backed by a real
   HTTPS client) that returns `DebarmentHttpResponse` objects.
2. Construct `DebarmentConfig` with the approved
   `DebarmentEndpointConfig` (HTTPS-only) and
   `DebarmentClientCredentials`. Call
   `DebarmentConfig.validate_for_real_use()` before wiring the
   real transport.
3. Construct `DebarmentAdapter(http_transport=...)`. The
   adapter will refuse non-HTTPS URLs at the transport
   boundary.
4. The source-specific payload shape is documented in
   `NormalizedDebarmentData`. Map your real source's fields
   onto this model in your real-source adapter (or extend
   `DebarmentResponseParser` for non-standard shapes).
5. Register the adapter with `ComplianceEngine` under the
   `PROCUREMENT_ELIGIBILITY` capability key and wire
   `DebarmentEligibilityRule` into the rule map.

## 16. Backward Compatibility

This milestone introduces the following without modifying any
existing contract:

* one new canonical capability string
  (`PROCUREMENT_ELIGIBILITY`) -- not promoted to the
  `Capability` enum because the live source is not yet
  approved;
* one new source string (`DEBARMENT_REGISTRY`);
* two new flag IDs in the registry;
* the capability matrix gained two corresponding entries
  (with the count summary updated);
* the risk correlation module recognizes the
  `PROCUREMENT_ELIGIBILITY_UNVERIFIABLE` flag as
  verification-availability uncertainty.

No existing flag, threshold, score weight, or aggregation
formula is modified. No existing test is weakened.
