# GeM Bid Compliance Verification Platform

An AI-powered platform to verify bidder documents for GeM (Government e-Marketplace) 
procurement. Automates document classification and gives procurement officers a 
compliance dashboard with risk scoring and AI recommendations — final decision 
always stays with the officer.

## Problem it solves
Procurement officers currently verify bidder documents (Udyam/MSME, GST, PAN, 
EPFO/ESIC, etc.) manually. This platform automates document ingestion, OCR, and 
classification to speed up and standardize that process.

## Tech Stack
- FastAPI
- PostgreSQL
- Celery + Redis
- Docker
- Tesseract OCR + Poppler (for scanned document text extraction)
- PyMuPDF (native PDF text extraction)

## Current Status
**Module 1 — Document Ingestion & Classification: Complete**
- Zip upload → safe extraction → bidder grouping → text extraction (native + OCR fallback) → keyword-based classification
- Stores results in PostgreSQL

**Planned Modules**
- Module 2: AI entity extraction (NLP/NER)
- Module 3: Multi-portal API gateway (GST, MCA21, DigiLocker) with RPA fallback
- Module 4: Cross-verification and risk scoring

## Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
docker compose up -d
uvicorn app.main:app --reload
celery -A app.tasks worker --loglevel=info --pool=solo
```

## Integrated Modules 1/2 + 4

`SIH-PROJECT-main` (Modules 1/2) is integrated with the sibling
[`Core-Engine-GeM`](..) project (Module 4, the parent directory of this
repo). Core-Engine-GeM
is installed as a local editable package — its source is NOT copied:

```bash
pip install -r requirements.txt
pip install -e ..    # installs Core-Engine-GeM (the parent package)
```

### Current data flow (no Module 3)

```
ZIP upload
  -> Module 1: safe extraction, bidder grouping, native text extraction/OCR,
     document classification
  -> Module 2: entity extraction (bidder-level ConsolidatedBidderExtraction;
     unchanged for existing API consumers)
  -> app.integration.module12_adapter: PER-DOCUMENT extraction -> explicit
     field mapping -> Core normalize_upstream -> document-level Evidence
  -> app.integration.module4_service: Core VerificationEngine(
       identity_reconciliation_engine=IdentityReconciliationEngine(),
       cross_document_consistency_engine=CrossDocumentConsistencyEngine())
  -> cross-document findings -> canonical flags -> grounded explanations
     (deterministic fallback; an LLM may explain but never create/change flags)
  -> persistence (document_evidence, bidder_verification_results)
```

The identity reconciliation step receives **zero** authoritative
Verification records today. That is the deliberate, correct "no
authoritative verification yet" state. The future Module 3 hook is a
Protocol only (`app/integration/future_module3.py`); it is not called,
implemented, or mocked anywhere.

### Field mapping (Module 2 -> Core Evidence)

Document types (`Document.classified_type` -> `Evidence.document_type`):

| Module 1 label | Core document_type |
|---|---|
| gst_certificate | GST |
| pan_card | PAN |
| udyam_certificate | UDYAM |
| itr_acknowledgment | ITR |
| financial_statement | BS |
| make_in_india_local_content | MAKE_IN_INDIA |
| oem_authorization | OEM_AUTHORIZATION |
| others | kept verbatim (never compared by Core) |

Field renames (only renames; everything else passes through unchanged):
`pan -> pan_number`, `udyam -> udyam_registration_number`,
`udin -> ca_udin`, `taxpayer_name -> name_on_pan`,
`declared_local_content_pct -> local_content_percentage`.

`confidence` / `page` / `bbox` are left `None` unless Module 1/2 actually
produced them. Evidence ids are deterministic: `<document_id>:<field_name>`
(Core's canonical scheme), so every finding traces back to a source
document and field. Fields Core requires but Module 2 does not provide
(e.g. `registered_address`) remain absent — never fabricated.

### Pipeline wiring

`app/tasks.py::process_evaluation` now chains:
safe extraction -> bidder grouping -> text extraction/OCR
-> `process_entity_extraction_job` (Module 2, status COMPLETED)
-> `run_module4_for_evaluation` (Module 4, status VERIFIED /
MODULE4_FAILED).

Per-bidder failures are persisted as `MODULE4_FAILED` on the bidder result
row (never converted into a fake clean result). A new read endpoint
`GET /api/v1/evaluations/{evaluation_id}/verification` exposes per-bidder
documents, evidence with provenance, findings, canonical flags and
grounded explanations.

### Configuration

- `DATABASE_URL` — overrides the default
  `postgresql(+psycopg)://gem_user:gem_pass@localhost:5432/gem_verification`
- `TESSERACT_CMD`, `POPPLER_PATH` — OCR tool locations (platform-neutral;
  defaults resolve from PATH). The previous hard-coded Windows paths were
  removed.

### Tests

```bash
pytest   # legacy Module 2 tests + 14 integration tests (A-N)
```
