from ai_verification.engine import VerificationEngine
from ai_verification.models import VerificationInput, BidderSummary
from compliance_engine.models import Evidence
from ai_verification.cross_bidder.document_artifact_store import InMemoryDocumentArtifactStore, DocumentMeta
from datetime import date

raw_text = "This is the exact same document content for both bidders."
file_hash = "sha256:" + "a" * 62
metadata = {
    "doc1": {
        "document_type": "PDF",
        "evidence_id": "ev1",
        "ocr_confidence": 0.95,
        "document_type_confidence": 0.9,
        "issuer": "Test Issuer",
        "authorization_number": "AUTH123",
        "issue_date": date(2024, 1, 1),
        "valid_until": date(2025, 1, 1),
        "bidder_name": "Bidder A",
        "territory": "Territory X",
    }
}
artifact_store = InMemoryDocumentArtifactStore(
    raw_texts={"doc1": raw_text},
    file_hashes={"doc1": file_hash},
    metadata={k: DocumentMeta(**v) for k, v in metadata.items()},
)

engine = VerificationEngine(artifact_store=artifact_store)

ev1 = Evidence(evidence_id="ev1", bidder_id="bidder-1", document_id="doc1", document_type="PDF", field_name="f1", value="v1")
ev2 = Evidence(evidence_id="ev2", bidder_id="bidder-2", document_id="doc1", document_type="PDF", field_name="f1", value="v1")

input_data = VerificationInput(
    bidder_id="bidder-1",
    evidence=[ev1],
    compliance_results=[],
    identity_findings=[],
    bidder_corpus=[
        BidderSummary(
            bidder_id="bidder-2",
            evidence=[ev2],
            compliance_results=[],
            identity_findings=[],
            verification_records=[],
        )
    ],
)

print("Running engine...")
result = engine.run(input_data)
print("Findings:", result.findings)
print("Number of findings:", len(result.findings))
