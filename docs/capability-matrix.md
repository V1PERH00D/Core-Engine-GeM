# Capability Matrix

This document defines the verification capabilities required by Stream A.

## Evidence Types

- E = Extracted from bidder-submitted documents
- G = Government / authoritative verification
- D = Derived by our compliance engine
- T = Tender-derived requirement

---

## 1. Bidder Identity

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| submission_id | E | Confirmed | Identify submission |
| legal_name | E/G | Proposed | Establish bidder identity |
| trade_name | E/G | Proposed | Identity matching |
| entity_type | E/G | Proposed | Proprietorship/company/LLP/etc. |
| registered_address | E/G | Proposed | Identity/address matching |
| registered_state | E/G | Proposed | Geographic eligibility |
| registered_city | E/G | Proposed | Geographic eligibility |

---

## 2. GST

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| gstin | E | Confirmed | Extract GSTIN |
| legal_name | E/G | Proposed | Compare bidder identity |
| trade_name | E/G | Proposed | Identity verification |
| registration_date | G | Proposed | Verify registration |
| registration_status | G | Proposed | Active/cancelled/etc. |
| constitution_of_business | G | Proposed | Entity consistency |
| principal_place_of_business | G | Proposed | Address verification |
| taxpayer_type | G | Proposed | Taxpayer classification |
| return_filing_status | G | Proposed | Tender-specific compliance |
| last_return_filed | G | Proposed | Tender-specific compliance |

### Possible rules

- GSTIN must be present when GST registration is applicable.
- GSTIN must be valid/active where required.
- GST identity should match the bidder.
- GST return compliance is a separate capability from GST registration.

---

## 3. PAN / Income Tax

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| pan_number | E | Confirmed | Extract PAN |
| pan_aadhaar_linked | E | Confirmed | Extracted linkage information |
| pan_status | G | Proposed | Verify PAN status |
| name_on_pan | G | Proposed | Identity matching |
| entity_type | G | Proposed | Entity consistency |
| ITR filing status | E/G | Proposed | Tax compliance |
| assessment_year | E/G | Proposed | Determine relevant filing |
| latest_filing_date | E/G | Proposed | Filing verification |
| gross_total_income | E/G | Proposed | Financial/tender requirement |
| total_income | E/G | Proposed | Financial/tender requirement |
| tax_payable | E/G | Proposed | Tax compliance |
| tax_paid | E/G | Proposed | Tax compliance |

### Possible rules

- PAN must be present where applicable.
- PAN must be valid.
- PAN identity must match bidder identity.
- ITR requirements must be evaluated according to the tender rather than universally treating missing ITR information as failure.

---

## 4. Udyam / MSME

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| udyam_registration_number | E | Confirmed | Identify MSME registration |
| enterprise_category | E | Confirmed | Micro/Small/Medium classification |
| enterprise_name | E/G | Proposed | Identity matching |
| registration_date | G | Proposed | Registration verification |
| registration_status | G | Proposed | Active/validity verification |
| major_activity | G | Proposed | Applicability |
| registered_address | G | Proposed | Identity/address verification |

### Possible rules

- Udyam registration required when tender grants/requires MSME status.
- Registration must be valid.
- Enterprise identity must match bidder.
- Enterprise category must satisfy tender requirement where a category is specified.

---

## 5. Financial Capacity

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| annual_turnovers[] | E | Confirmed | Historical turnover |
| financial_year | E | Confirmed | Identify financial period |
| turnover_inr_cr | E | Confirmed | Turnover requirement |
| net_worth_inr_cr | E | Confirmed | Net-worth requirement |
| is_solvency_positive | E | Confirmed | Solvency indicator |
| total_assets_inr_cr | E | Proposed | Financial analysis |
| total_liabilities_inr_cr | E | Proposed | Financial analysis |
| profit_after_tax_inr_cr | E | Proposed | Financial analysis |
| current_assets_inr_cr | E | Proposed | Liquidity analysis |
| current_liabilities_inr_cr | E | Proposed | Liquidity analysis |
| working_capital_inr_cr | D | Proposed | Derived financial metric |
| audited | E | Proposed | Audit requirement |
| auditor_name | E | Proposed | Auditor evidence |
| auditor_firm | E | Proposed | Auditor evidence |

### Possible rules

- Required turnover must be compared against the tender threshold.
- Correct financial years must be considered.
- Net worth must satisfy tender threshold where applicable.
- Solvency requirement must be evaluated where applicable.
- Do not assume a universal turnover threshold.

---

## 6. CA / UDIN

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| ca_udin | E | Confirmed | Identify CA-certified document |
| certificate_type | E | Proposed | Identify certification |
| certificate_date | E | Proposed | Date verification |
| ca_name | E | Proposed | CA identity |
| ca_membership_number | E | Proposed | CA identity |
| certificate_subject | E | Proposed | Determine what is certified |

### Possible rules

- UDIN required when tender requires CA-certified evidence.
- Certificate must correspond to the required financial/compliance claim.
- Authenticity should be verified where an authoritative verification mechanism is available.

---

## 7. MCA21

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| cin | E | Confirmed | Identify company |
| company_name | G | Proposed | Identity verification |
| company_status | G | Proposed | Active status |
| company_type | G | Proposed | Entity classification |
| date_of_incorporation | G | Proposed | Eligibility/age |
| registered_office | G | Proposed | Address verification |
| roc | G | Proposed | Registry information |
| authorized_capital_inr | G | Proposed | Company information |
| paid_up_capital_inr | G | Proposed | Company information |
| active_director_dins | E/G | Confirmed field | Director verification |
| directors[] | G | Proposed | Director information |
| director.din | G | Proposed | Director identity |
| director.name | G | Proposed | Director identity |
| director.designation | G | Proposed | Director information |
| director.status | G | Proposed | Director status |

### Possible rules

- CIN required where company registration is applicable.
- Company status must satisfy tender requirement.
- Bidder identity should match MCA identity.
- Director-related requirements should only be evaluated when applicable.

---

## 8. Make in India / Local Content

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| local_content_percentage | E | Confirmed | Declared local content |
| supplier_class | E | Confirmed | Declared Class-I/Class-II/etc. |
| local_content_declaration | E | Proposed | Supporting evidence |
| calculation_basis | E | Proposed | Explain local-content calculation |
| country_of_origin | E | Proposed | Origin verification |
| manufacturing_location | E | Proposed | Local manufacturing evidence |
| local_content_certificate | E | Proposed | Certification |
| required_local_content | T | Proposed | Tender/policy threshold |
| required_supplier_class | T | Proposed | Tender/policy classification |

### Derived checks

| Result | Type |
|---|---|
| calculated/declared content satisfies threshold | D |
| declared supplier class satisfies requirement | D |
| required local-content evidence present | D |

### Important

Local-content compliance is not simply a portal lookup.

The engine must combine:

1. Tender requirement
2. Applicable Make-in-India policy
3. Bidder declaration/evidence
4. Required threshold
5. Supplier classification

---

## 9. EPFO

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| epfo_establishment_code | E | Confirmed | Identify establishment |
| epfo_status | G | Proposed | Establishment verification |
| epfo_establishment_name | G | Proposed | Identity matching |
| epfo_registration_date | G | Proposed | Registration verification |
| epfo_validity | G | Proposed | Status/validity where applicable |

### Possible rules

- EPFO registration required only when tender/eligibility conditions require it.
- Establishment identity should match bidder.
- Government-side status should be used where available.

---

## 10. ESIC

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| esic_code | E | Confirmed | Identify employer |
| esic_status | G | Proposed | Registration verification |
| esic_employer_name | G | Proposed | Identity matching |
| esic_registration_date | G | Proposed | Registration verification |

### Possible rules

- ESIC registration is tender/applicability dependent.
- Employer identity should match bidder.
- Government-side status should be preferred for verification.

---

## 11. Startup India / DPIIT

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| startup_india_number | E | Confirmed | Startup recognition identifier |
| dpiit_recognition_number | E/G | Proposed | DPIIT recognition |
| recognition_status | G | Proposed | Recognition verification |
| recognition_date | G | Proposed | Recognition information |
| startup_name | G | Proposed | Identity matching |
| recognition_certificate | E | Proposed | Supporting evidence |

### Possible rules

- Startup recognition required only when tender condition/benefit is applicable.
- Recognition must be valid/verified.
- Startup identity must match bidder.

---

## 11. Startup India / DPIIT

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| startup_india_number | E | Confirmed | Startup recognition identifier |
| dpiit_recognition_number | E/G | Proposed | DPIIT recognition |
| recognition_status | G | Proposed | Recognition verification |
| recognition_date | G | Proposed | Recognition information |
| startup_name | G | Proposed | Identity matching |
| recognition_certificate | E | Proposed | Supporting evidence |

### Possible rules

- Startup recognition required only when tender condition/benefit is applicable.
- Recognition must be valid/verified.
- Startup identity must match bidder.

---

## 12. NSIC

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| registration_number | E | Proposed | NSIC registration |
| registration_status | G | Proposed | Registration verification |
| scheme | E/G | Proposed | Identify scheme |
| certificate_number | E | Proposed | Certificate |
| issue_date | E/G | Proposed | Certificate information |
| valid_until | E/G | Proposed | Validity |
| product_categories[] | E/G | Proposed | Scope |
| monetary_limit | E/G | Proposed | Applicable purchase limit |

### Possible rules

- NSIC requirement is tender-specific.
- Registration must be valid.
- Product/category scope must cover the tender where applicable.

---

## 13. BIS

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| applicable | T | Proposed | Determine whether BIS is required |
| licence_number | E | Proposed | BIS licence |
| licence_status | G | Proposed | Verify licence |
| manufacturer_name | E/G | Proposed | Manufacturer identity |
| manufacturing_address | E/G | Proposed | Manufacturing identity |
| product_name | E/G | Proposed | Product coverage |
| is_number | E/G | Proposed | Applicable Indian Standard |
| licence_issue_date | G | Proposed | Licence information |
| licence_valid_until | G | Proposed | Licence validity |
| covered_variants[] | G | Proposed | Product coverage |
| registration_number | E/G | Proposed | CRS/registration where applicable |
| certificate_of_conformity_number | E/G | Proposed | CoC where applicable |

### Possible rules

- BIS is not universally applicable.
- Product/tender must determine whether certification is required.
- Correct product and standard must be covered.
- Licence/registration must be valid.

---

## 14. DigiLocker

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| verified | G | Confirmed field | Overall verification state |
| document_count | G | Proposed | Number of retrieved documents |
| documents[] | G | Proposed | Verified documents |
| document_type | G | Proposed | Document classification |
| issuer | G | Proposed | Issuing authority |
| document_uri | G | Proposed | Document reference |
| verification_status | G | Proposed | Authenticity |
| issued_date | G | Proposed | Document date |

### Important

DigiLocker is a verification/document-access channel, not itself a bidder qualification.

A DigiLocker-verified document should feed into the relevant capability.

---

## 15. OEM Authorization

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| authorization_required | T | Proposed | Tender requirement |
| authorization_present | E | Proposed | Evidence presence |
| oem_name | E | Proposed | OEM identity |
| oem_authorization_number | E | Proposed | Authorization |
| authorization_date | E | Proposed | Date |
| valid_until | E | Proposed | Validity |
| authorized_product | E | Proposed | Product scope |
| authorized_bidder | E | Proposed | Authorized entity |
| manufacturer_address | E | Proposed | OEM identity |

### Possible rules

- Authorization must exist if tender requires it.
- Authorization must cover the bidder.
- Authorization must cover the relevant product/scope.
- Validity must cover the bid where required.

---

## 16. Blacklisting / Debarment

| Field / Capability | Type | Upstream Status | Purpose |
|---|---|---|---|
| has_debarment | G | Proposed | Overall debarment status |
| has_blacklisting | G | Proposed | Overall blacklisting status |
| status | G | Proposed | Current status |
| records[] | G/E | Proposed | Individual records |
| authority | G/E | Proposed | Issuing authority |
| order_number | G/E | Proposed | Order identification |
| order_date | G/E | Proposed | Order date |
| effective_from | G/E | Proposed | Start |
| effective_until | G/E | Proposed | End |
| reason | G/E | Proposed | Reason |
| scope | G/E | Proposed | Scope of exclusion |
| source_reference | G/E | Proposed | Evidence source |

### Possible rules

- Active debarment/blacklisting must be checked against applicable exclusion rules.
- Scope and dates matter.
- A historical debarment should not automatically be treated as an active failure.

---

## 17. Tender-Specific Requirements

This is one of the most important capabilities.

| Field | Type | Purpose |
|---|---|---|
| requirement_id | T | Unique requirement |
| requirement_type | T | Categorize requirement |
| description | T | Human-readable requirement |
| mandatory | T | Mandatory/optional |
| applicable | D | Whether it applies to this bidder |
| threshold | T | Required value |
| required_document | T | Required evidence |
| required_source | T | Required verification source |
| comparison_operator | T | >=, <=, =, etc. |
| exception | T | Applicable exemption |
| exemption_basis | T | Why exemption applies |

### Examples

- Minimum annual turnover
- Minimum net worth
- Minimum local content
- Startup exemption
- MSME exemption
- OEM authorization
- BIS certification
- Experience requirement
- Geographic requirement
- Registration requirement
- Financial requirement
- Non-blacklisting declaration

---

## 18. Other Certifications

| Field | Type | Purpose |
|---|---|---|
| certification_type | E/G | Certification type |
| certificate_number | E/G | Certificate identifier |
| issuer | E/G | Issuing authority |
| issue_date | E/G | Issue date |
| valid_until | E/G | Validity |
| status | G | Verification status |
| scope | E/G | Certification scope |

This is intentionally extensible because tender-specific certifications cannot be known in advance.

| Field | Type | Purpose |
|---|---|---|
| document_id | E | Identify source document |
| document_type | E | Classify document |
| document_name | E | Original name |
| document_number | E | Registration/certificate number |
| issue_date | E | Document date |
| expiry_date | E | Expiry |
| issuer | E | Issuing authority |
| pages | E | Document size |

| Field | Type | Purpose |
|---|---|---|
| field_confidence | E | Confidence in extracted field |
| overall_grounding_score | E | Overall grounding |
| is_reliable | E | Overall reliability |
| page | E | Source page |
| bbox | E | Source location |

### Important

Grounding is evidence quality information.

It must NOT itself become a compliance result.

Example:

LOW grounding
    ↓
evidence may be UNVERIFIABLE
    ↓
not automatically FAIL

Each evaluated requirement should eventually produce:

- requirement_id
- capability
- status
- reason
- expected
- actual
- evidence_refs[]
- verification_refs[]
- rule_id


---

# One correction before you commit this

There's a subtle but **very important** thing in the matrix:

### `E/G` doesn't mean the upstream team must provide it.

For example:

```text
mca21.cin

Yes. **The verification engine should not just output PASS/FAIL.** It should raise **explainable flags** whenever it finds an inconsistency, missing evidence, failed requirement, verification problem, or suspicious cross-document relationship.

I would add a dedicated section to `docs/capability-matrix.md`:

# 22. Verification Engine Flags

Every flag should contain at least:

```text
flag_id
severity
capability
title
explanation
evidence_refs[]
verification_refs[]
rule_id
```

The engine should never raise a bare `"GST_MISMATCH"` with no explanation. It should produce something like:

```text
FLAG: GST_IDENTITY_MISMATCH
Severity: HIGH

Explanation:
The GSTIN extracted from the submitted GST certificate belongs to
"ABC Technologies Pvt Ltd", while the bidder name declared in the
tender is "ABC Technology Solutions Pvt Ltd".

Evidence:
- GST certificate, page 1
- Bidder declaration, page 2
- GSTN verification result
```

---

## A. Missing / Completeness Flags

| Flag ID                         | Meaning                                                | Severity |
| ------------------------------- | ------------------------------------------------------ | -------- |
| `MANDATORY_DOCUMENT_MISSING`    | Required document was not submitted                    | HIGH     |
| `MANDATORY_FIELD_MISSING`       | Required field could not be extracted                  | HIGH     |
| `REQUIRED_REGISTRATION_MISSING` | Required registration/certificate is absent            | HIGH     |
| `REQUIRED_DECLARATION_MISSING`  | Required declaration is absent                         | HIGH     |
| `REQUIRED_EVIDENCE_MISSING`     | Requirement exists but supporting evidence is missing  | HIGH     |
| `OPTIONAL_DOCUMENT_MISSING`     | Optional supporting evidence unavailable               | LOW      |
| `INCOMPLETE_DOCUMENT`           | Document exists but required information is incomplete | MEDIUM   |

---

# B. Identity / Cross-Document Flags

These are **very important** for your engine.

| Flag ID                      | Meaning                                       | Severity |
| ---------------------------- | --------------------------------------------- | -------- |
| `BIDDER_NAME_MISMATCH`       | Bidder name differs across submitted evidence | HIGH     |
| `GST_NAME_MISMATCH`          | GST identity doesn't match bidder             | HIGH     |
| `PAN_NAME_MISMATCH`          | PAN identity doesn't match bidder             | HIGH     |
| `UDYAM_NAME_MISMATCH`        | Udyam identity doesn't match bidder           | HIGH     |
| `MCA_NAME_MISMATCH`          | MCA identity doesn't match bidder             | HIGH     |
| `EPFO_NAME_MISMATCH`         | EPFO establishment identity doesn't match     | MEDIUM   |
| `ESIC_NAME_MISMATCH`         | ESIC employer identity doesn't match          | MEDIUM   |
| `STARTUP_NAME_MISMATCH`      | DPIIT/Startup identity doesn't match          | HIGH     |
| `OEM_BIDDER_MISMATCH`        | OEM authorization names a different bidder    | HIGH     |
| `ADDRESS_MISMATCH`           | Registered addresses conflict                 | MEDIUM   |
| `ENTITY_TYPE_MISMATCH`       | Entity type differs between sources           | HIGH     |
| `IDENTIFIER_ENTITY_MISMATCH` | Registration number belongs to another entity | CRITICAL |

---

# C. Registration / Status Flags

These apply across GST, Udyam, MCA, EPFO, ESIC, Startup India, NSIC, BIS, etc.

| Flag ID                           | Meaning                                               | Severity |
| --------------------------------- | ----------------------------------------------------- | -------- |
| `REGISTRATION_INVALID`            | Registration could not be validated                   | HIGH     |
| `REGISTRATION_INACTIVE`           | Government source reports inactive status             | HIGH     |
| `REGISTRATION_CANCELLED`          | Registration has been cancelled                       | HIGH     |
| `REGISTRATION_EXPIRED`            | Certificate/registration has expired                  | HIGH     |
| `REGISTRATION_NOT_FOUND`          | Identifier cannot be found in authoritative source    | HIGH     |
| `REGISTRATION_DETAILS_MISMATCH`   | Portal data conflicts with submitted evidence         | HIGH     |
| `REGISTRATION_DATE_INCONSISTENCY` | Registration dates conflict                           | MEDIUM   |
| `REGISTRATION_SCOPE_MISMATCH`     | Registration does not cover required activity/product | HIGH     |

---

# D. GST Flags

| Flag ID                        | Meaning                                      | Severity |
| ------------------------------ | -------------------------------------------- | -------- |
| `GSTIN_INVALID`                | GSTIN format/validation failure              | HIGH     |
| `GSTIN_NOT_FOUND`              | GSTIN not found through verification         | HIGH     |
| `GST_INACTIVE`                 | GST registration is inactive/cancelled       | HIGH     |
| `GST_IDENTITY_MISMATCH`        | GST identity differs from bidder             | HIGH     |
| `GST_ADDRESS_MISMATCH`         | GST address conflicts with required identity | MEDIUM   |
| `GST_RETURN_COMPLIANCE_ISSUE`  | Required return compliance not satisfied     | HIGH     |
| `GST_RETURN_EVIDENCE_MISSING`  | Required return evidence unavailable         | HIGH     |
| `GST_VERIFICATION_UNAVAILABLE` | GST source could not be queried              | MEDIUM   |

---

# E. PAN / Income Tax Flags

| Flag ID                        | Meaning                                         | Severity |
| ------------------------------ | ----------------------------------------------- | -------- |
| `PAN_INVALID`                  | PAN validation failed                           | HIGH     |
| `PAN_NOT_FOUND`                | PAN could not be verified                       | HIGH     |
| `PAN_INACTIVE`                 | PAN is inactive                                 | HIGH     |
| `PAN_IDENTITY_MISMATCH`        | PAN name differs from bidder                    | HIGH     |
| `ITR_MISSING`                  | Required ITR evidence unavailable               | HIGH     |
| `ITR_NOT_FILED`                | Required filing not found                       | HIGH     |
| `ITR_OUTDATED`                 | Evidence doesn't cover required assessment year | MEDIUM   |
| `ITR_DATA_INCONSISTENCY`       | ITR data conflicts with financial evidence      | HIGH     |
| `TAX_DATA_MISMATCH`            | Tax information conflicts across sources        | HIGH     |
| `PAN_VERIFICATION_UNAVAILABLE` | Authoritative verification unavailable          | MEDIUM   |

---

# F. Udyam / MSME Flags

| Flag ID                   | Meaning                                                | Severity |
| ------------------------- | ------------------------------------------------------ | -------- |
| `UDYAM_INVALID`           | Udyam number invalid                                   | HIGH     |
| `UDYAM_NOT_FOUND`         | Registration not found                                 | HIGH     |
| `UDYAM_INACTIVE`          | Registration is not active                             | HIGH     |
| `UDYAM_CATEGORY_MISMATCH` | Enterprise category doesn't satisfy tender requirement | HIGH     |
| `UDYAM_IDENTITY_MISMATCH` | Udyam belongs to another entity                        | HIGH     |
| `UDYAM_SCOPE_MISMATCH`    | Activity/category doesn't match requirement            | MEDIUM   |

---

# G. Financial Flags

These are going to be some of your most useful deterministic flags.

| Flag ID                        | Meaning                                                  | Severity |
| ------------------------------ | -------------------------------------------------------- | -------- |
| `TURNOVER_BELOW_THRESHOLD`     | Required turnover not achieved                           | HIGH     |
| `TURNOVER_PERIOD_MISMATCH`     | Wrong financial years supplied                           | HIGH     |
| `TURNOVER_DATA_MISSING`        | Required turnover evidence absent                        | HIGH     |
| `NET_WORTH_BELOW_THRESHOLD`    | Net worth below tender requirement                       | HIGH     |
| `SOLVENCY_REQUIREMENT_FAILED`  | Required solvency condition failed                       | HIGH     |
| `FINANCIAL_DATA_INCONSISTENCY` | Financial figures conflict across documents              | HIGH     |
| `TURNOVER_TREND_ANOMALY`       | Unusual/inconsistent turnover information                | MEDIUM   |
| `BALANCE_SHEET_INCOMPLETE`     | Required financial information missing                   | MEDIUM   |
| `AUDIT_EVIDENCE_MISSING`       | Audited financial evidence required but unavailable      | HIGH     |
| `FINANCIAL_YEAR_MISMATCH`      | Financial evidence doesn't correspond to required period | HIGH     |

**Important:** `TURNOVER_TREND_ANOMALY` should be a **warning**, not an accusation of fraud.

---

# H. CA / UDIN Flags

| Flag ID                         | Meaning                                          | Severity |
| ------------------------------- | ------------------------------------------------ | -------- |
| `UDIN_MISSING`                  | Required UDIN absent                             | HIGH     |
| `UDIN_INVALID`                  | UDIN validation failed                           | HIGH     |
| `UDIN_NOT_FOUND`                | UDIN cannot be verified                          | HIGH     |
| `UDIN_CERTIFICATE_MISMATCH`     | UDIN doesn't correspond to submitted certificate | HIGH     |
| `CA_IDENTITY_MISMATCH`          | CA details conflict                              | MEDIUM   |
| `CA_CERTIFICATE_EXPIRED`        | Required certificate is expired                  | HIGH     |
| `CA_CERTIFICATE_SCOPE_MISMATCH` | Certificate doesn't certify required claim       | HIGH     |

---

# I. MCA21 Flags

| Flag ID                                | Meaning                                   | Severity |
| -------------------------------------- | ----------------------------------------- | -------- |
| `CIN_INVALID`                          | CIN invalid                               | HIGH     |
| `CIN_NOT_FOUND`                        | Company not found                         | HIGH     |
| `COMPANY_INACTIVE`                     | Company isn't in required active state    | HIGH     |
| `MCA_IDENTITY_MISMATCH`                | MCA identity differs from bidder          | HIGH     |
| `DIRECTOR_DATA_MISMATCH`               | Director information conflicts            | HIGH     |
| `DIRECTOR_REQUIREMENT_FAILED`          | Tender-specific director condition failed | HIGH     |
| `INCORPORATION_AGE_REQUIREMENT_FAILED` | Company doesn't meet required age         | HIGH     |
| `MCA_DATA_UNAVAILABLE`                 | Required MCA verification unavailable     | MEDIUM   |

---

# J. Make in India / Local Content Flags

| Flag ID                                  | Meaning                                                | Severity |
| ---------------------------------------- | ------------------------------------------------------ | -------- |
| `LOCAL_CONTENT_BELOW_THRESHOLD`          | Local content below required percentage                | HIGH     |
| `SUPPLIER_CLASS_MISMATCH`                | Declared class doesn't satisfy requirement             | HIGH     |
| `LOCAL_CONTENT_EVIDENCE_MISSING`         | Required supporting evidence absent                    | HIGH     |
| `LOCAL_CONTENT_CALCULATION_INCONSISTENT` | Declared percentage doesn't match evidence/calculation | HIGH     |
| `COUNTRY_OF_ORIGIN_MISMATCH`             | Origin information conflicts                           | HIGH     |
| `MANUFACTURING_LOCATION_MISMATCH`        | Manufacturing evidence conflicts                       | MEDIUM   |
| `MII_DECLARATION_MISMATCH`               | Declaration conflicts with supporting evidence         | HIGH     |

---

# K. EPFO / ESIC Flags

| Flag ID                     | Meaning                                          | Severity |
| --------------------------- | ------------------------------------------------ | -------- |
| `EPFO_REGISTRATION_MISSING` | Required EPFO registration absent                | HIGH     |
| `EPFO_NOT_FOUND`            | Establishment not found                          | HIGH     |
| `EPFO_STATUS_INVALID`       | Establishment status doesn't satisfy requirement | HIGH     |
| `EPFO_IDENTITY_MISMATCH`    | Establishment belongs to different entity        | HIGH     |
| `ESIC_REGISTRATION_MISSING` | Required ESIC registration absent                | HIGH     |
| `ESIC_NOT_FOUND`            | Employer not found                               | HIGH     |
| `ESIC_STATUS_INVALID`       | ESIC status doesn't satisfy requirement          | HIGH     |
| `ESIC_IDENTITY_MISMATCH`    | Employer identity mismatch                       | HIGH     |

---

# L. Startup India / DPIIT Flags

| Flag ID                               | Meaning                                       | Severity |
| ------------------------------------- | --------------------------------------------- | -------- |
| `DPIIT_RECOGNITION_MISSING`           | Required recognition absent                   | HIGH     |
| `DPIIT_RECOGNITION_INVALID`           | Recognition cannot be verified                | HIGH     |
| `DPIIT_RECOGNITION_INACTIVE`          | Recognition doesn't satisfy requirement       | HIGH     |
| `DPIIT_IDENTITY_MISMATCH`             | Recognition belongs to another entity         | HIGH     |
| `STARTUP_CATEGORY_REQUIREMENT_FAILED` | Required startup classification not satisfied | HIGH     |
| `STARTUP_EXEMPTION_INVALID`           | Claimed startup exemption isn't supported     | HIGH     |

---

# M. NSIC Flags

| Flag ID                     | Meaning                                | Severity |
| --------------------------- | -------------------------------------- | -------- |
| `NSIC_REGISTRATION_MISSING` | Required NSIC registration absent      | HIGH     |
| `NSIC_REGISTRATION_INVALID` | Registration cannot be verified        | HIGH     |
| `NSIC_REGISTRATION_EXPIRED` | Registration expired                   | HIGH     |
| `NSIC_IDENTITY_MISMATCH`    | Registration belongs to another entity | HIGH     |
| `NSIC_SCOPE_MISMATCH`       | Product/service isn't covered          | HIGH     |
| `NSIC_LIMIT_EXCEEDED`       | Applicable monetary limit exceeded     | HIGH     |

---

# N. BIS Flags

| Flag ID                        | Meaning                                   | Severity |
| ------------------------------ | ----------------------------------------- | -------- |
| `BIS_CERTIFICATION_MISSING`    | Required BIS certification absent         | HIGH     |
| `BIS_LICENCE_INVALID`          | Licence cannot be verified                | HIGH     |
| `BIS_LICENCE_EXPIRED`          | Licence expired                           | HIGH     |
| `BIS_PRODUCT_MISMATCH`         | Licence doesn't cover tendered product    | HIGH     |
| `BIS_STANDARD_MISMATCH`        | Required IS standard not covered          | HIGH     |
| `BIS_MANUFACTURER_MISMATCH`    | Manufacturer differs from required entity | HIGH     |
| `BIS_SCOPE_MISMATCH`           | Certification scope insufficient          | HIGH     |
| `BIS_VERIFICATION_UNAVAILABLE` | BIS verification unavailable              | MEDIUM   |

---

# O. DigiLocker Flags

| Flag ID                               | Meaning                                            | Severity |
| ------------------------------------- | -------------------------------------------------- | -------- |
| `DIGILOCKER_VERIFICATION_FAILED`      | Document verification failed                       | HIGH     |
| `DIGILOCKER_DOCUMENT_MISSING`         | Expected document unavailable                      | HIGH     |
| `DIGILOCKER_ISSUER_MISMATCH`          | Document issuer isn't expected authority           | HIGH     |
| `DIGILOCKER_DOCUMENT_MISMATCH`        | Retrieved document differs from submitted evidence | HIGH     |
| `DIGILOCKER_VERIFICATION_UNAVAILABLE` | DigiLocker verification couldn't be completed      | MEDIUM   |

---

# P. OEM Authorization Flags

| Flag ID                       | Meaning                                          | Severity |
| ----------------------------- | ------------------------------------------------ | -------- |
| `OEM_AUTHORIZATION_MISSING`   | Required authorization absent                    | HIGH     |
| `OEM_AUTHORIZATION_INVALID`   | Authorization cannot be validated                | HIGH     |
| `OEM_IDENTITY_MISMATCH`       | OEM identity doesn't match required manufacturer | HIGH     |
| `AUTHORIZED_BIDDER_MISMATCH`  | Authorization is for another bidder              | CRITICAL |
| `AUTHORIZED_PRODUCT_MISMATCH` | Authorization doesn't cover tendered product     | HIGH     |
| `OEM_AUTHORIZATION_EXPIRED`   | Authorization expired                            | HIGH     |
| `OEM_SCOPE_MISMATCH`          | Authorization scope insufficient                 | HIGH     |

---

# Q. Blacklisting / Debarment Flags

These should be treated particularly seriously.

| Flag ID                      | Meaning                                        | Severity |
| ---------------------------- | ---------------------------------------------- | -------- |
| `ACTIVE_DEBARMENT`           | Bidder currently debarred                      | CRITICAL |
| `ACTIVE_BLACKLISTING`        | Bidder currently blacklisted                   | CRITICAL |
| `DEBARMENT_SCOPE_MATCH`      | Debarment applies to this procurement          | CRITICAL |
| `DEBARMENT_PERIOD_ACTIVE`    | Exclusion period covers current bid            | CRITICAL |
| `HISTORICAL_DEBARMENT`       | Previous debarment found but no longer active  | MEDIUM   |
| `DEBARMENT_DATA_UNAVAILABLE` | Required exclusion check couldn't be completed | HIGH     |

---

# R. Cross-Document Consistency Flags

**This is where your engine can become genuinely useful rather than just a collection of API checks.**

| Flag ID                                | Meaning                                                        | Severity |
| -------------------------------------- | -------------------------------------------------------------- | -------- |
| `CROSS_DOCUMENT_IDENTITY_MISMATCH`     | Same bidder identified differently                             | HIGH     |
| `CROSS_DOCUMENT_ADDRESS_MISMATCH`      | Addresses conflict                                             | MEDIUM   |
| `CROSS_DOCUMENT_DATE_MISMATCH`         | Important dates conflict                                       | MEDIUM   |
| `CROSS_DOCUMENT_REGISTRATION_MISMATCH` | Registration details conflict                                  | HIGH     |
| `CROSS_DOCUMENT_FINANCIAL_MISMATCH`    | Financial figures conflict                                     | HIGH     |
| `CROSS_DOCUMENT_PRODUCT_MISMATCH`      | Product identity differs                                       | HIGH     |
| `CROSS_DOCUMENT_MANUFACTURER_MISMATCH` | Manufacturer differs                                           | HIGH     |
| `CROSS_DOCUMENT_CERTIFICATE_MISMATCH`  | Certificate details conflict                                   | HIGH     |
| `DUPLICATE_IDENTIFIER_DETECTED`        | Same identifier appears unexpectedly across entities/documents | HIGH     |
| `CONFLICTING_DECLARATIONS`             | Two submitted declarations contradict each other               | HIGH     |

---

# S. Grounding / Evidence Quality Flags

These are **not compliance failures**. They're evidence-quality flags.

| Flag ID                     | Meaning                                          | Severity |
| --------------------------- | ------------------------------------------------ | -------- |
| `LOW_FIELD_CONFIDENCE`      | Extraction confidence below configured threshold | MEDIUM   |
| `LOW_OVERALL_GROUNDING`     | Overall evidence grounding is weak               | MEDIUM   |
| `UNRELIABLE_EXTRACTION`     | Upstream marked evidence unreliable              | HIGH     |
| `EVIDENCE_LOCATION_MISSING` | Expected bounding-box/source location missing    | LOW      |
| `EVIDENCE_SOURCE_UNCLEAR`   | Provenance cannot be established                 | MEDIUM   |
| `EVIDENCE_CONFLICT`         | Multiple evidence sources disagree               | HIGH     |

Again:

> **LOW_CONFIDENCE ≠ FAIL.**

It should generally lead to **UNVERIFIABLE**, **WARNING**, or human review depending on the rule.

---

# T. Verification Infrastructure Flags

These are important because otherwise your engine will confuse **"couldn't check"** with **"failed."**

| Flag ID                          | Meaning                                    | Severity |
| -------------------------------- | ------------------------------------------ | -------- |
| `SOURCE_UNAVAILABLE`             | Government source unavailable              | MEDIUM   |
| `SOURCE_TIMEOUT`                 | Verification request timed out             | MEDIUM   |
| `SOURCE_AUTHENTICATION_REQUIRED` | Required authorized access unavailable     | MEDIUM   |
| `SOURCE_RATE_LIMITED`            | Verification request was rate-limited      | LOW      |
| `SOURCE_DATA_UNAVAILABLE`        | Source doesn't expose required information | MEDIUM   |
| `VERIFICATION_STALE`             | Cached verification is too old             | MEDIUM   |
| `VERIFICATION_NOT_PERFORMED`     | Required check wasn't executed             | HIGH     |
| `VERIFICATION_PARTIAL`           | Only some required checks completed        | HIGH     |
| `VERIFICATION_CONFLICT`          | Different authoritative sources disagree   | HIGH     |

This distinction is **critical**:

```text
FAIL
≠
UNVERIFIABLE
≠
NOT_APPLICABLE
≠
NOT_CHECKED
```

---

# U. Tender Applicability Flags

Since the PS explicitly says **"other applicable sources"**, your engine needs to flag uncertainty here too.

| Flag ID                             | Meaning                                                      | Severity |
| ----------------------------------- | ------------------------------------------------------------ | -------- |
| `REQUIREMENT_APPLICABILITY_UNCLEAR` | Can't determine whether requirement applies                  | MEDIUM   |
| `REQUIREMENT_NOT_APPLICABLE`        | Requirement determined not to apply                          | INFO     |
| `EXEMPTION_CLAIMED`                 | Bidder claims exemption                                      | INFO     |
| `EXEMPTION_NOT_SUPPORTED`           | Claimed exemption lacks evidence                             | HIGH     |
| `EXEMPTION_CONDITION_FAILED`        | Exemption conditions aren't satisfied                        | HIGH     |
| `TENDER_THRESHOLD_MISSING`          | Rule requires threshold but threshold wasn't extracted       | HIGH     |
| `TENDER_CLAUSE_AMBIGUOUS`           | Clause cannot be deterministically interpreted               | MEDIUM   |
| `REQUIRED_SOURCE_UNDEFINED`         | Requirement needs verification source but none is configured | HIGH     |

---

# V. Overall Bid-Level Flags

Finally, the engine can aggregate individual flags into higher-level findings:

| Flag ID                         | Meaning                                             | Severity    |
| ------------------------------- | --------------------------------------------------- | ----------- |
| `CRITICAL_COMPLIANCE_FAILURE`   | One or more critical requirements failed            | CRITICAL    |
| `MANDATORY_REQUIREMENT_FAILED`  | Mandatory tender requirement failed                 | CRITICAL    |
| `MULTIPLE_HIGH_RISK_FLAGS`      | Multiple high-severity findings                     | HIGH        |
| `BID_INCOMPLETE`                | Mandatory evidence missing                          | HIGH        |
| `BID_UNVERIFIABLE`              | Required verification couldn't be completed         | HIGH        |
| `CROSS_SOURCE_INCONSISTENCY`    | Multiple authoritative sources disagree             | HIGH        |
| `MANUAL_REVIEW_REQUIRED`        | Automated determination isn't sufficiently reliable | MEDIUM/HIGH |
| `COMPLIANCE_PASS_WITH_WARNINGS` | Mandatory checks passed but warnings remain         | LOW         |
| `FULL_COMPLIANCE_PASS`          | All applicable mandatory requirements passed        | INFO        |

---

# And every flag needs an explanation

This is important for **Stream B** too.

The engine shouldn't output:

```json
{
  "flag": "TURNOVER_BELOW_THRESHOLD"
}
```

It should output something structurally closer to:

```json
{
  "flag_id": "TURNOVER_BELOW_THRESHOLD",
  "severity": "HIGH",
  "capability": "FINANCIAL_CAPACITY",
  "title": "Minimum turnover requirement not satisfied",
  "explanation": "The tender requires an average annual turnover of at least ₹25 crore for the specified financial years. The bidder's extracted turnover is ₹15.8 crore for FY 2023-24.",
  "expected": {
    "operator": ">=",
    "value": 25,
    "unit": "INR_CRORE"
  },
  "actual": {
    "value": 15.8,
    "unit": "INR_CRORE",
    "financial_year": "2023-24"
  },
  "evidence_refs": [
    "balance_sheet.annual_turnovers[0]"
  ],
  "rule_id": "FIN_TURNOVER_001"
}
```

That's the level of explainability we want.

### The architecture becomes:

```text
                 EVIDENCE
                    │
                    ▼
             VERIFICATION
                    │
                    ▼
              RULE ENGINE
                    │
         ┌──────────┴──────────┐
         ▼                     ▼
     COMPLIANCE             FLAGS
       STATUS              + EXPLANATION
         │                     │
         └──────────┬──────────┘
                    ▼
              STREAM B
```

**This flag catalogue should be part of the engine specification, not the upstream extraction schema.** The upstream team gives us evidence; **our verification engine determines which flags exist and why.**

And importantly, we should keep the flag IDs **stable and machine-readable**, because Stream B, the frontend, reports, filtering, analytics, and eventually human-review workflows can all consume the same flags.

