"""TEST N — end-to-end: Module 1/2-style raw document TEXT flows through
the adapter's real per-document Module 2 extractors into Core Evidence,
through the VerificationEngine, into a canonical flag and a grounded
explanation — all without Module 3."""

from __future__ import annotations

from app.integration import module4_service
from app.integration.module12_adapter import (
    build_bidder_evidence,
    build_upstream_payload,
    extract_document_fields,
)
from tests.helpers import flags_of


def test_n_end_to_end_from_document_text():
    bidder_id = "b-e2e"
    documents = [
        {
            "document_id": "GST_PDF_DOC",
            "doc_type": "gst_certificate",
            "extracted_text": (
                "Form GST REG-06\nGoods and Services Tax\n"
                "Certificate of Registration\n"
                "GSTIN: 27AAACI1234F1Z5\n"
                "Legal Name: ACME ENTERPRISES PRIVATE LIMITED\n"
            ),
        },
        {
            "document_id": "PAN_PDF_DOC",
            "doc_type": "pan_card",
            "extracted_text": (
                "Income Tax Department\nGovt. of India\n"
                "Permanent Account Number: AAACI1234F\n"
                "Name: ACME ENTERPRISES PRIVATE LIMITED\n"
            ),
        },
        {
            # A second GST certificate (additional place of business) whose
            # GSTIN contradicts the first one. Core only compares GSTIN
            # values between GST / GSTN family documents — a GSTIN embedded
            # in, say, an Udyam certificate is deliberately NOT compared.
            "document_id": "GST_PDF_DOC_2",
            "doc_type": "gst_certificate",
            "extracted_text": (
                "Form GST REG-06\nGoods and Services Tax\n"
                "Certificate of Registration\n"
                "GSTIN: 29BBBCD1234E1Z6\n"  # deliberate contradiction
                "Legal Name: ACME ENTERPRISES PRIVATE LIMITED\n"
            ),
        },
        {
            "document_id": "UDYAM_PDF_DOC",
            "doc_type": "udyam_certificate",
            "extracted_text": (
                "Udyam Registration Certificate\n"
                "Udyam Registration Number: UDYAM-MH-12-0012345\n"
            ),
        },
        {
            "document_id": "MII_PDF_DOC",
            "doc_type": "make_in_india_local_content",
            "extracted_text": (
                "Make in India Self Certification of Local Content\n"
                "Local Content: 68.5%\n"
            ),
        },
    ]

    # The adapter re-runs Module 2's real extractors PER DOCUMENT — the
    # bidder-level concatenation is never used as the evidence source.
    gst_fields = extract_document_fields(
        "gst_certificate", documents[0]["extracted_text"]
    )
    assert gst_fields["gstin"] == "27AAACI1234F1Z5"
    udyam_fields = extract_document_fields(
        "udyam_certificate", documents[3]["extracted_text"]
    )
    assert udyam_fields["udyam_registration_number"] == "UDYAM-MH-12-0012345"
    # A GSTIN extractable from a NON-GST document is kept as document-level
    # provenance but is intentionally not comparable by Core's rules.
    assert extract_document_fields(
        "udyam_certificate", "GSTIN: 29BBBCD1234E1Z6\n"
    )["gstin"] == "29BBBCD1234E1Z6"
    mii_fields = extract_document_fields(
        "make_in_india_local_content", documents[4]["extracted_text"]
    )
    assert mii_fields["local_content_percentage"] == 68.5

    evidence = build_bidder_evidence(bidder_id, documents)
    result = module4_service.run_bidder_verification(bidder_id, evidence)

    # The contradiction between the two documents' GSTINs is detected by
    # the real CrossDocumentConsistencyEngine via VerificationEngine.
    assert "CROSS_DOCUMENT_IDENTIFIER_CONFLICT" in flags_of(result)
    finding = next(
        f for f in result["findings"]
        if f["flag_id"] == "CROSS_DOCUMENT_IDENTIFIER_CONFLICT"
    )
    assert set(finding["evidence_refs"]) == {
        "GST_PDF_DOC:gstin",
        "GST_PDF_DOC_2:gstin",
    }

    # A grounded explanation exists and cites the real conflicted values.
    explanation = next(
        e for e in result["explanations"]
        if e["flag_id"] == "CROSS_DOCUMENT_IDENTIFIER_CONFLICT"
    )
    assert "27AAACI1234F1Z5" in explanation["content"]["detailed_explanation"]
    assert "29BBBCD1234E1Z6" in explanation["content"]["detailed_explanation"]

    # The document-level payload handed to Core is contract-valid and
    # carries no fabricated confidence/page/bbox values.
    payload = build_upstream_payload(bidder_id, documents)
    assert payload["bidder_id"] == bidder_id
    for document in payload["documents"]:
        assert document["document_id"].startswith(("GST_", "PAN_", "UDYAM_", "MII_"))
        for field in document["extracted_fields"].values():
            assert field["confidence"] is None
            assert field["page"] is None
            assert field["bbox"] is None

    assert result["status"] == module4_service.STATUS_VERIFIED
    assert result["verification_records_used"] == 0
