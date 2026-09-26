from pathlib import Path
from app.database import SessionLocal, BidderFolder, Document
from app.services.text_extraction import extract_text_from_pdf, ocr_pdf, ocr_image_file , extract_forensic_metadata
from app.services.classification import classify_document
import uuid
import shutil

IGNORE_NAMES = {"__MACOSX", "Thumbs.db", ".DS_Store", "desktop.ini"}
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}

def group_top_level_folders(extracted_root: Path, evaluation_id: str):
    db = SessionLocal()

    top_level_folders = [
        p for p in extracted_root.iterdir()
        if p.is_dir() and p.name not in IGNORE_NAMES
    ]

    bidder_folder_records = []

    for folder in top_level_folders:
        bidder_folder_id = uuid.uuid4()
        bidder_folder = BidderFolder(
            id=bidder_folder_id,
            evaluation_id=evaluation_id,
            raw_folder_name=folder.name,
            document_count=0,
        )
        db.add(bidder_folder)
        bidder_folder_records.append((bidder_folder_id, folder))

    db.commit()

    total_documents = 0
    for bidder_folder_id, folder in bidder_folder_records:
        doc_count = collect_documents(folder, bidder_folder_id, db)
        db.query(BidderFolder).filter_by(id=bidder_folder_id).update({"document_count": doc_count})
        total_documents += doc_count

    db.commit()
    db.close()

    return len(bidder_folder_records)


def collect_documents(folder: Path, bidder_folder_id, db) -> int:
    count = 0
    for file_path in folder.rglob("*"):
        if file_path.is_dir() or file_path.name in IGNORE_NAMES:
            continue
        if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue

        doc_id = uuid.uuid4()
        dest_dir = Path("normalized") / str(bidder_folder_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"{doc_id}{file_path.suffix.lower()}"
        shutil.copy2(file_path, dest_path)

        document = Document(
            id=doc_id,
            bidder_folder_id=bidder_folder_id,
            original_relative_path=str(file_path.relative_to(folder)),
            stored_path=str(dest_path),
            extension=file_path.suffix.lower(),
        )
        db.add(document)
        count += 1

    return count



def extract_all_documents(evaluation_id: str, db) -> int:
    documents = (
        db.query(Document)
        .join(BidderFolder, Document.bidder_folder_id == BidderFolder.id)
        .filter(BidderFolder.evaluation_id == evaluation_id)
        .all()
    )

    count = 0
    for doc in documents:
        try:
            if doc.extension == ".pdf":
                text = extract_text_from_pdf(doc.stored_path)
                if text:
                    doc.extracted_text = text
                    doc.classification_status = "text_extracted"

                    forensic = extract_forensic_metadata(doc.stored_path)
                    doc.pdf_producer = forensic["producer"]
                    doc.has_digital_signature = forensic["has_digital_signature"]
                    doc.font_anomaly_detected = forensic["font_anomaly_detected"]
                else:
                    doc.extracted_text = ocr_pdf(doc.stored_path)
                    doc.classification_status = "ocr_extracted"
            else:
                doc.extracted_text = ocr_image_file(doc.stored_path)
                doc.classification_status = "ocr_extracted"

            classified_type, display_name = classify_document(doc.extracted_text)
            doc.classified_type = classified_type
            doc.display_name = display_name

        except Exception as e:
            doc.classification_status = f"extraction_failed: {str(e)}"

        count += 1

    db.commit()
    return count