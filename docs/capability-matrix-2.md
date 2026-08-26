# Capability Matrix — Stream A Verification Engine

## Purpose

This matrix defines what the downstream verification engine needs to evaluate
bidder eligibility and compliance.

It is NOT the upstream extraction schema.

The upstream team provides extracted evidence and provenance.
Stream A performs normalization, authoritative verification, cross-document
checks, tender-rule evaluation, and flag generation.

---

## Evidence / Data Ownership

| Type | Meaning | Owner |
|---|---|---|
| E | Extracted from submitted bidder documents | Previous team |
| G | Retrieved from government/authoritative source | Stream A |
| T | Extracted/derived from tender requirements | Stream A |
| D | Derived/calculated by verification engine | Stream A |

### Important distinction

The same capability may contain multiple evidence types.

Example:

GSTIN:
- E: GSTIN extracted from bidder document
- G: GSTIN status/details retrieved from GST source
- D: whether the GST requirement is satisfied

The upstream team does NOT need to produce the D/G values.

---

# 1. Universal Document Evidence

These are the most important inputs from the upstream team.

| Field | Type | Required? | Purpose |
|---|---|---:|---|
| document_id | E | YES | Stable reference to source document |
| document_type | E | YES | Identify document |
| document_name | E | YES | Original/source document name |
| page_count | E | Preferred | Document metadata |
| issuer | E | If present | Identify issuing authority |
| document_number | E | If present | Registration/certificate identifier |
| issue_date | E | If present | Document date |
| expiry_date | E | If present | Validity |
| extracted_fields[] | E | YES | Evidence extracted from document |

### Every extracted field should ideally contain:

| Field | Purpose |
|---|---|
| field_name | Canonical field identifier |
| value | Extracted value |
| confidence | Extraction confidence |
| document_id | Source document |
| page | Source page |
| bounding_box | Source location |
| source_text | Optional but useful for auditability |

Missing/uncertain fields must remain distinguishable.

The extraction pipeline should distinguish:

- field not present
- field unreadable
- field extraction uncertain
- document missing
- document type unidentified

---

# 2. Bidder Identity

## Extracted evidence

| Field | Type | Required? |
|---|---|---:|
| legal_name | E | Preferred |
| trade_name | E | If present |
| entity_type | E | If present |
| registered_address | E | If present |
| state | E | If present |
| city | E | If present |

## Verification data

| Field | Type |
|---|---|
| verified_legal_name | G |
| verified_entity_type | G |
| verified_address | G |

## Engine-derived checks

- BIDDER_NAME_MISMATCH
- ENTITY_TYPE_MISMATCH
- ADDRESS_MISMATCH
- CROSS_DOCUMENT_IDENTITY_MISMATCH

---

# 3. GST

## Extracted evidence

| Field | Type | Required? |
|---|---|---:|
| gstin | E | If GST document exists |
| legal_name | E | If present |
| trade_name | E | If present |
| address | E | If present |
| registration_date | E | If present |

## Government verification

| Field | Type |
|---|---|
| registration_status | G |
| verified_legal_name | G |
| verified_trade_name | G |
| verified_address | G |
| registration_date | G |
| taxpayer_type | G |

GST return/filling information is treated as a separate verification capability
and should not be assumed to come from document extraction.

## Engine checks

- GSTIN validation
- GST identity match
- GST registration status
- applicability of GST requirement
- return-compliance requirement where applicable

Possible flags:

- GSTIN_INVALID
- GSTIN_NOT_FOUND
- GST_INACTIVE
- GST_IDENTITY_MISMATCH
- GST_ADDRESS_MISMATCH
- GST_RETURN_COMPLIANCE_ISSUE
- GST_RETURN_EVIDENCE_MISSING
- GST_VERIFICATION_UNAVAILABLE

---

# 4. PAN / Income Tax

## Extracted evidence

| Field | Type | Required? |
|---|---|---:|
| pan_number | E | If PAN evidence exists |
| name_on_pan | E | If present |
| assessment_year | E | If ITR submitted |
| financial_year | E | If present |
| relevant_financial_values | E | If present |

## Government verification

- PAN validity/status
- verified identity
- applicable ITR information

## Engine checks

- PAN validity
- bidder/PAN identity match
- required ITR availability
- required assessment year
- tender-specific tax requirements

Possible flags:

- PAN_INVALID
- PAN_NOT_FOUND
- PAN_INACTIVE
- PAN_IDENTITY_MISMATCH
- ITR_MISSING
- ITR_NOT_FILED
- ITR_OUTDATED
- ITR_DATA_INCONSISTENCY
- TAX_DATA_MISMATCH
- PAN_VERIFICATION_UNAVAILABLE

---

# 5. Udyam / MSME

## Extracted evidence

| Field | Type |
|---|---|
| udyam_registration_number | E |
| enterprise_name | E |
| enterprise_category | E |
| registration_date | E, if present |
| address | E, if present |
| major_activity | E, if present |

## Government verification

- registration status
- verified enterprise identity
- category
- relevant registration information

## Engine checks

- registration validity
- identity match
- MSME category requirement
- tender-specific exemption/benefit

Possible flags:

- UDYAM_INVALID
- UDYAM_NOT_FOUND
- UDYAM_INACTIVE
- UDYAM_CATEGORY_MISMATCH
- UDYAM_IDENTITY_MISMATCH
- UDYAM_SCOPE_MISMATCH

---

# 6. Financial Capacity

## Extracted evidence

Only extract values actually present in submitted financial documents.

| Field | Type |
|---|---|
| financial_year | E |
| turnover | E |
| net_worth | E |
| profit_after_tax | E, if present |
| total_assets | E, if present |
| total_liabilities | E, if present |
| audited | E, if determinable |
| auditor_name | E, if present |
| auditor_firm | E, if present |

## Engine-derived values

- required turnover
- turnover comparison
- required net worth
- net-worth comparison
- financial-year applicability
- derived financial ratios where actually required

## Engine checks

- turnover threshold
- net-worth threshold
- financial-year requirements
- financial evidence completeness
- cross-document financial consistency

Possible flags:

- TURNOVER_BELOW_THRESHOLD
- TURNOVER_PERIOD_MISMATCH
- TURNOVER_DATA_MISSING
- NET_WORTH_BELOW_THRESHOLD
- FINANCIAL_DATA_INCONSISTENCY
- FINANCIAL_YEAR_MISMATCH
- BALANCE_SHEET_INCOMPLETE
- AUDIT_EVIDENCE_MISSING

---

# 7. CA / UDIN

## Extracted evidence

| Field | Type |
|---|---|
| udin | E |
| certificate_type | E |
| certificate_date | E, if present |
| ca_name | E, if present |
| ca_membership_number | E, if present |
| certificate_subject | E, if present |

## Verification

- UDIN validity
- certificate authenticity where supported

## Engine checks

- required certificate present
- UDIN valid
- certificate corresponds to required claim

Possible flags:

- UDIN_MISSING
- UDIN_INVALID
- UDIN_NOT_FOUND
- UDIN_CERTIFICATE_MISMATCH
- CA_IDENTITY_MISMATCH
- CA_CERTIFICATE_SCOPE_MISMATCH

---

# 8. MCA21

## Extracted evidence

| Field | Type |
|---|---|
| cin | E |
| company_name | E, if present |
| registered_address | E, if present |
| date_of_incorporation | E, if present |
| directors[] | E, if present and actually extracted |

## Government verification

- company status
- company identity
- incorporation information
- relevant director information

Only retrieve additional MCA information when required by a tender rule.

## Engine checks

- CIN validity
- company identity match
- company status requirement
- incorporation-age requirement
- tender-specific director requirements

Possible flags:

- CIN_INVALID
- CIN_NOT_FOUND
- COMPANY_INACTIVE
- MCA_IDENTITY_MISMATCH
- DIRECTOR_DATA_MISMATCH
- DIRECTOR_REQUIREMENT_FAILED
- INCORPORATION_AGE_REQUIREMENT_FAILED
- MCA_DATA_UNAVAILABLE

---

# 9. Make in India / Local Content

## Extracted evidence

| Field | Type |
|---|---|
| local_content_percentage | E, if declared |
| supplier_class | E, if declared |
| country_of_origin | E, if present |
| manufacturer | E, if present |
| manufacturing_location | E, if present |
| local_content_declaration | E, if present |

## Tender/policy data

| Field | Type |
|---|---|
| required_local_content | T |
| required_supplier_class | T |

## Engine-derived checks

- local-content comparison
- supplier-class comparison
- declaration/evidence consistency
- applicability

Possible flags:

- LOCAL_CONTENT_BELOW_THRESHOLD
- SUPPLIER_CLASS_MISMATCH
- LOCAL_CONTENT_EVIDENCE_MISSING
- LOCAL_CONTENT_CALCULATION_INCONSISTENT
- COUNTRY_OF_ORIGIN_MISMATCH
- MANUFACTURING_LOCATION_MISMATCH
- MII_DECLARATION_MISMATCH

---

# 10. EPFO

## Extracted evidence

| Field | Type |
|---|---|
| establishment_code | E |
| establishment_name | E, if present |
| registration_date | E, if present |

## Government verification

- establishment existence
- status
- identity

## Engine checks

- registration requirement
- identity match
- applicable status

Possible flags:

- EPFO_REGISTRATION_MISSING
- EPFO_NOT_FOUND
- EPFO_STATUS_INVALID
- EPFO_IDENTITY_MISMATCH

---

# 11. ESIC

## Extracted evidence

| Field | Type |
|---|---|
| esic_code | E |
| employer_name | E, if present |
| registration_date | E, if present |

## Government verification

- employer existence
- status
- identity

Possible flags:

- ESIC_REGISTRATION_MISSING
- ESIC_NOT_FOUND
- ESIC_STATUS_INVALID
- ESIC_IDENTITY_MISMATCH

---

# 12. Startup India / DPIIT

## Extracted evidence

| Field | Type |
|---|---|
| dpiit_recognition_number | E |
| startup_name | E |
| recognition_date | E, if present |
| recognition_certificate | E, if submitted |

## Government verification

- recognition validity/status
- verified startup identity

## Engine checks

- recognition requirement
- startup-specific exemption
- identity match

Possible flags:

- DPIIT_RECOGNITION_MISSING
- DPIIT_RECOGNITION_INVALID
- DPIIT_RECOGNITION_INACTIVE
- DPIIT_IDENTITY_MISMATCH
- STARTUP_CATEGORY_REQUIREMENT_FAILED
- STARTUP_EXEMPTION_INVALID

---

# 13. NSIC

## Extracted evidence

| Field | Type |
|---|---|
| registration_number | E |
| certificate_number | E, if present |
| scheme/category | E, if present |
| valid_until | E, if present |
| product/service scope | E, if present |

## Government verification

- registration validity
- scope/category
- applicable monetary limits where relevant

Possible flags:

- NSIC_REGISTRATION_MISSING
- NSIC_REGISTRATION_INVALID
- NSIC_REGISTRATION_EXPIRED
- NSIC_IDENTITY_MISMATCH
- NSIC_SCOPE_MISMATCH
- NSIC_LIMIT_EXCEEDED

---

# 14. BIS

BIS is conditional.

The extraction pipeline should NOT be required to produce a BIS object
for every bidder.

If BIS-related evidence is submitted:

| Field | Type |
|---|---|
| licence_number | E |
| registration_number | E, if applicable |
| product_name | E |
| manufacturer | E |
| IS_number | E |
| validity | E, if present |

## Verification

- licence/registration validity
- product coverage
- manufacturer
- applicable standard

Possible flags:

- BIS_CERTIFICATION_MISSING
- BIS_LICENCE_INVALID
- BIS_LICENCE_EXPIRED
- BIS_PRODUCT_MISMATCH
- BIS_STANDARD_MISMATCH
- BIS_MANUFACTURER_MISMATCH
- BIS_SCOPE_MISMATCH

---

# 15. DigiLocker

DigiLocker is treated primarily as a document verification/access mechanism.

Required provenance:

| Field | Type |
|---|---|
| document_reference | G |
| issuer | G |
| verification_status | G |
| document_type | G |

A DigiLocker document should feed into the relevant capability rather
than being treated as a separate eligibility criterion.

Possible flags:

- DIGILOCKER_VERIFICATION_FAILED
- DIGILOCKER_DOCUMENT_MISSING
- DIGILOCKER_ISSUER_MISMATCH
- DIGILOCKER_DOCUMENT_MISMATCH
- DIGILOCKER_VERIFICATION_UNAVAILABLE

---

# 16. OEM Authorization

If the tender requires OEM authorization and a document is submitted:

| Field | Type |
|---|---|
| oem_name | E |
| authorized_bidder | E |
| authorization_number | E, if present |
| authorized_product | E |
| issue_date | E, if present |
| valid_until | E, if present |

## Engine checks

- authorization exists
- OEM identity
- authorized bidder
- authorized product
- validity

Possible flags:

- OEM_AUTHORIZATION_MISSING
- OEM_AUTHORIZATION_INVALID
- OEM_IDENTITY_MISMATCH
- AUTHORIZED_BIDDER_MISMATCH
- AUTHORIZED_PRODUCT_MISMATCH
- OEM_AUTHORIZATION_EXPIRED
- OEM_SCOPE_MISMATCH

---

# 17. Blacklisting / Debarment

If declarations or orders are submitted:

| Field | Type |
|---|---|
| declaration/status | E |
| authority | E |
| order_number | E, if present |
| order_date | E, if present |
| effective_from | E, if present |
| effective_until | E, if present |
| scope | E, if present |

## Verification

Search/check applicable authoritative exclusion sources.

## Engine checks

- active exclusion
- date applicability
- scope applicability
- historical vs active exclusion

Possible flags:

- ACTIVE_DEBARMENT
- ACTIVE_BLACKLISTING
- DEBARMENT_SCOPE_MATCH
- DEBARMENT_PERIOD_ACTIVE
- HISTORICAL_DEBARMENT
- DEBARMENT_DATA_UNAVAILABLE

---

# 18. Tender-Specific Requirements

This is a core part of the engine.

Tender requirements should be normalized into:

| Field | Type |
|---|---|
| requirement_id | T |
| description | T |
| requirement_type | T |
| mandatory | T |
| applicable | D |
| threshold | T |
| required_evidence | T |
| required_source | T |
| comparison_operator | T |
| exemption | T |

Examples:

- minimum turnover
- minimum net worth
- registration requirement
- MSME requirement
- startup exemption
- local-content requirement
- OEM authorization
- BIS certification
- experience
- geographical requirement
- non-blacklisting requirement

---

# 19. Cross-Document Verification

The engine compares evidence from different documents/sources.

Possible checks:

- bidder identity
- PAN ↔ GST
- PAN ↔ MCA
- GST ↔ Udyam
- MCA ↔ bidder identity
- financial statements ↔ ITR
- OEM authorization ↔ bidder/product
- BIS ↔ manufacturer/product
- local-content declaration ↔ supporting evidence
- certificate ↔ issuing authority

Possible flags:

- BIDDER_NAME_MISMATCH
- PAN_NAME_MISMATCH
- GST_NAME_MISMATCH
- UDYAM_NAME_MISMATCH
- MCA_NAME_MISMATCH
- ENTITY_TYPE_MISMATCH
- ADDRESS_MISMATCH
- CROSS_DOCUMENT_IDENTITY_MISMATCH
- CROSS_DOCUMENT_FINANCIAL_MISMATCH
- CROSS_DOCUMENT_PRODUCT_MISMATCH
- CROSS_DOCUMENT_CERTIFICATE_MISMATCH
- CONFLICTING_DECLARATIONS
- DUPLICATE_IDENTIFIER_DETECTED

---

# 20. Evidence Quality

These are extraction/verification quality signals, NOT compliance failures.

Possible flags:

- LOW_FIELD_CONFIDENCE
- LOW_OVERALL_GROUNDING
- UNRELIABLE_EXTRACTION
- EVIDENCE_LOCATION_MISSING
- EVIDENCE_SOURCE_UNCLEAR
- EVIDENCE_CONFLICT

Important:

LOW_CONFIDENCE does not automatically mean FAIL.

It may result in:

UNVERIFIABLE / WARNING / MANUAL_REVIEW_REQUIRED

depending on the rule.

---

# 21. Verification Infrastructure

The engine must distinguish "failed" from "could not verify."

Possible flags:

- SOURCE_UNAVAILABLE
- SOURCE_TIMEOUT
- SOURCE_AUTHENTICATION_REQUIRED
- SOURCE_RATE_LIMITED
- SOURCE_DATA_UNAVAILABLE
- VERIFICATION_STALE
- VERIFICATION_NOT_PERFORMED
- VERIFICATION_PARTIAL
- VERIFICATION_CONFLICT

---

# 22. Compliance Result

For each tender requirement:

```json
{
  "requirement_id": "...",
  "capability": "...",
  "status": "PASS | FAIL | MISSING | UNVERIFIABLE | NOT_APPLICABLE | WARNING",
  "reason": "...",
  "expected": {},
  "actual": {},
  "evidence_refs": [],
  "verification_refs": [],
  "rule_id": "...",
  "flags": []
}
