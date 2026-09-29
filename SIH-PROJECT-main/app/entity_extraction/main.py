import uuid
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.database import (
    SessionLocal,
    Evaluation,
    BidderFolder,
    Document,
    DocumentEvidence,
    BidderVerificationResult,
    BidderDocumentScoreRecord,
    BidderComplianceResultRecord,
    BidderVerificationRecord,
)
from app.entity_extraction.tasks import process_entity_extraction_job
from app.integration.module4_service import run_module4_for_evaluation

app = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 1. Fetch the latest extracted JSON directly
@app.get("/api/v1/latest-results", summary="Get Latest Extracted Entities JSON")
def get_latest_extracted_json(db: Session = Depends(get_db)):
    record = db.query(Evaluation).order_by(Evaluation.created_at.desc()).first()
    if not record:
        raise HTTPException(status_code=404, detail="No evaluation found. Run ingestion first.")
    
    # If not yet extracted into JSON, run extraction now
    if not record.entities_payload:
        result = process_entity_extraction_job(str(record.id))
        return result
        
    return record.entities_payload

# 2. Trigger Extraction by Evaluation ID
@app.post("/api/v1/extract-entities", summary="Run Entity Extraction on Evaluation ID")
def extract_entities_endpoint(payload: Optional[Dict[str, Any]] = None, db: Session = Depends(get_db)):
    try:
        # If payload is empty or has no ID, pick the latest evaluation record
        target_id = None
        if payload:
            target_id = payload.get("evaluation_id") or payload.get("id")
            
        if not target_id:
            latest_eval = db.query(Evaluation).order_by(Evaluation.created_at.desc()).first()
            if latest_eval:
                target_id = str(latest_eval.id)
            else:
                raise HTTPException(status_code=400, detail="No evaluations exist to process.")

        result = process_entity_extraction_job(target_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction error: {str(e)}")

# 3. Module 4 verification results (findings / canonical flags / grounded
#    explanations with document-level evidence provenance, plus the
#    DocumentScoringEngine per-document scores and bidder category).
@app.get(
    "/api/v1/evaluations/{evaluation_id}/verification",
    summary="Get Module 4 verification + document scoring results for an evaluation",
)
def get_verification_results(evaluation_id: str, db: Session = Depends(get_db)):
    try:
        eval_uuid = uuid.UUID(str(evaluation_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid evaluation_id")
    record = db.query(Evaluation).filter(Evaluation.id == eval_uuid).first()
    if not record:
        raise HTTPException(status_code=404, detail="Evaluation not found.")

    results = (
        db.query(BidderVerificationResult)
        .filter(BidderVerificationResult.evaluation_id == record.id)
        .all()
    )
    # Entity extraction may have been run via the API after upload; run
    # Module 4 lazily in that case so results are always available.
    if not results and record.entities_payload:
        run_module4_for_evaluation(str(record.id), db=db)
        results = (
            db.query(BidderVerificationResult)
            .filter(BidderVerificationResult.evaluation_id == record.id)
            .all()
        )

    bidders = []
    for result in results:
        folder = (
            db.query(BidderFolder)
            .filter(BidderFolder.id == result.bidder_folder_id)
            .first()
        )
        documents = (
            db.query(Document)
            .filter(Document.bidder_folder_id == result.bidder_folder_id)
            .all()
        )
        evidence_rows = (
            db.query(DocumentEvidence)
            .filter(DocumentEvidence.bidder_folder_id == result.bidder_folder_id)
            .all()
        )
        score_row = (
            db.query(BidderDocumentScoreRecord)
            .filter(BidderDocumentScoreRecord.bidder_folder_id == result.bidder_folder_id)
            .first()
        )
        compliance_rows = (
            db.query(BidderComplianceResultRecord)
            .filter(BidderComplianceResultRecord.bidder_folder_id == result.bidder_folder_id)
            .order_by(BidderComplianceResultRecord.created_at)
            .all()
        )
        verification_rows = (
            db.query(BidderVerificationRecord)
            .filter(BidderVerificationRecord.bidder_folder_id == result.bidder_folder_id)
            .order_by(BidderVerificationRecord.created_at)
            .all()
        )
        bidders.append({
            "bidder_id": str(result.bidder_folder_id),
            "bidder_name": folder.raw_folder_name if folder else None,
            "status": result.status,
            "error": result.error,
            "documents": [
                {
                    "document_id": str(d.id),
                    "document_type": d.classified_type,
                    "display_name": d.display_name,
                    "source_filename": d.original_relative_path,
                }
                for d in documents
            ],
            "evidence": [
                {
                    "evidence_id": e.evidence_id,
                    "document_id": e.document_id,
                    "document_type": e.document_type,
                    "field_name": e.field_name,
                    "value": (e.value or {}).get("value"),
                    "confidence": e.confidence,
                    "page": e.page,
                    "bbox": e.bbox,
                }
                for e in evidence_rows
            ],
            # REAL Module 3 output: one row per evaluated requirement,
            # faithfully persisted (UNVERIFIABLE stays UNVERIFIABLE).
            "compliance_results": [
                {
                    "requirement_id": r.requirement_id,
                    "capability": r.capability,
                    "status": r.status,
                    "reason": r.reason,
                    "rule_id": r.rule_id,
                    "expected": r.expected,
                    "actual": r.actual,
                    "evidence_refs": r.evidence_refs,
                    "verification_refs": r.verification_refs,
                    "flags": r.flags,
                }
                for r in compliance_rows
            ],
            # REAL Module 3 authoritative provider records (audit trail).
            "verification_records": [
                {
                    "verification_id": v.verification_id,
                    "capability": v.capability,
                    "source": v.source,
                    "queried_identifier": v.queried_identifier,
                    "status": v.status,
                    "data": v.data,
                    "evidence_id": v.evidence_id,
                    "document_id": v.document_id,
                    "transport_status_code": v.transport_status_code,
                    "retrieved_at": (
                        v.retrieved_at.isoformat() if v.retrieved_at else None
                    ),
                }
                for v in verification_rows
            ],
            "findings": result.findings,
            "flags": result.flags,
            "explanations": result.explanations,
            # DocumentScoringEngine output (None when the bidder had no
            # documents or Module 4 failed — never a fabricated score).
            "scoring": (
                {
                    "bidder_id": score_row.bidder_id,
                    "submission_id": score_row.submission_id,
                    "overall_score": score_row.overall_score,
                    "category": score_row.category,
                    "reason_codes": score_row.reason_codes,
                    "documents": score_row.document_scores,
                    "summary": score_row.summary,
                    "generated_at": (
                        score_row.generated_at.isoformat()
                        if score_row.generated_at else None
                    ),
                }
                if score_row else None
            ),
        })

    return {
        "evaluation_id": str(record.id),
        "status": record.status,
        "bidders": bidders,
    }
