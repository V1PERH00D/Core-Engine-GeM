import uuid
from typing import Dict, Any, Union
from app.database import SessionLocal, Evaluation, BidderFolder, Document

from app.entity_extraction.schemas.consolidated import ConsolidatedBidderExtraction, DocumentForensics
from app.entity_extraction.schemas.gst import GSTCertExtraction
from app.entity_extraction.schemas.pan import PANITRExtraction
from app.entity_extraction.schemas.udyam import UdyamExtraction
from app.entity_extraction.schemas.balance_sheet import BalanceSheetExtraction
from app.entity_extraction.schemas.ca_udin import CAUDINExtraction
from app.entity_extraction.schemas.mca import MCA21Extraction
from app.entity_extraction.schemas.mii import MakeInIndiaExtraction
from app.entity_extraction.schemas.epfo_esic import EPFOESICExtraction

from app.entity_extraction.regex_patterns import extract_statutory_tokens
from app.entity_extraction.llm_extractor import (
    extract_balance_sheet_structured,
    extract_mii_declaration,
    extract_signatory_name,
)
from app.entity_extraction.bbox_mapper import map_field_to_bbox
from app.entity_extraction.grounding import calculate_grounding_score


def _extract_single_bidder(bidder_id: str, bidder_name: str, documents: list, raw_forensics: dict) -> Dict[str, Any]:
    pages = []
    for doc in documents:
        text = doc.extracted_text if hasattr(doc, "extracted_text") else doc.get("raw_text", "")
        file_name = (
            getattr(doc, "original_relative_path", None)
            or getattr(doc, "display_name", None)
            or (doc.get("file_name") if isinstance(doc, dict) else "document")
        )
        classification = getattr(doc, "classified_type", None) or (doc.get("classification_type") if isinstance(doc, dict) else None)
        
        if text:
            pages.append({
                "raw_text": text,
                "file_name": file_name,
                "classification_type": classification
            })
    
    full_text = " \n ".join([p["raw_text"] for p in pages]) if pages else ""
    
    # 1. Regex Extraction
    fast_ids = extract_statutory_tokens(full_text)

    # 2. Structured & Semantic Extraction
    bs_data = extract_balance_sheet_structured(full_text) or BalanceSheetExtraction()
    mii_data = extract_mii_declaration(full_text) or MakeInIndiaExtraction()
    signatory = extract_signatory_name(full_text)

    # Enterprise category parsing
    udyam_number = fast_ids.get("udyam")
    enterprise_cat = None
    if udyam_number or "udyam" in full_text.lower():
        if "micro" in full_text.lower():
            enterprise_cat = "Micro"
        elif "small" in full_text.lower():
            enterprise_cat = "Small"
        elif "medium" in full_text.lower():
            enterprise_cat = "Medium"

    # 3. Model Assembly
    consolidated = ConsolidatedBidderExtraction(
        submission_id=str(bidder_id),
        gst=GSTCertExtraction(
            gstin=fast_ids.get("gstin")
        ),
        pan_itr=PANITRExtraction(
            pan_number=fast_ids.get("pan"),
            pan_aadhaar_linked=True if (
                "aadhaar linked" in full_text.lower() or "pan linked" in full_text.lower()
            ) else None
        ),
        udyam=UdyamExtraction(
            udyam_registration_number=udyam_number,
            enterprise_category=enterprise_cat
        ),
        balance_sheet=bs_data,
        ca_udin=CAUDINExtraction(
            ca_udin=fast_ids.get("udin")
        ),
        mca21=MCA21Extraction(
            cin=fast_ids.get("cin"),
            active_director_dins=fast_ids.get("dins", [])
        ),
        make_in_india=mii_data,
        epfo_esic=EPFOESICExtraction(
            epfo_establishment_code=fast_ids.get("epfo"),
            esic_code=fast_ids.get("esic")
        ),
        registered_pincode=fast_ids.get("registered_pincode"),
        registered_email=fast_ids.get("registered_email"),
        registered_phone=fast_ids.get("registered_phone"),
        signatory_name=signatory,
        document_forensics=DocumentForensics(
            pdf_producer=raw_forensics.get("producer", "Standard PDF Engine") if isinstance(raw_forensics, dict) else "Standard PDF Engine",
            has_digital_signature=bool(
                (raw_forensics.get("has_dsc", False) if isinstance(raw_forensics, dict) else False) or "digilocker" in full_text.lower()
            ),
            font_anomaly_detected=bool(
                raw_forensics.get("font_anomaly", False) if isinstance(raw_forensics, dict) else False
            )
        ),
        startup_india_number=fast_ids.get("startup_india_number"),
        digilocker_verified=bool("digilocker" in full_text.lower())
    )

    # 4. Bounding Boxes & Grounding
    bboxes = {
        "pan": map_field_to_bbox(consolidated.pan_itr.pan_number, pages),
        "gstin": map_field_to_bbox(consolidated.gst.gstin, pages),
        "udin": map_field_to_bbox(consolidated.ca_udin.ca_udin, pages),
        "udyam": map_field_to_bbox(consolidated.udyam.udyam_registration_number, pages),
        "cin": map_field_to_bbox(consolidated.mca21.cin, pages)
    }
    grounding_report = calculate_grounding_score(consolidated.model_dump(), full_text)

    return {
        "bidder_id": str(bidder_id),
        "bidder_name": bidder_name,
        "document_count": len(pages),
        "extracted_entities": consolidated.model_dump(),
        "bounding_boxes": bboxes,
        "grounding": grounding_report
    }


def process_entity_extraction_job(target: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    db = SessionLocal()
    evaluation_record = None

    try:
        bidders_output = []
        
        # Resolve target whether passed as a String UUID or Swagger JSON Dict
        eval_id_raw = None
        if isinstance(target, str):
            eval_id_raw = target.strip()
        elif isinstance(target, dict):
            eval_id_raw = target.get("evaluation_id") or target.get("id") or target.get("submission_id")

        if eval_id_raw:
            try:
                eval_uuid = uuid.UUID(str(eval_id_raw))
                evaluation_record = db.query(Evaluation).filter(Evaluation.id == eval_uuid).first()
            except ValueError:
                evaluation_record = None

        # Database Mode
        if evaluation_record:
            bidder_folders = db.query(BidderFolder).filter(BidderFolder.evaluation_id == evaluation_record.id).all()

            for bidder in bidder_folders:
                docs = db.query(Document).filter(
                    Document.bidder_folder_id == bidder.id,
                    Document.extracted_text.isnot(None)
                ).all()

                bidder_forensics = {
                    "producer": next((d.pdf_producer for d in docs if d.pdf_producer), None),
                     "has_dsc": any(getattr(d, "has_digital_signature", False) for d in docs),
                    "font_anomaly": any(getattr(d, "font_anomaly_detected", False) for d in docs),
                }

                bidder_data = _extract_single_bidder(
                    bidder_id=str(bidder.id),
                    bidder_name=bidder.raw_folder_name or "Bidder",
                    documents=docs,
                    raw_forensics={}
                )
                bidders_output.append(bidder_data)

            result_payload = {
                "status": "SUCCESS",
                "evaluation_id": str(evaluation_record.id),
                "total_bidders": len(bidders_output),
                "bidders": bidders_output
            }

            # Save extracted JSON in PostgreSQL
            evaluation_record.entities_payload = result_payload
            evaluation_record.status = "COMPLETED"
            db.commit()
            return result_payload

        # Direct Payload Fallback
        pages = target.get("pages", []) if isinstance(target, dict) else []
        bidders_output.append(
            _extract_single_bidder(
                bidder_id=eval_id_raw or "default_bidder",
                bidder_name="Direct Upload",
                documents=pages,
                raw_forensics=target.get("metadata", {}) if isinstance(target, dict) else {}
            )
        )
        return {
            "status": "SUCCESS",
            "evaluation_id": eval_id_raw,
            "total_bidders": len(bidders_output),
            "bidders": bidders_output
        }

    except Exception as e:
        if evaluation_record:
            evaluation_record.status = "FAILED"
            db.commit()
        raise e
    finally:
        db.close()