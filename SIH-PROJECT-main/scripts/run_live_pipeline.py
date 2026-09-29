"""LIVE end-to-end backend run: Module 1 -> 2 -> 3 -> 4 -> 5 -> PostgreSQL -> API.

Builds a REAL bidder-submission zip (actual PDFs), runs the real Celery
task body synchronously (no broker needed — the task function is called
directly), and then reads everything back from PostgreSQL through the
existing API endpoint.

Prerequisites:
    * PostgreSQL with gem_user/gem_pass/gem_verification reachable at
      the DATABASE_URL (the app's own docker-compose image).
    * Core-Engine-GeM installed (pip install -e ../Core-Engine-GeM).

Run from the SIH-PROJECT-main directory:

    DATABASE_URL='postgresql+psycopg://gem_user:gem_pass@localhost:5433/gem_verification' \\
        python scripts/run_live_pipeline.py
"""

from __future__ import annotations

import os
import sys
import uuid
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://gem_user:gem_pass@localhost:5433/gem_verification",
)
os.environ["DATABASE_URL"] = DATABASE_URL

import fitz  # pymupdf — Module 1's real PDF text extractor


def make_pdf(path: Path, text: str) -> None:
    """Create a real PDF whose extracted text is ``text``."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 90), text, fontsize=11)
    doc.save(str(path))
    doc.close()


GST_CERT = (
    "FORM GST REG-06\nGoods and Services Tax\nCertificate of Registration\n"
    "GSTIN: 27AAACI1234F1Z5\nLegal Name: ACME ENTERPRISES PRIVATE LIMITED\n"
)
GST_CERT_CONTRADICTING = (
    "FORM GST REG-06\nGoods and Services Tax\nCertificate of Registration\n"
    "GSTIN: 29BBBCD1234E1Z6\nLegal Name: ACME ENTERPRISES PRIVATE LIMITED\n"
)
PAN_CARD = (
    "Income Tax Department\nGovt. of India\nPermanent Account Number: AAACI1234F\n"
    "Name: ACME ENTERPRISES PRIVATE LIMITED\n"
)
UDYAM_CERT = (
    "Udyam Registration Certificate\n"
    "Udyam Registration Number: UDYAM-MH-12-0012345\n"
    "ACME ENTERPRISES PRIVATE LIMITED\n"
)
BALANCE_SHEET = (
    "Audited Financial Statement\nBalance Sheet as at 31 March 2024\n"
    "Annual Turnover: INR 12,00,00,000\n"
    "Chartered Accountant\nCA UDIN: 0029XXXX123456\n"
)
MII_CERT = (
    "Make in India Self-Certification of Local Content\n"
    "Local Content: 68.5%\nClass-I Local Supplier\n"
)


def build_submission_zip(dest: Path) -> None:
    """Two real bidder folders inside one submission zip."""
    work = dest.parent / "submission_src"
    bidder_a = work / "Bidder_A_Acme"
    bidder_b = work / "Bidder_B_Contradiction"
    bidder_a.mkdir(parents=True, exist_ok=True)
    bidder_b.mkdir(parents=True, exist_ok=True)

    make_pdf(bidder_a / "gst_certificate.pdf", GST_CERT)
    make_pdf(bidder_a / "pan_card.pdf", PAN_CARD)
    make_pdf(bidder_a / "udyam_certificate.pdf", UDYAM_CERT)
    make_pdf(bidder_a / "balance_sheet.pdf", BALANCE_SHEET)
    make_pdf(bidder_a / "local_content.pdf", MII_CERT)

    # Bidder B: two GST certificates whose GSTINs contradict each other —
    # a real cross-document contradiction Module 4 must flag.
    make_pdf(bidder_b / "gst_certificate_1.pdf", GST_CERT)
    make_pdf(bidder_b / "gst_certificate_2.pdf", GST_CERT_CONTRADICTING)
    make_pdf(bidder_b / "pan_card.pdf", PAN_CARD)

    with zipfile.ZipFile(dest, "w") as zf:
        for pdf in sorted(work.rglob("*.pdf")):
            zf.write(pdf, arcname=str(pdf.relative_to(work)))


def main() -> int:
    from app.database import (
        Base,
        BidderComplianceResultRecord,
        BidderDocumentScoreRecord,
        BidderVerificationRecord,
        BidderVerificationResult,
        Document,
        DocumentEvidence,
        Evaluation,
        SessionLocal,
        engine,
    )
    from app.tasks import process_evaluation

    print(f"DATABASE_URL = {DATABASE_URL}")
    Base.metadata.create_all(bind=engine)

    zip_path = PROJECT_ROOT / "scripts" / "live_submission.zip"
    build_submission_zip(zip_path)

    evaluation_id = str(uuid.uuid4())
    db = SessionLocal()
    db.add(Evaluation(id=uuid.UUID(evaluation_id),
                      original_zip_name="live_submission.zip",
                      status="uploaded"))
    db.commit()
    db.close()

    print(f"\n=== Running REAL pipeline (task body) for evaluation {evaluation_id}")
    summary = process_evaluation(evaluation_id, str(zip_path))
    print("task summary:", summary)

    print("\n=== Persisted rows per table")
    db = SessionLocal()
    evaluation = db.query(Evaluation).filter(
        Evaluation.id == uuid.UUID(evaluation_id)).first()
    print(f"evaluation.status           = {evaluation.status}")
    print(f"documents                   = {db.query(Document).count()}")
    print(f"document_evidence           = {db.query(DocumentEvidence).count()}")
    print(f"bidder_compliance_results   = {db.query(BidderComplianceResultRecord).count()}")
    print(f"bidder_verification_records= {db.query(BidderVerificationRecord).count()}")
    print(f"bidder_verification_results= {db.query(BidderVerificationResult).count()}")
    print(f"bidder_document_scores     = {db.query(BidderDocumentScoreRecord).count()}")

    print("\n=== Per-bidder Module 3/4/5 results")
    for row in db.query(BidderVerificationResult).all():
        print(f"\nbidder {row.bidder_folder_id} status={row.status}")
        print(f"  flags: {row.flags}")
        for r in db.query(BidderComplianceResultRecord).filter(
            BidderComplianceResultRecord.bidder_folder_id == row.bidder_folder_id
        ).all():
            print(f"  M3  {r.capability:16} {r.status:14} refs={r.verification_refs}")
        for v in db.query(BidderVerificationRecord).filter(
            BidderVerificationRecord.bidder_folder_id == row.bidder_folder_id
        ).all():
            print(f"  M3v {v.source:10} {v.status:12} queried={v.queried_identifier}")
        score = db.query(BidderDocumentScoreRecord).filter(
            BidderDocumentScoreRecord.bidder_folder_id == row.bidder_folder_id
        ).first()
        if score:
            print(f"  M5  score={score.overall_score} category={score.category}")
            print(f"  M5  reasons={score.reason_codes}")
        for finding in (row.findings or [])[:1]:
            print(f"  example finding: {finding['flag_id']} severity={finding['severity']}")
            print(f"    evidence_refs={finding['evidence_refs']}")
        for explanation in (row.explanations or [])[:1]:
            print(f"  example explanation: {explanation['flag_id']}")
            print(f"    grounded evidence={explanation['grounding']['evidence_refs']}")
    db.close()

    print("\n=== API endpoint read-back")
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    response = client.get(f"/api/v1/evaluations/{evaluation_id}/verification")
    print("HTTP", response.status_code)
    payload = response.json()
    print("evaluation status:", payload["status"])
    for bidder in payload["bidders"]:
        print(
            f"  {bidder['bidder_name']}: status={bidder['status']} "
            f"evidence={len(bidder['evidence'])} "
            f"compliance={len(bidder['compliance_results'])} "
            f"verifications={len(bidder['verification_records'])} "
            f"findings={len(bidder['findings'])} "
            f"scoring={'yes' if bidder['scoring'] else 'no'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

