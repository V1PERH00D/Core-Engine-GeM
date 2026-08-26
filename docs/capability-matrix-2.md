# 26100 — Stream A Capability Matrix

## Purpose

This matrix defines the exact bidder-side data required by the verification
engine.

IMPORTANT:

This is NOT a request to extract every field present in a document.

The upstream extraction team should extract ONLY the fields listed below.

Anything else found in a document should not be included unless Stream A
explicitly adds it later.

---

# Data Ownership

| Type | Meaning | Owner |
|---|---|---|
| E | Extracted from bidder-submitted documents | Upstream |
| G | Retrieved from government/authoritative source | Stream A |
| T | Extracted from tender requirements | Stream A |
| D | Derived/calculated by our engine | Stream A |

The upstream team's job ends at:

    document → required fields → value + provenance + confidence

Stream A handles:

    verification → cross-checking → tender rules → flags → explanation

---

# 1. Universal Extraction Metadata

These are required for every submitted document.

| Field | Type | Required |
|---|---|---|
| document_id | E | YES |
| document_type | E | YES |
| page_count | E | YES |
| document_number | E | Only if relevant/present |
| issuer | E | Only if relevant/present |
| issue_date | E | Only if relevant/present |
| expiry_date | E | Only if relevant/present |

## Every required extracted field must also carry:

| Field | Purpose |
|---|---|
| value | Extracted value |
| confidence | Extraction confidence |
| document_id | Source document |
| page | Source page |
| bounding_box | Source location |

Do NOT extract arbitrary document fields just because they exist.

---

# 2. Bidder Identity

Required because multiple capabilities must be cross-checked against
the bidder.

| Field | Type |
|---|---|
| legal_name | E |
| entity_type | E |
| registered_address | E |

Only extract trade name/state/city if they are specifically needed by
a verification rule.

---

# 3. GST

## Extract from bidder documents

| Field | Type |
|---|---|
| gstin | E |
| legal_name | E |
| registered_address | E |

These are the only GST fields required from the upstream team.

## Stream A obtains separately

- GST registration status
- verified legal name
- verified address
- other portal truth required by the verification rule
- return/filling compliance where applicable

## Engine evaluates

- GSTIN validity
- GST identity match
- GST status
- tender-specific GST requirements

---

# 4. PAN / Income Tax

## Extract

| Field | Type |
|---|---|
| pan_number | E |
| name_on_pan | E |

For submitted ITR evidence:

| Field | Type |
|---|---|
| assessment_year | E |
| financial_year | E |
| relevant_income/financial_value | E |

Only extract the financial values that are actually used by a configured
tender rule.

Do NOT extract the entire ITR.

## Stream A verifies

- PAN validity
- PAN identity
- required ITR availability/status
- applicable tax requirements

---

# 5. Udyam / MSME

## Extract

| Field | Type |
|---|---|
| udyam_registration_number | E |
| enterprise_name | E |
| enterprise_category | E |

These are the core fields needed for Udyam verification.

Registration date/address/activity should NOT be required from upstream
unless a specific rule uses them.

## Stream A verifies

- registration existence
- status
- enterprise identity
- MSME category
- applicability/exemption

---

# 6. Financial Documents

## Extract only

| Field | Type |
|---|---|
| financial_year | E |
| turnover | E |
| net_worth | E |

Additional financial values should only be extracted when required by an
actual tender rule.

Examples that may be enabled later:

- profit_after_tax
- total_assets
- total_liabilities

Do NOT extract an entire balance sheet into the handoff.

## Stream A derives

- threshold comparisons
- required financial period
- average turnover where required
- financial consistency checks

---

# 7. CA / UDIN

## Extract

| Field | Type |
|---|---|
| udin | E |
| certificate_type | E |
| certificate_date | E |
| ca_name | E |

Only these fields are required for the verification flow.

## Stream A verifies

- UDIN validity
- certificate relevance
- certificate/financial evidence relationship

---

# 8. MCA21

## Extract

| Field | Type |
|---|---|
| cin | E |
| company_name | E |

Only extract the following when a tender rule actually needs them:

| Field | Type |
|---|---|
| registered_address | E |
| date_of_incorporation | E |
| director_identifiers | E |

Do NOT extract the entire MCA company profile.

## Stream A verifies

- CIN/company existence
- company identity
- company status
- incorporation requirement
- tender-specific company/director conditions

---

# 9. Make in India / Local Content

## Extract

| Field | Type |
|---|---|
| local_content_percentage | E |
| supplier_class | E |
| country_of_origin | E |

Only extract manufacturer/manufacturing-location information when the
tender's local-content rule requires it.

## Stream A obtains

- required local-content percentage
- required supplier class
- applicable policy/rule

## Engine evaluates

    bidder declaration
            vs
    tender requirement

---

# 10. EPFO

## Extract

| Field | Type |
|---|---|
| establishment_code | E |
| establishment_name | E |

## Stream A verifies

- establishment existence
- status
- identity

No other EPFO fields are required from upstream unless a rule later needs them.

---

# 11. ESIC

## Extract

| Field | Type |
|---|---|
| esic_code | E |
| employer_name | E |

## Stream A verifies

- employer existence
- status
- identity

---

# 12. Startup India / DPIIT

## Extract

| Field | Type |
|---|---|
| dpiit_recognition_number | E |
| startup_name | E |

Only extract recognition date/certificate reference if required for a specific
verification rule.

## Stream A verifies

- recognition
- status
- bidder identity
- applicable startup exemption

---

# 13. NSIC

## Extract

| Field | Type |
|---|---|
| registration_number | E |
| certificate_number | E |
| valid_until | E |
| scope/category | E |

These are needed to determine whether the submitted NSIC evidence covers
the requirement.

## Stream A verifies

- registration validity
- identity
- scope
- applicability

---

# 14. BIS

BIS is conditional.

If the bidder submits BIS evidence AND the tender requires BIS:

## Extract

| Field | Type |
|---|---|
| licence_number | E |
| product_name | E |
| manufacturer | E |
| IS_number | E |

Do NOT extract a complete BIS certificate.

## Stream A verifies

- licence/registration validity
- product coverage
- manufacturer
- applicable standard

---

# 15. DigiLocker

DigiLocker is a document verification mechanism, not a bidder qualification.

The upstream team only needs to identify the relevant document.

## Required

| Field | Type |
|---|---|
| document_id | E |
| document_type | E |

The verification layer handles DigiLocker/source verification and obtains:

- issuer
- verification status
- document reference
- authenticity evidence

Do NOT create a large DigiLocker-specific bidder schema.

---

# 16. OEM Authorization

## Extract

| Field | Type |
|---|---|
| oem_name | E |
| authorized_bidder | E |
| authorized_product | E |
| authorization_number | E |
| valid_until | E |

Only these fields are required for our OEM checks.

## Stream A evaluates

- correct OEM
- correct bidder
- correct product
- authorization validity
- scope

---

# 17. Blacklisting / Debarment

## Extract from submitted declarations/orders

| Field | Type |
|---|---|
| declaration_status | E |
| authority | E |
| order_number | E |
| effective_from | E |
| effective_until | E |
| scope | E |

Only extract these when blacklisting/debarment evidence exists.

## Stream A separately verifies

- applicable exclusion sources
- active status
- dates
- scope

---

# 18. Tender-Specific Requirements

These are NOT bidder extraction fields.

Stream A extracts/normalizes from the tender:

| Field | Type |
|---|---|
| requirement_id | T |
| requirement_type | T |
| description | T |
| mandatory | T |
| threshold | T |
| comparison_operator | T |
| required_evidence | T |
| exemption | T |

These determine which bidder fields are actually relevant.

---

# 19. Multiple Values

The upstream team must preserve multiple relevant values.

Example:

```json
"turnover": [
  {
    "financial_year": "2023-24",
    "value": 18.5
  },
  {
    "financial_year": "2024-25",
    "value": 22.1
  }
]
