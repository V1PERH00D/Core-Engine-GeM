# AI-Powered Bid Compliance & Entity Extraction Engine (Module 2)
An automated statutory entity extraction, document normalization, and visual grounding pipeline designed for public procurement bid compliance verification under General Financial Rules (GFR) 2017.

# Overview
Module 2 serves as the canonical extraction layer in the verification pipeline. It ingests raw OCR tokens and document images, applies a hybrid Deterministic Regex Fast-Path and LLM Semantic Normalizer, anchors evidence using bounding boxes, and exports a standardized Universal Document Contract payload to downstream government verification gateways (Module 3) and risk engines (Module 4).


```
  Raw OCR Payloads (Module 1)
                │
                ▼
┌────────────────────────────────────────────────────────┐
│               MODULE 2: ENTITY EXTRACTION              │
│                                                        │
│  • Path A: Statutory Fast-Path (Regex/Token Matcher)   │
│  • Path B: LLM Semantic & Financial Normalizer         │
│  • Bounding Box Coordinate Grounding                   │
│  • Anti-Hallucination & Provenance Validation          │
└───────────────────────┬────────────────────────────────┘
                        │
                        ▼
       Canonical Document Contract (JSON)
          │                            │
          ▼                            ▼
  Module 3 (Gov Gateway)      Module 4 (GFR Risk Engine)
```


# Key Features
Strict Extraction Scope: Extracts only the required evidentiary fields (GSTIN, PAN, Udyam, CA UDIN, Turnovers, MCA21 CIN/DINs, Make in India declarations, EPFO/ESIC) to eliminate document noise.

Deterministic + LLM Hybrid Pipeline: Fast-path regex execution for standard statutory tokens paired with schema-constrained LLM parsing for complex balance sheets and local content declarations.

Unit Normalization: Converts financial values across varying units (e.g., INR Lakhs, Thousands) into standard INR Crores.

Visual Grounding & Provenance: Maps extracted fields back to source pages and coordinate bounding boxes ([x1, y1, x2, y2]) for visual audit verification.

Explicit Missing State Tracking: Distinguishes missing field reasons using explicit states (NOT_PRESENT, NOT_READABLE, EXTRACTION_FAILED, NOT_APPLICABLE).

# Project Structure
```
entity_extraction/
│
├── schemas/                      # Pydantic v2 domain schemas
│   ├── __init__.py
│   ├── universal_contract.py    # Standard document-level handoff contract
│   ├── gst.py                   # GST extraction schema
│   ├── pan.py                   # PAN / ITR schema
│   ├── udyam.py                 # MSME / Udyam schema
│   ├── balance_sheet.py         # Financials, Net Worth & Turnovers
│   ├── ca_udin.py               # CA certification schema
│   ├── mca.py                   # MCA21, CIN & Director DINs
│   ├── mii.py                   # Make in India declaration schema
│   ├── epfo_esic.py             # Labor compliance schema
│   └── consolidated.py          # Unified bidder extraction model
│
├── tests/
│   ├── golden_set/              # Ground truth test fixtures
│   │   └── sample_payloads.py   # Compliant, startup, and shell company OCR inputs
│   ├── test_pipeline.py         # End-to-end extraction tests
│   └── test_regex.py            # Unit tests for statutory regex patterns
│
├── regex_patterns.py            # Regex extractors for statutory tokens & cartel signals
├── llm_extractor.py             # LLM prompt templates and structured JSON decoders
├── bbox_mapper.py               # Token-to-bounding-box visual mapping logic
├── grounding.py                 # Grounding score and reliability verification
├── tasks.py                     # Master orchestration function
├── main.py                      # FastAPI REST application endpoints
├── test_runner.py               # Test harness for offline batch evaluation
├── requirements.txt             # Python dependencies
└── .gitignore                   # Git exclusion rules

```
# Tech Stack

1. Language: Python 3.11+
2. API Framework: FastAPI / Uvicorn
3. Data Validation: Pydantic v2
4. NLP & Extraction: Regular Expressions (Re2), LangChain / LLM APIs
5. Spatial Grounding: Custom Bounding Box Coordinate Mapper
6. Testing: Pytest
