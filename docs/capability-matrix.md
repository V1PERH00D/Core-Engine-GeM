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

