from app.celery_app import celery_app
from app.services.zip_handler import safe_extract_zip
from app.services.bidder_grouping import group_top_level_folders, extract_all_documents
from app.database import SessionLocal, Evaluation
from pathlib import Path

# Module 1/2 -> Module 4 integration: entity extraction produces the
# bidder-level consolidated output (existing behaviour); the integration
# service then turns each document's extracted fields into document-level
# Core Evidence and runs Module 4 (cross-document consistency, canonical
# flags, grounded explanations) before results are persisted.
from app.entity_extraction.tasks import process_entity_extraction_job
from app.integration.module4_service import run_module4_for_evaluation

@celery_app.task
def add(x, y):
    return x + y

@celery_app.task
def process_evaluation(evaluation_id: str, zip_path: str):
    db = SessionLocal()

    try:
        extracted_path = safe_extract_zip(Path(zip_path), evaluation_id)

        db.query(Evaluation).filter_by(id=evaluation_id).update({"status": "extracted"})
        db.commit()

        folder_count = group_top_level_folders(extracted_path, evaluation_id)

        db.query(Evaluation).filter_by(id=evaluation_id).update({"status": "grouped"})
        db.commit()

        doc_count = extract_all_documents(evaluation_id, db)

        db.query(Evaluation).filter_by(id=evaluation_id).update({"status": "text_extracted"})
        db.commit()

        # Module 2: document classification results + entity extraction
        # (bidder-level ConsolidatedBidderExtraction, stored on the
        # evaluation's entities_payload; sets status COMPLETED).
        extraction_result = process_entity_extraction_job(evaluation_id)

        # Module 4: document-level Evidence -> VerificationEngine ->
        # cross-document findings / canonical flags / grounded
        # explanations (persisted on bidder_verification_results;
        # sets status VERIFIED / MODULE4_FAILED).
        module4_result = run_module4_for_evaluation(evaluation_id, db=db)

        return {
            "extracted_path": str(extracted_path),
            "bidder_folders_found": folder_count,
            "documents_processed": doc_count,
            "extraction_status": extraction_result.get("status"),
            "module4_status": module4_result.get("status"),
        }

    except Exception as e:
        db.query(Evaluation).filter_by(id=evaluation_id).update({"status": f"failed: {str(e)}"})
        db.commit()
        raise

    finally:
        db.close()