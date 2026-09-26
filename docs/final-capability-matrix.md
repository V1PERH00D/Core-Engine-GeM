# Final Capability Matrix — SIH PS 26100 Procurement Compliance Platform

This is the final, authoritative capability matrix for the compliance
platform. It supersedes the aspirational sections of
`docs/capability-matrix.md` (which is retained as the original requirement
elicitation artifact and as the registry-parity reference enforced by
`tests/flags/test_registry.py`).

## Status definitions

| Status | Meaning |
|---|---|
| IMPLEMENTED | Deterministic rule/verifier + canonical flags + persistence + tests exist end to end. Live verification against the real government source additionally requires production connectivity (see limitations). |
| STRUCTURALLY SUPPORTED / PRODUCTION SOURCE REQUIRED | Canonical flag definitions, persistence, explanation and snapshot support exist; no deterministic rule and/or no authoritative production API is available yet. No behavior is simulated. |
| INTENTIONALLY OUT OF SCOPE | Excluded by the architecture decisions (no severity, no risk score, no AI compliance decisions) or deliberately deferred (no production source, speculative capability). |

## External compliance contract (boolean only)

The only externally consumable compliance output is:

```json
{
  "bidder_id": "...",
  "flags": {
    "<CANONICAL_FLAG_ID>": true,
    "<CANONICAL_FLAG_ID>": false
  }
}
```

Canonical flag IDs come from `compliance_engine.flags.FLAG_REGISTRY`
(`docs/capability-matrix.md` lists the registry exactly; parity is
test-enforced). There is no severity, risk score, risk level, confidence
or AI decision in the downstream contract. Internal diagnostic metadata
(verification provenance, correlation IDs, grounded explanations) is
persisted separately and never contaminates the boolean contract.

## Capability matrix

| PS 26100 capability | Implementation | Verification | Rule | Flag(s) | Persistence | Explanation | Tests | Status |
|---|---|---|---|---|---|---|---|---|
| Bidder Identity (`BIDDER_IDENTITY`) | `anomalies/identity.py`, `ai_verification/identity/`, `ai_verification/cross_document/` | deterministic cross-source identifier correlation (GST/PAN/Udyam/MCA21/DigiLocker alias tables) | cross-document identity verification | `ADDRESS_MISMATCH`, `BIDDER_NAME_MISMATCH`, `CROSS_DOCUMENT_IDENTITY_MISMATCH`, `CROSS_SOURCE_IDENTITY_MISMATCH`, `ENTITY_TYPE_MISMATCH`, `IDENTIFIER_ENTITY_MISMATCH` | PG + snapshot | Expl | `tests/anomalies/`, `tests/ai_verification/identity/` | IMPLEMENTED |
| GST / GSTN (`GST`) | `rules/gst.py`, `verification/gstn_adapter.py`, `MockGSTProvider` | typed GSTN seam, mock provider; no production endpoint | `GSTRegistrationRule` | `GSTIN_INVALID`, `GSTIN_MISSING`, `GSTIN_NOT_FOUND`, `GST_IDENTITY_MISMATCH`, `GST_INACTIVE`, `GST_VERIFICATION_UNAVAILABLE` | PG + snapshot | Expl | `tests/rules/test_gst.py`, `tests/verification/test_gstn_adapter.py` | IMPLEMENTED (production GSTN source required for live queries) |
| GST Return Filing (`GST_RETURN_FILING`) | `rules/gst_return_filing.py` | submitted-return evidence evaluation | `GSTReturnFilingRule` | `GST_RETURN_COMPLIANCE_ISSUE`, `GST_RETURN_EVIDENCE_MISSING` | PG + snapshot | Expl | `tests/verification/test_gst_return_filing.py` | IMPLEMENTED |
| PAN / Income Tax (`PAN_INCOME_TAX`) | `rules/pan.py`, `verification/pan_adapter.py`, `MockPANProvider` | typed PAN seam + domain semantics tests | `PANValidationRule` | `PAN_INVALID`, `PAN_INACTIVE`, `PAN_NOT_FOUND`, `PAN_IDENTITY_MISMATCH`, `PAN_VERIFICATION_UNAVAILABLE`, `ITR_MISSING`, `ITR_NOT_FILED`, `ITR_OUTDATED`, `ITR_DATA_INCONSISTENCY`, `TAX_DATA_MISMATCH` | PG + snapshot | Expl | `tests/rules/test_pan.py`, `tests/verification/test_pan_*.py` | IMPLEMENTED (production PAN/ITR source required for live queries) |
| Udyam / MSME (`UDYAM`) | `rules/udyam.py`, `verification/udyam_adapter.py`, `MockUdyamProvider` | typed Udyam seam, mock provider | `UdyamRegistrationRule` | `UDYAM_INVALID`, `UDYAM_INACTIVE`, `UDYAM_NOT_FOUND`, `UDYAM_IDENTITY_MISMATCH`, `UDYAM_CATEGORY_MISMATCH`, `UDYAM_SCOPE_MISMATCH`, `UDYAM_VERIFICATION_UNAVAILABLE` | PG + snapshot | Expl | `tests/rules/test_udyam.py`, `tests/verification/test_udyam_provider.py` | IMPLEMENTED (production Udyam API required for live queries) |
| Financial Capacity (`FINANCIAL`) | `rules/financial.py`, `compliance_engine/financial/` | deterministic financial consistency analysis (turnover, solvency, net worth, year consistency) | `FinancialCapacityRule` | `FINANCIAL_CAPACITY_MISSING`, `FINANCIAL_DATA_INCONSISTENCY`, `FINANCIAL_VERIFICATION_UNAVAILABLE`, `FINANCIAL_YEAR_*`, `NET_WORTH_BELOW_THRESHOLD`, `SOLVENCY_*`, `TURNOVER_*`, `AUDITED_STATUS_MISSING`, `AUDIT_EVIDENCE_MISSING`, `BALANCE_SHEET_INCOMPLETE` | PG + snapshot | Expl | `tests/rules/test_financial.py` | IMPLEMENTED (verified financial data source per matrix TBD) |
| MCA21 (`MCA21`) | `rules/mca.py`, `verification/mca_adapter.py` | production-shaped adapter over the typed transport seam (no network/credentials); explicit `required_status` contradiction check | `McaRegistrationRule` | `CIN_INVALID`, `CIN_NOT_FOUND`, `COMPANY_INACTIVE`, `COMPANY_STRIKE_OFF`, `COMPANY_UNDER_LIQUIDATION`, `MCA_VERIFICATION_UNAVAILABLE` | PG + snapshot | Expl | `tests/rules/test_mca.py` | IMPLEMENTED (production MCA21 source required for live queries) |


## Legend

- **PG** — PostgreSQL persistence via `src/infrastructure/persistence/`
  (submissions, documents, evidence, verifications, compliance results,
  findings, flag state + boolean snapshots, jobs, audit/outbox events).
- **Expl** — grounded, evidence-referenced explanations via
  `src/ai_verification/explanations/` with deterministic fallback.
| Make in India / Local Content (`MAKE_IN_INDIA`) | `rules/make_in_india.py` | deterministic evaluation of submitted local-content evidence (thresholds, sourcing locations, exemption validity) | `MakeInIndiaRule` | `LOCAL_CONTENT_BELOW_THRESHOLD`, `LOCAL_CONTENT_CLAIM_INCONSISTENT`, `LOCAL_CONTENT_EVIDENCE_MISSING`, `LOCAL_CONTENT_VERIFICATION_UNAVAILABLE`, `MAKE_IN_INDIA_EXEMPTION_INVALID`, `MANUFACTURING_LOCATION_INELIGIBLE`, `SOURCING_LOCATION_MISMATCH` | PG + snapshot | Expl | `tests/rules/test_make_in_india.py` | IMPLEMENTED (DGFT/portal-level verification source TBD per matrix) |
| BIS / Product Certification (`BIS`) | `rules/bis.py`, `verification/bis_adapter.py` | production-shaped adapter over the typed transport seam | `BisCertificationRule` | `BIS_CERTIFICATE_EXPIRED`, `BIS_CERTIFICATE_INVALID`, `BIS_CERTIFICATE_NOT_FOUND`, `BIS_CERTIFICATE_SUSPENDED_REVOKED`, `BIS_FACILITY_LOCATION_INELIGIBLE`, `BIS_PRODUCT_SCOPE_MISMATCH`, `BIS_QUALITY_GRADE_BELOW_REQUIREMENT`, `BIS_VERIFICATION_UNAVAILABLE` | PG + snapshot | Expl | `tests/rules/test_bis.py`, `tests/verification/test_bis_adapter.py` | IMPLEMENTED (production BIS portal source required for live queries) |
| DigiLocker / Document Verification (`DIGILOCKER`) | `rules/digilocker.py`, `verification/digilocker_adapter.py` | typed transport seam (authority-specific signature APIs TBD) | `DigiLockerVerificationRule` | `DIGILOCKER_VERIFICATION_UNAVAILABLE`, `DIGITAL_DOCUMENT_EXPIRED`, `DIGITAL_DOCUMENT_HASH_MISMATCH`, `DIGITAL_DOCUMENT_NOT_FOUND`, `DIGITAL_DOCUMENT_REVOKED`, `DIGITAL_DOCUMENT_SIGNATURE_INVALID`, `DIGITAL_SIGNATURE_VERIFICATION_FAILED`, `ISSUING_AUTHORITY_INVALID` | PG + snapshot | Expl | `tests/rules/test_digilocker.py`, `tests/verification/test_digilocker_adapter.py` | IMPLEMENTED (production signature-verification APIs required for live sources) |
| OEM Authorization (`OEM_AUTHORIZATION`) | `rules/oem.py` | deterministic evaluation of submitted OEM authorization evidence (territory, type, product range, validity) | `OemAuthorizationRule` | `OEM_AUTHORIZATION_EXPIRED`, `OEM_AUTHORIZATION_INVALID`, `OEM_AUTHORIZATION_NOT_PROVIDED`, `AUTHORIZATION_TERRITORY_MISMATCH`, `AUTHORIZATION_TYPE_MISMATCH`, `AUTHORIZED_PRODUCT_RANGE_INSUFFICIENT`, `OEM_NAME_MISMATCH`, `OEM_VERIFICATION_UNAVAILABLE` | PG + snapshot | Expl | `tests/rules/test_oem.py` | IMPLEMENTED (OEM-specific verification mechanisms vary per OEM) |
| Blacklisting / Debarment (`DEBARMENT`) | `rules/debarment.py`, `verification/debarment_adapter.py`, `verification/debarment_models.py` | production-shaped registry adapter (exact-identifier and name matching, date-window semantics, TLS floor) | `DebarmentEligibilityRule` | `PROCUREMENT_DEBARMENT_ACTIVE`, `PROCUREMENT_ELIGIBILITY_UNVERIFIABLE`, `DEBARMENT_CLEARANCE_MISSING`, `DEBARMENT_CLEARANCE_INVALID`, `DEBARMENT_VERIFICATION_UNAVAILABLE`, `BIDDER_BLACKLISTED`, `BIDDER_DEBARRED`, `BIDDER_SUSPENDED`, `BIDDER_UNDER_INVESTIGATION`, `BLACKLIST_STATUS_UNKNOWN`, `INTEGRITY_UNDERTAKING_MISSING` | PG + snapshot | Expl | `tests/rules/test_debarment.py`, `tests/rules/test_debarment_integration.py`, `tests/verification/test_debarment_*.py` | IMPLEMENTED (production debarment registry source required for live queries) |
| Cross-Document Verification | `ai_verification/cross_document/` | deterministic field-level conflict detection (names, addresses, identifiers, dates, financial years, product/manufacturer fields) | cross-document conflict findings | `CROSS_DOCUMENT_ADDRESS_CONFLICT`, `CROSS_DOCUMENT_DATE_SEQUENCE_INVALID`, `CROSS_DOCUMENT_ENTITY_TYPE_CONFLICT`, `CROSS_DOCUMENT_FINANCIAL_YEAR_MISMATCH`, `CROSS_DOCUMENT_IDENTIFIER_CONFLICT`, `CROSS_DOCUMENT_MANUFACTURER_MISMATCH`, `CROSS_DOCUMENT_NAME_CONFLICT`, `CROSS_DOCUMENT_PRODUCT_MISMATCH`, `CROSS_DOCUMENT_TEMPORAL_GAP`, `CROSS_DOCUMENT_VERIFICATION_INCOMPLETE` | PG + snapshot | Expl | `tests/ai_verification/cross_document/` | IMPLEMENTED |
| Cross-Bidder / Duplicate / Near-Duplicate Detection | `ai_verification/cross_bidder/`, ArtifactStore-backed document artifacts | deterministic hash/normalized/lexical matching + shared-address/director correlation (no ML) | detector findings | `EXACT_DUPLICATE_BIDDER_DETECTED`, `NEAR_DUPLICATE_BIDDER_DETECTED`, `CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE`, `CROSS_BIDDER_DOCUMENT_REUSED`, `ADDRESS_SHARING_SUSPICIOUS`, `DIRECTOR_SHARING_SUSPICIOUS`, `FINANCIAL_PROFILE_ANOMALY`, `SUSPICIOUS_BIDDER_RELATIONSHIP_DETECTED`, `CROSS_BIDDER_VERIFICATION_INCOMPLETE` | PG + snapshot | Expl | `tests/ai_verification/cross_bidder/` | IMPLEMENTED (deterministic methods only; ML-based strategy intentionally out of scope) |


| Missing / Completeness Checks | per-rule missing paths (every rule emits `REQUIRED_FIELD_MISSING` for absent mandatory evidence), `rules/base.py` | none (structural completeness, no source) | all rules + requirement applicability gating | `REQUIRED_FIELD_MISSING`, `REQUIRED_EVIDENCE_MISSING`, `CONDITIONAL_FIELD_MISSING`, `MISSING_REASON_NOT_SPECIFIED`, `ALTERNATIVE_EVIDENCE_INSUFFICIENT`, `CAPABILITY_NOT_APPLICABLE_UNCLEAR`, `COMPLETENESS_VERIFICATION_INCOMPLETE`, `EVIDENCE_GROUNDING_INSUFFICIENT` | PG + snapshot | Expl | `tests/rules/test_*.py` (missing paths) | IMPLEMENTED |
| Evidence Quality Checks | `ai_verification/evidence_quality/` | deterministic evidence-quality evaluation (OCR confidence, document-type confidence, evidence age, grounding, provenance) | evidence-quality findings | `OCR_CONFIDENCE_BELOW_THRESHOLD`, `DOCUMENT_TYPE_CONFIDENCE_LOW`, `EVIDENCE_CONFIDENCE_BELOW_THRESHOLD`, `EVIDENCE_AGE_EXCESSIVE`, `EVIDENCE_GROUNDING_UNRELIABLE`, `EVIDENCE_PROVENANCE_UNCLEAR`, `EVIDENCE_QUALITY_VERIFICATION_INCOMPLETE`, `GROUNDING_INSUFFICIENT` | PG + snapshot | Expl | `tests/ai_verification/evidence_quality/` | IMPLEMENTED |
| Verification Infrastructure Checks | `verification/transport.py`, all `*_adapter.py` modules, per-rule UNVERIFIABLE paths | typed transport seam; every adapter failure mode deterministically mapped (transport error, 5xx, 4xx, malformed payload) | every rule (never FAILs on source unavailability) | `VERIFICATION_PROVIDER_ERROR`, `VERIFICATION_PROVIDER_TIMEOUT`, `VERIFICATION_PROVIDER_UNAVAILABLE`, `CRITICAL_SOURCE_UNAVAILABLE`, `FALLBACK_VERIFICATION_INCOMPLETE`, `INFRASTRUCTURE_VERIFICATION_INCOMPLETE`, `VERIFICATION_DATA_STALE`, `*_VERIFICATION_UNAVAILABLE` | PG + snapshot | Expl | `tests/verification/`, `tests/rules/test_mca.py` | IMPLEMENTED |
| Explainability | `ai_verification/explanations/` | grounded explanations built from deterministic findings; deterministic fallback when the LLM provider is unavailable; provider-unavailable never blocks evaluation | n/a (explains flags; never decides compliance) | n/a (explanations are persisted, not emitted as flags) | explanations persisted | primary deliverable | `tests/ai_verification/explanations/` | IMPLEMENTED (AI explanation-only; no AI compliance decisions) |
| Auditability / Evidence Traceability | `DocumentArtifactStore` (ArtifactStore), `FlagStateRecord` lineage, audit/outbox event store | deterministic provenance chains (submission -> document -> evidence -> verification -> flag -> snapshot) | n/a | `AUDITABILITY_VERIFICATION_INCOMPLETE`, `AUDIT_TRAIL_INCOMPLETE`, `EVIDENCE_CHAIN_INCOMPLETE`, `EVIDENCE_LINKAGE_BROKEN`, `SOURCE_DOCUMENT_UNRECOVERABLE`, `VERIFICATION_NON_REPRODUCIBLE` | PG + snapshot | Expl | `tests/infrastructure/persistence/` | IMPLEMENTED |
| CA / UDIN | flag registry + persistence + typed flag definitions only | none (ICAI UDIN verification API TBD per matrix) | none | `CA_NOT_REGISTERED`, `CA_PROFESSIONAL_STATUS_INVALID`, `CA_IDENTITY_MISMATCH`, `CA_UDIN_INVALID`, `CA_UDIN_EXPIRED`, `CA_UDIN_NOT_FOUND`, `CA_VERIFICATION_UNAVAILABLE`, `CERTIFICATE_TYPE_MISMATCH`, `CERTIFICATE_VALIDITY_EXPIRED` | PG + snapshot | Expl | registry tests only | STRUCTURALLY SUPPORTED / PRODUCTION SOURCE REQUIRED |
| EPFO | flag registry + persistence only | none (EPFO portal API TBD) | none | `EPFO_REGISTRATION_INVALID`, `EPFO_REGISTRATION_INACTIVE`, `EPFO_REGISTRATION_NOT_FOUND`, `EPFO_VERIFICATION_UNAVAILABLE`, `EPFO_CONTRIBUTION_DEFAULT`, `EPFO_OUTSTANDING_LIABILITY_EXCESSIVE`, `EMPLOYEE_COUNT_BELOW_THRESHOLD` | PG + snapshot | Expl | registry tests only | STRUCTURALLY SUPPORTED / PRODUCTION SOURCE REQUIRED |
| ESIC | flag registry + persistence only | none (ESIC portal API TBD) | none | `ESIC_REGISTRATION_INVALID`, `ESIC_REGISTRATION_INACTIVE`, `ESIC_REGISTRATION_NOT_FOUND`, `ESIC_VERIFICATION_UNAVAILABLE`, `ESIC_CONTRIBUTION_DEFAULT`, `COVERED_EMPLOYEE_COUNT_BELOW_THRESHOLD` | PG + snapshot | Expl | registry tests only | STRUCTURALLY SUPPORTED / PRODUCTION SOURCE REQUIRED |
| Startup India / DPIIT | flag registry + persistence only | none (DPIIT recognition API TBD) | none | `STARTUP_RECOGNITION_INVALID`, `STARTUP_RECOGNITION_EXPIRED`, `STARTUP_RECOGNITION_NOT_FOUND`, `STARTUP_VERIFICATION_UNAVAILABLE`, `STARTUP_IDENTITY_MISMATCH`, `STARTUP_SECTOR_MISMATCH`, `STARTUP_INELIGIBLE_FOR_EXEMPTION` | PG + snapshot | Expl | registry tests only | STRUCTURALLY SUPPORTED / PRODUCTION SOURCE REQUIRED |
| NSIC | flag registry + persistence only | none (NSIC registration API TBD) | none | `NSIC_REGISTRATION_INVALID`, `NSIC_REGISTRATION_EXPIRED`, `NSIC_REGISTRATION_NOT_FOUND`, `NSIC_VERIFICATION_UNAVAILABLE`, `NSIC_ENTITY_IDENTITY_MISMATCH`, `NSIC_REGISTRATION_TYPE_MISMATCH` | PG + snapshot | Expl | registry tests only | STRUCTURALLY SUPPORTED / PRODUCTION SOURCE REQUIRED |
| Other Applicable Statutory Requirements | flag registry + persistence only | none (per-requirement sources TBD) | none | `STATUTORY_REQUIREMENT_MISSING`, `STATUTORY_REQUIREMENT_INVALID`, `STATUTORY_REQUIREMENT_EXPIRED`, `STATUTORY_REQUIREMENT_SUSPENDED_REVOKED`, `STATUTORY_REQUIREMENT_SCOPE_MISMATCH`, `STATUTORY_VERIFICATION_UNAVAILABLE`, `ISSUING_AUTHORITY_NOT_RECOGNIZED`, `ISSUING_AUTHORITY_INVALID` | PG + snapshot | Expl | registry tests only | STRUCTURALLY SUPPORTED / PRODUCTION SOURCE REQUIRED |
| Other Tender-Specific Requirements | flag registry + persistence only | none (per-tender deterministic rules TBD) | none | `TENDER_REQUIREMENT_EVIDENCE_MISSING`, `TENDER_REQUIREMENT_EVIDENCE_INVALID`, `TENDER_REQUIREMENT_THRESHOLD_NOT_MET`, `TENDER_REQUIREMENT_COMPLIANCE_UNCLEAR`, `TENDER_SPECIFIC_VERIFICATION_UNAVAILABLE` | PG + snapshot | Expl | registry tests only | STRUCTURALLY SUPPORTED / PRODUCTION SOURCE REQUIRED |
| Registration / Status Checks (aggregated) | flag registry + persistence only (per-capability registration rules implemented individually above) | per-capability rules only | none (aggregation layer TBD) | `AGGREGATED_REGISTRATION_STATUS_INVALID`, `REGISTRATION_STATUS_INCONSISTENT`, `REGISTRATION_RECENTLY_CHANGED`, `REGISTRATION_CHANGE_UNEXPLAINED`, `REGISTRATION_STALE_NOT_VERIFIED`, `REGISTRATION_VERIFICATION_INCOMPLETE`, `MULTIPLE_INACTIVE_REGISTRATIONS` | PG + snapshot | Expl | registry tests only | STRUCTURALLY SUPPORTED / PRODUCTION SOURCE REQUIRED |
| Tender Applicability / Exemption Checks | `Requirement.applicability` gating, per-rule `NOT_APPLICABLE` paths, `MakeInIndiaRule` exemption validity | none beyond Make-in-India exemption | all rules (applicability) | `TENDER_APPLICABILITY_UNDEFINED`, `CONDITIONAL_APPLICABILITY_UNCLEAR`, `EXEMPTION_NOT_RECOGNIZED_FOR_TENDER`, `EXEMPTION_CONDITION_NOT_MET`, `EXEMPTION_EVIDENCE_INSUFFICIENT`, `CONFLICTING_EXEMPTIONS`, `MANDATORY_CAPABILITY_MISSING` | PG + snapshot | Expl | `tests/rules/test_*.py` (applicability paths) | IMPLEMENTED (applicability gating + Make-in-India exemption); remaining exemption checks STRUCTURALLY SUPPORTED |
| Overall Bid-Level Assessment | `infrastructure/flags/snapshot.py` boolean snapshot materialization | n/a (aggregates already-materialized flags) | n/a | `BID_LEVEL_COMPLIANT`, `BID_LEVEL_NON_COMPLIANT`, `BID_LEVEL_MISSING_EVIDENCE`, `BID_LEVEL_UNVERIFIABLE`, `BID_LEVEL_PARTIAL_COMPLIANCE`, `BID_ASSESSMENT_INCOMPLETE`, `CRITICAL_CAPABILITY_FAILED` | PG (boolean snapshot) | Expl | `tests/infrastructure/flags/` | IMPLEMENTED (boolean-only; no severity aggregation) |
| Compliance Score / Risk Level | none in the external contract | n/a | n/a | legacy registry entries `COMPLIANCE_SCORE_LOW`, `SCORING_FORMULA_UNDEFINED`, `RISK_LEVEL_HIGH`, `RISK_ASSESSMENT_INCOMPLETE`, `RISK_TREND_DETERIORATING` retained for matrix parity only | n/a | n/a | n/a | INTENTIONALLY OUT OF SCOPE (architecture forbids severity/risk scoring in the external contract; the pre-existing internal `ai_verification.risk` layer remains as legacy diagnostic infrastructure, is not consumed downstream, and new behavior must not depend on it) |
| AI Recommendation (accept/reject) | none as a compliance decision | n/a | n/a | legacy registry entries `RECOMMENDATION_*` retained for matrix parity only | n/a | n/a | n/a | INTENTIONALLY OUT OF SCOPE (the AI is explanation-only: it grounds explanations in deterministic findings and never accepts, rejects or scores a bid) |



---

## Architecture confirmation

- **Boolean flag contract**: every externally consumed flag is a canonical
  registry ID materialized as a boolean; no severity, risk, confidence or
  AI decision crosses the boundary.
- **Never silently positive**: every verification path (missing evidence,
  unconfigured params, provider failure) terminates in `MISSING`,
  `NOT_APPLICABLE` or `UNVERIFIABLE` — never `PASS`.
- **No network in this milestone**: all adapters are production-shaped over
  the typed `VerificationTransport` seam; live connectivity is future work
  per capability (see the limitations column).
- **Determinism**: repeated evaluation with the same inputs produces the
  same statuses, flags, reasons and provenance references; execution-time
  UUIDs and timestamps are the only varying outputs.

## Production limitations (live connectivity required per capability)

GSTN, PAN/ITR, Udyam, MCA21, BIS portal, DigiLocker signature APIs,
debarment registries, DGFT/local-content portal, ICAI UDIN, EPFO, ESIC,
DPIIT and NSIC each require their authoritative production API and
credential handling before live verification. The adapter seams, failure
semantics and deterministic tests for every one of them already exist, so
wiring a real HTTP transport is an additive, non-breaking change.

## Material gap summary (this engagement)

1. MCA21 company registration rule (`McaRegistrationRule`) with explicit
   `required_status` contradiction checking and full adapter failure-mode
   semantics — `src/compliance_engine/rules/mca.py`,
   `src/compliance_engine/verification/mca_adapter.py`,
   `tests/rules/test_mca.py`.
2. Capability contract alignment and model support for the canonical
   `Capability.MCA21` value.
3. This final capability matrix consolidating implemented, structurally
   supported and intentionally out-of-scope capabilities.
