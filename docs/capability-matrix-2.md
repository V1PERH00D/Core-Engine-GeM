# 26100 — Capability Matrix
## Stream A — AI Bid Compliance Verification Engine

This document defines the capabilities and data required by the verification
engine for PS 26100.

The PS is intentionally broad. The system must support:
- statutory registrations
- tax/compliance verification
- financial eligibility
- tender-specific requirements
- document verification
- cross-document consistency
- blacklisting/debarment
- risk/compliance scoring
- explainable flags
- auditability

IMPORTANT:

This document is NOT a request for the upstream extraction team to extract
everything present in a document.

For each document/capability, the upstream team should extract ONLY the
fields explicitly marked as required under "Upstream Required Fields".

Government/authoritative fields are retrieved by Stream A.

Tender requirements are extracted/normalized by Stream A.

Derived compliance results are calculated by Stream A.

---

# 1. Data Ownership

| Type | Meaning | Owner |
|---|---|---|
| E | Evidence extracted from bidder documents | Upstream |
| G | Government / authoritative source data | Stream A |
| T | Tender-derived requirement | Stream A |
| D | Derived by verification/rules engine | Stream A |

The upstream handoff should therefore be:

document
→ required fields
→ value
→ confidence
→ evidence reference

Stream A then performs:

evidence
+ portal truth
+ tender rules
→ verification
→ compliance
→ flags
→ explanation
→ risk/score

---

# 2. Universal Upstream Handoff

Required for every document:

| Field | Type | Required |
|---|---|---|
| document_id | E | YES |
| bidder_id / submission_id | E | YES |
| document_type | E | YES |
| extracted_fields | E | YES |
| ocr_confidence | E | YES |

For each extracted field, preserve:

| Field | Required | Purpose |
|---|---|---|
| value | YES | Extracted value |
| confidence | YES | Extraction confidence |
| document_id | YES | Evidence reference |
| page | Preferred | Evidence location |
| bounding_box | Optional | UI/audit highlighting |

Do NOT extract arbitrary fields simply because they exist in the document.

---

# 3. Bidder Identity

## Upstream Required Fields

| Field | Purpose |
|---|---|
| legal_name | Primary bidder identity |
| entity_type | Company/LLP/proprietorship/etc. |
| registered_address | Identity/address matching |

These should be extracted from the bidder's primary identity/submission
documents where available.

## Government / authoritative data

- verified legal name
- entity type
- registered address
- relevant registration identity

## Engine checks

- bidder identity consistency
- entity-type consistency
- address consistency
- identity matching across all sources

---

# 4. GST / GSTN

The PS explicitly requires GST registration AND return-filing verification.

## Upstream Required Fields

From GST registration evidence:

| Field |
|---|
| gstin |
| legal_name |

From GST return evidence, ONLY if submitted and relevant:

| Field |
|---|
| return_period |
| filing_status |

Do not extract the entire GST certificate or entire return.

## Government / authoritative data

- GSTIN validity
- registration status
- registered legal name
- registration date
- return-filing status
- relevant return periods

Only retrieve additional GST attributes when a tender rule actually needs them.

## Engine checks

- GSTIN valid
- GST registration active
- GST identity matches bidder
- required return filing satisfied
- GST requirement applicable

---

# 5. PAN / Income Tax

The PS explicitly requires PAN and Income Tax compliance.

## Upstream Required Fields

From PAN evidence:

| Field |
|---|
| pan_number |
| name_on_pan |

From ITR/tax evidence, only fields required by the applicable tender rule:

| Field |
|---|
| assessment_year |
| financial_year |
| relevant_income_value |

Do NOT extract an entire ITR.

## Government / authoritative data

- PAN validity/status
- PAN-linked identity
- relevant Income Tax/ITR filing information
- relevant assessment year
- applicable tax compliance information

## Engine checks

- PAN validity
- PAN identity match
- required ITR present
- required assessment year covered
- tax requirement satisfied

---

# 6. Udyam / MSME

## Upstream Required Fields

| Field |
|---|
| udyam_registration_number |
| enterprise_name |
| enterprise_category |

Nothing else is required from the Udyam document unless a tender rule
specifically needs it.

## Government / authoritative data

- registration validity/status
- enterprise identity
- enterprise category
- other required registration information

## Engine checks

- Udyam registration valid
- enterprise identity matches bidder
- MSME category satisfies tender requirement
- applicable MSME exemption/benefit

---

# 7. Financial Capacity

Financial eligibility is treated as a tender-specific capability.

## Upstream Required Fields

Only extract financial values that the tender/rule configuration can consume.

Core fields:

| Field |
|---|
| financial_year |
| turnover |
| net_worth |

Conditional fields:

| Field | When needed |
|---|---|
| profit_after_tax | If tender/rule requires |
| total_assets | If tender/rule requires |
| total_liabilities | If tender/rule requires |
| current_assets | If tender/rule requires |
| current_liabilities | If tender/rule requires |
| solvency_indicator | If tender/rule requires |
| audited | If tender requires audited evidence |

Do NOT extract an entire balance sheet by default.

Multiple financial years MUST be preserved.

Example:

annual_turnovers:
- FY 2023-24 → value
- FY 2024-25 → value
- FY 2025-26 → value

## Engine derives

- required financial period
- turnover threshold comparison
- average turnover
- net-worth threshold
- solvency requirement
- financial consistency

---

# 8. CA / UDIN

Conditional: only relevant where tender evidence requires a CA-certified
document.

## Upstream Required Fields

| Field |
|---|
| udin |
| certificate_type |
| certificate_date |
| ca_name |

Only extract additional certificate information if needed to establish what
the certificate certifies.

## Government / authoritative verification

- UDIN validity
- certificate authenticity where supported

## Engine checks

- UDIN present
- UDIN valid
- certificate corresponds to required claim

---

# 9. MCA21

The PS explicitly identifies MCA21 as a relevant source.

## Upstream Required Fields

From company-registration evidence:

| Field |
|---|
| cin |
| company_name |

Conditional:

| Field | When needed |
|---|---|
| date_of_incorporation | Tender has company-age requirement |
| registered_address | Address matching required |
| director_dins | Tender has director-related requirement |

Do NOT extract an entire MCA company profile.

## Government / authoritative data

- company existence
- company name
- company status
- entity type
- incorporation date
- registered office
- directors where required

## Engine checks

- CIN valid
- company identity matches bidder
- company status satisfies requirement
- incorporation-age requirement
- director requirement where applicable

---

# 10. Make in India / Local Content

The PS explicitly requires local-content checks.

## Upstream Required Fields

From bidder declaration/certificate:

| Field |
|---|
| local_content_percentage |
| supplier_class |
| country_of_origin |

Conditional:

| Field | When needed |
|---|---|
| manufacturing_location | Local manufacturing rule requires it |
| local_content_certificate | Certification is submitted |
| calculation_basis | Engine needs to validate declared percentage |

Do NOT extract an entire Make-in-India declaration.

## Tender-derived data

- required local content
- required supplier class
- applicable policy/rule

## Engine checks

- local content ≥ requirement
- supplier class satisfies requirement
- origin consistency
- supporting evidence present
- declaration consistent with evidence

---

# 11. EPFO

## Upstream Required Fields

| Field |
|---|
| epfo_establishment_code |
| establishment_name |

## Government / authoritative data

- establishment existence
- status
- identity
- registration information where required

## Engine checks

- EPFO requirement applicable
- registration exists
- status satisfies requirement
- identity matches bidder

---

# 12. ESIC

## Upstream Required Fields

| Field |
|---|
| esic_code |
| employer_name |

## Government / authoritative data

- employer existence
- status
- identity
- registration information where required

## Engine checks

- ESIC requirement applicable
- registration exists
- status satisfies requirement
- employer identity matches bidder

---

# 13. Startup India / DPIIT

The PS explicitly mentions Startup India and BIS/DPIIT.

## Upstream Required Fields

| Field |
|---|
| dpiit_recognition_number |
| startup_name |

Conditional:

| Field | When needed |
|---|---|
| recognition_date | Tender/rule depends on recognition date |
| recognition_certificate | Supporting certificate is required |

## Government / authoritative data

- recognition validity
- recognition status
- startup identity
- relevant DPIIT information

## Engine checks

- recognition exists
- recognition valid
- startup identity matches bidder
- startup-specific eligibility/exemption satisfied

---

# 14. NSIC

The PS explicitly requires NSIC verification.

## Upstream Required Fields

| Field |
|---|
| nsic_registration_number |
| certificate_number |
| valid_until |
| scope/category |

Conditional:

| Field | When needed |
|---|---|
| monetary_limit | Tender/rule depends on NSIC limit |

## Government / authoritative data

- registration validity
- status
- scope/category
- applicable limit

## Engine checks

- NSIC registration valid
- identity matches bidder
- scope covers tender requirement
- applicable limit satisfied

---

# 15. BIS

BIS is conditional and should NOT be extracted for every bidder.

## Upstream Required Fields

If BIS evidence is actually submitted AND applicable:

| Field |
|---|
| licence_number |
| product_name |
| manufacturer_name |
| is_number / applicable_standard |

Conditional:

| Field | When needed |
|---|---|
| validity | If validity is required |
| registration_number | If registration/CRS applies |
| certificate_number | If certificate-of-conformity is used |

Do NOT extract the entire BIS certificate.

## Government / authoritative data

- licence/registration validity
- manufacturer
- covered product
- applicable standard
- certification scope

## Engine checks

- BIS requirement applicable
- certification exists
- certification valid
- correct product covered
- correct manufacturer
- correct standard covered

---

# 16. DigiLocker

DigiLocker is a verification/document-access mechanism, not a separate
eligibility criterion.

## Upstream Required Fields

The upstream team only needs to identify the relevant submitted document:

| Field |
|---|
| document_id |
| document_type |

If the document was retrieved through DigiLocker, preserve its normal
document evidence.

## Government / authoritative verification

- issuer
- document reference
- authenticity/verification status
- issued date where relevant

## Engine checks

- retrieved document corresponds to submitted evidence
- issuer valid
- verification successful

Do NOT create a large DigiLocker-specific bidder schema.

---

# 17. OEM Authorization

The PS explicitly requires OEM authorization verification.

## Upstream Required Fields

| Field |
|---|
| oem_name |
| authorized_bidder |
| authorized_product |
| authorization_number |
| authorization_date |
| valid_until |

These are the minimum fields required to determine whether the authorization
covers the bidder, product and bid period.

## Engine checks

- authorization exists
- OEM identity matches required manufacturer
- authorized bidder matches bidder
- authorized product matches tendered product
- authorization is valid for bid

---

# 18. Blacklisting / Debarment

The PS explicitly requires blacklisting/debarment identification.

## Upstream Required Fields

From bidder declaration/order evidence:

| Field |
|---|
| declaration_status |
| authority |
| order_number |
| effective_from |
| effective_until |
| scope |

Only extract these when such evidence exists.

## Government / authoritative data

- active blacklisting/debarment
- authority
- order/reference
- effective dates
- scope

## Engine checks

- active exclusion
- exclusion applies to current bid
- exclusion period active
- scope applicable
- historical vs active exclusion

---

# 19. Other Applicable Statutory / Tender-Specific Requirements

The PS explicitly says "other applicable sources" and "other applicable
statutory and tender-specific compliance requirements."

Therefore the architecture must be extensible.

## Generic evidence fields

Only for a certification/registration that the tender actually requires:

| Field |
|---|
| identifier |
| issuer |
| certificate_type |
| issue_date |
| valid_until |
| scope |

Do NOT ask upstream to extract arbitrary data from unknown documents.

The tender/rule engine determines what is actually required.

---

# 20. Tender Requirement Model

Tender requirements are NOT upstream extraction fields.

Stream A must normalize requirements into:

| Field |
|---|
| requirement_id |
| requirement_type |
| description |
| mandatory |
| applicability_condition |
| threshold |
| comparison_operator |
| required_document |
| required_source |
| exemption |
| exemption_conditions |

Examples:

- GST required
- GST returns required
- minimum turnover
- minimum net worth
- MSME requirement
- startup exemption
- local-content threshold
- OEM authorization
- BIS certification
- experience requirement
- geographic requirement
- non-blacklisting requirement
- statutory registration
- financial requirement

---

# 21. Cross-Document Verification

The engine must compare information across submitted documents and
authoritative sources.

Core comparisons:

- bidder name
- entity type
- PAN identity
- GST identity
- Udyam identity
- MCA identity
- EPFO/ESIC identity
- Startup/DPIIT identity
- OEM authorized bidder
- product identity
- manufacturer identity
- financial values
- important dates
- registration identifiers

The engine must NOT require upstream to calculate these comparisons.

---

# 22. Cross-Bidder / Duplicate Evidence Detection

The platform should also detect suspicious reuse across bidders.

Examples:

- same OEM authorization reused
- same certificate/document submitted by multiple bidders
- near-identical declaration documents
- identifiers associated with multiple bidders
- suspiciously identical supporting evidence

This requires access to the original document/OCR representation through
`document_id`.

It does NOT require the upstream team to create additional extracted fields.

---

# 23. Verification Status Model

The engine must distinguish:

```text
PASS
FAIL
MISSING
UNVERIFIABLE
NOT_APPLICABLE
WARNING
NOT_CHECKED
