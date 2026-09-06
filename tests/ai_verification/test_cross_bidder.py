"""Integration tests for cross-bidder document anomaly detection in VerificationEngine."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List

import pytest

from ai_verification.engine import VerificationEngine
from ai_verification.models import (
    BidderSummary,
    VerificationInput,
    VerificationResult,
    VerificationFinding,
)
from compliance_engine.models import (
    Evidence,
    ComplianceResult,
    IdentityFinding,
)
from compliance_engine.models.verification import Verification, VerificationStatus
from ai_verification.cross_bidder.document_artifact_store import InMemoryDocumentArtifactStore, DocumentMeta


def make_evidence(
    *,
    evidence_id: str,
    bidder_id: str,
    document_id: str,
    document_type: str,
    field_name: str = "dummy_field",
    value: str = "dummy_value",
    confidence: float = 1.0,
) -> Evidence:
    """Helper to create an Evidence instance."""
    return Evidence(
        evidence_id=evidence_id,
        bidder_id=bidder_id,
        document_id=document_id,
        document_type=document_type,
        field_name=field_name,
        value=value,
        confidence=confidence,
    )


def make_verification_record(
    *,
    verification_id: str,
    bidder_id: str,
    capability: str = "GST",
    source: str = "GSTN_MOCK",
    status: VerificationStatus = VerificationStatus.VERIFIED,
    data: dict | None = None,
) -> Verification:
    """Helper to create a Verification record."""
    return Verification(
        verification_id=verification_id,
        bidder_id=bidder_id,
        capability=capability,
        source=source,
        status=status,
        data=data or {},
    )


def _make_meta(metadata_dict: dict) -> DocumentMeta:
    """Helper to create a DocumentMeta from a dict."""
    return DocumentMeta(**metadata_dict)


def test_empty_corpus_no_findings() -> None:
    """With an empty corpus, the engine should return no findings."""
    engine = VerificationEngine()
    input_data = VerificationInput(
        bidder_id="bidder-1",
        evidence=[],
        compliance_results=[],
        identity_findings=[],
        bidder_corpus=[],
    )
    result: VerificationResult = engine.run(input_data)
    assert result.findings == []


def test_exact_reused_document_produces_reused_finding() -> None:
    """Two bidders submitting the exact same document should yield a REUSED finding."""
    # Setup artifact store with two document IDs pointing to same content.
    raw_text = "This is the exact same document content for both bidders."
    file_hash = "sha256:" + "a" * 62  # dummy hash
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
        },
        "doc2": {
            "document_type": "PDF",
            "evidence_id": "ev2",
            "ocr_confidence": 0.95,
            "document_type_confidence": 0.9,
            "issuer": "Test Issuer",
            "authorization_number": "AUTH123",
            "issue_date": date(2024, 1, 1),
            "valid_until": date(2025, 1, 1),
            "bidder_name": "Bidder B",
            "territory": "Territory X",
        }
    }
    artifact_store = InMemoryDocumentArtifactStore(
        raw_texts={"doc1": raw_text, "doc2": raw_text},
        file_hashes={"doc1": file_hash, "doc2": file_hash},
        metadata={k: _make_meta(v) for k, v in metadata.items()},
    )
    engine = VerificationEngine(artifact_store=artifact_store)

    # Bidder 1 evidence
    ev1 = make_evidence(
        evidence_id="ev1",
        bidder_id="bidder-1",
        document_id="doc1",
        document_type="PDF",
    )
    # Bidder 2 evidence (same content but different document ID)
    ev2 = make_evidence(
        evidence_id="ev2",
        bidder_id="bidder-2",
        document_id="doc2",
        document_type="PDF",
    )

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

    result: VerificationResult = engine.run(input_data)

    # We expect exactly one finding
    assert len(result.findings) == 1
    finding = result.findings[0]

    # Check that it's a cross-bidder reused document finding
    assert finding.flag_id == "CROSS_BIDDER_DOCUMENT_REUSED"
    assert finding.bidder_id == "bidder-1"  # left bidder in our pairing
    assert finding.related_bidder_ids == ["bidder-2"]
    # Evidence refs should include both evidence IDs
    assert set(finding.evidence_refs) == {"ev1", "ev2"}
    # Verification refs should be empty because we didn't provide verification records
    assert finding.verification_refs == []
    # Confidence should be between 0 and 1
    assert 0.0 <= finding.confidence <= 1.0
    # Explanation should be a string
    assert isinstance(finding.explanation, str) and len(finding.explanation) > 0
    # Trace should be present
    assert finding.trace is not None


def test_near_duplicate_document_produces_near_duplicate_finding() -> None:
    """Two bidders submitting near-duplicate documents should yield a NEAR_DUPLICATE finding."""
    raw_text1 = "the quick brown fox"
    raw_text2 = "the quick brown foxx"
    file_hash1 = "sha256:" + "b" * 62
    file_hash2 = "sha256:" + "c" * 62
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
        },
        "doc2": {
            "document_type": "PDF",
            "evidence_id": "ev2",
            "ocr_confidence": 0.93,
            "document_type_confidence": 0.9,
            "issuer": "Test Issuer",
            "authorization_number": "AUTH123",
            "issue_date": date(2024, 1, 1),
            "valid_until": date(2025, 1, 1),
            "bidder_name": "Bidder B",
            "territory": "Territory X",
        }
    }
    artifact_store = InMemoryDocumentArtifactStore(
        raw_texts={"doc1": raw_text1, "doc2": raw_text2},
        file_hashes={"doc1": file_hash1, "doc2": file_hash2},
        metadata={k: _make_meta(v) for k, v in metadata.items()},
    )
    engine = VerificationEngine(artifact_store=artifact_store)

    ev1 = make_evidence(
        evidence_id="ev1",
        bidder_id="bidder-1",
        document_id="doc1",
        document_type="PDF",
    )
    ev2 = make_evidence(
        evidence_id="ev2",
        bidder_id="bidder-2",
        document_id="doc2",
        document_type="PDF",
    )

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

    result: VerificationResult = engine.run(input_data)

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.flag_id == "CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE"
    assert finding.bidder_id == "bidder-1"
    assert finding.related_bidder_ids == ["bidder-2"]
    assert set(finding.evidence_refs) == {"ev1", "ev2"}
    assert finding.verification_refs == []
    assert 0.0 <= finding.confidence <= 1.0
    assert isinstance(finding.explanation, str) and len(finding.explanation) > 0
    assert finding.trace is not None


def test_same_bidder_documents_no_finding() -> None:
    """Documents from the same bidder should not produce cross-bidder findings."""
    raw_text = "Same document, same bidder."
    file_hash = "sha256:" + "d" * 62
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
        metadata={k: _make_meta(v) for k, v in metadata.items()},
    )
    engine = VerificationEngine(artifact_store=artifact_store)

    # Two pieces of evidence from the same bidder, same document
    ev1 = make_evidence(
        evidence_id="ev1",
        bidder_id="bidder-1",
        document_id="doc1",
        document_type="PDF",
        field_name="field1",
        value="value1",
    )
    ev2 = make_evidence(
        evidence_id="ev2",
        bidder_id="bidder-1",
        document_id="doc1",
        document_type="PDF",
        field_name="field2",
        value="value2",
    )

    input_data = VerificationInput(
        bidder_id="bidder-1",
        evidence=[ev1, ev2],
        compliance_results=[],
        identity_findings=[],
        bidder_corpus=[],  # no corpus
    )

    result: VerificationResult = engine.run(input_data)
    assert result.findings == []  # no cross-bidder findings expected


def test_different_document_types_no_finding() -> None:
    """Documents of different types should not produce a finding."""
    raw_text1 = "the quick brown fox"
    raw_text2 = "the quick brown foxx"
    file_hash1 = "sha256:" + "e" * 62
    file_hash2 = "sha256:" + "f" * 62
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
        },
        "doc2": {
            "document_type": "JPEG",
            "evidence_id": "ev2",
            "ocr_confidence": 0.90,
            "document_type_confidence": 0.85,
            "issuer": "Test Issuer",
            "authorization_number": "AUTH124",
            "issue_date": date(2024, 1, 1),
            "valid_until": date(2025, 1, 1),
            "bidder_name": "Bidder B",
            "territory": "Territory X",
        }
    }
    artifact_store = InMemoryDocumentArtifactStore(
        raw_texts={"doc1": raw_text1, "doc2": raw_text2},
        file_hashes={"doc1": file_hash1, "doc2": file_hash2},
        metadata={k: _make_meta(v) for k, v in metadata.items()},
    )
    engine = VerificationEngine(artifact_store=artifact_store)

    ev1 = make_evidence(
        evidence_id="ev1",
        bidder_id="bidder-1",
        document_id="doc1",
        document_type="PDF",
    )
    ev2 = make_evidence(
        evidence_id="ev2",
        bidder_id="bidder-2",
        document_id="doc2",
        document_type="JPEG",
    )

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

    result: VerificationResult = engine.run(input_data)
    assert result.findings == []


def test_duplicate_pair_emitted_only_once() -> None:
    """The same document pair should not produce two findings."""
    # We'll create two evidences per bidder for the same document, but we expect only one finding.
    raw_text = "Identical document."
    file_hash = "sha256:" + "g" * 62
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
        },
        "doc2": {
            "document_type": "PDF",
            "evidence_id": "ev3",
            "ocr_confidence": 0.95,
            "document_type_confidence": 0.9,
            "issuer": "Test Issuer",
            "authorization_number": "AUTH123",
            "issue_date": date(2024, 1, 1),
            "valid_until": date(2025, 1, 1),
            "bidder_name": "Bidder B",
            "territory": "Territory X",
        }
    }
    artifact_store = InMemoryDocumentArtifactStore(
        raw_texts={"doc1": raw_text, "doc2": raw_text},
        file_hashes={"doc1": file_hash, "doc2": file_hash},
        metadata={k: _make_meta(v) for k, v in metadata.items()},
    )
    engine = VerificationEngine(artifact_store=artifact_store)

    # Bidder 1: two evidence for the same document
    ev1a = make_evidence(
        evidence_id="ev1a",
        bidder_id="bidder-1",
        document_id="doc1",
        document_type="PDF",
        field_name="field1",
        value="value1",
    )
    ev1b = make_evidence(
        evidence_id="ev1b",
        bidder_id="bidder-1",
        document_id="doc1",
        document_type="PDF",
        field_name="field2",
        value="value2",
    )
    # Bidder 2: two evidence for the same document
    ev2a = make_evidence(
        evidence_id="ev2a",
        bidder_id="bidder-2",
        document_id="doc2",
        document_type="PDF",
        field_name="field1",
        value="value1",
    )
    ev2b = make_evidence(
        evidence_id="ev2b",
        bidder_id="bidder-2",
        document_id="doc2",
        document_type="PDF",
        field_name="field2",
        value="value2",
    )

    input_data = VerificationInput(
        bidder_id="bidder-1",
        evidence=[ev1a, ev1b],
        compliance_results=[],
        identity_findings=[],
        bidder_corpus=[
            BidderSummary(
                bidder_id="bidder-2",
                evidence=[ev2a, ev2b],
                compliance_results=[],
                identity_findings=[],
                verification_records=[],
            )
        ],
    )

    result: VerificationResult = engine.run(input_data)

    # We expect exactly one finding (the pair of documents, not per evidence pair)
    # Our engine currently will produce a finding for each evidence pair that matches.
    # We have 2 evidences from bidder1 and 2 from bidder2 -> 4 pairs.
    # But note: we deduplicate by document_id per bidder, so each bidder has only one unique document_id.
    # Therefore, we will have only one pair: (doc1 from bidder1, doc2 from bidder2).
    # So we expect one finding.
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.flag_id == "CROSS_BIDDER_DOCUMENT_REUSED"
    # Evidence refs should include the evidence IDs from the metadata? Actually, the finding's evidence_refs
    # are built from the metadata's evidence_id. In our metadata, we set evidence_id to "ev1" for doc1 and "ev3" for doc2.
    # But note: we have two evidences per bidder, but the metadata only has one evidence_id per document.
    # The detector uses the metadata from the artifact store, which we set with evidence_id="ev1" for doc1 and "ev3" for doc2.
    # So we expect the finding to have evidence_refs = ["ev1"] (from left) and ["ev3"] from right? Actually, the detector
    # collects evidence_refs from both left and right metadata. Since we set the evidence_id for each document, we might get ["ev1", "ev3"].
    # Let's not over-specify; we just check that the finding is produced.
    assert isinstance(finding, VerificationFinding)


def test_verification_refs_are_empty_when_no_association_possible() -> None:
    """Verification refs should be empty because there is no way to associate verification records with documents."""
    raw_text = "Document."
    file_hash = "sha256:" + "k" * 62
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
        },
        "doc2": {
            "document_type": "PDF",
            "evidence_id": "ev2",
            "ocr_confidence": 0.95,
            "document_type_confidence": 0.9,
            "issuer": "Test Issuer",
            "authorization_number": "AUTH123",
            "issue_date": date(2024, 1, 1),
            "valid_until": date(2025, 1, 1),
            "bidder_name": "Bidder B",
            "territory": "Territory X",
        }
    }
    artifact_store = InMemoryDocumentArtifactStore(
        raw_texts={"doc1": raw_text, "doc2": raw_text},
        file_hashes={"doc1": file_hash, "doc2": file_hash},
        metadata={k: _make_meta(v) for k, v in metadata.items()},
    )
    engine = VerificationEngine(artifact_store=artifact_store)

    ver1 = make_verification_record(
        verification_id="ver1",
        bidder_id="bidder-1",
    )
    ver2 = make_verification_record(
        verification_id="ver2",
        bidder_id="bidder-2",
    )

    ev1 = make_evidence(
        evidence_id="ev1",
        bidder_id="bidder-1",
        document_id="doc1",
        document_type="PDF",
    )
    ev2 = make_evidence(
        evidence_id="ev2",
        bidder_id="bidder-2",
        document_id="doc2",
        document_type="PDF",
    )

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
                verification_records=[ver2],
            )
        ],
    )

    result: VerificationResult = engine.run(input_data)

    assert len(result.findings) == 1
    finding = result.findings[0]
    # Since we cannot associate verification records with documents, we expect verification_refs to be empty.
    assert finding.verification_refs == []
    # But we do expect the finding to be produced.
    assert finding.flag_id == "CROSS_BIDDER_DOCUMENT_REUSED"


def test_input_objects_not_mutated() -> None:
    """The VerificationEngine should not mutate the input VerificationInput."""
    raw_text = "Test document."
    file_hash = "sha256:" + "i" * 62
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
        metadata={k: _make_meta(v) for k, v in metadata.items()},
    )
    engine = VerificationEngine(artifact_store=artifact_store)

    ev1 = make_evidence(
        evidence_id="ev1",
        bidder_id="bidder-1",
        document_id="doc1",
        document_type="PDF",
    )
    ev2 = make_evidence(
        evidence_id="ev2",
        bidder_id="bidder-2",
        document_id="doc1",
        document_type="PDF",
    )

    original_input = VerificationInput(
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
    # Deep copy the input to compare later
    import copy
    input_copy = copy.deepcopy(original_input)

    result: VerificationResult = engine.run(original_input)

    # The input should be unchanged
    assert original_input == input_copy


def test_missing_artifact_data_fails_safely() -> None:
    """If the artifact store is missing data for a document, the engine should not crash."""
    # We'll create an artifact store that is missing the raw text for a document.
    raw_text = "Available document."
    file_hash = "sha256:" + "j" * 62
    metadata = {
        "doc1": {  # this one we have
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
        },
        "doc2": {  # this one we will not provide raw text for
            "document_type": "PDF",
            "evidence_id": "ev2",
            "ocr_confidence": 0.90,
            "document_type_confidence": 0.85,
            "issuer": "Test Issuer",
            "authorization_number": "AUTH124",
            "issue_date": date(2024, 1, 1),
            "valid_until": date(2025, 1, 1),
            "bidder_name": "Bidder B",
            "territory": "Territory X",
        }
    }
    # We only provide raw text for doc1
    artifact_store = InMemoryDocumentArtifactStore(
        raw_texts={"doc1": raw_text},  # missing doc2
        file_hashes={"doc1": file_hash, "doc2": file_hash},  # we provide file hash for both
        metadata={k: _make_meta(v) for k, v in metadata.items()},
    )
    engine = VerificationEngine(artifact_store=artifact_store)

    ev1 = make_evidence(
        evidence_id="ev1",
        bidder_id="bidder-1",
        document_id="doc1",
        document_type="PDF",
    )
    ev2 = make_evidence(
        evidence_id="ev2",
        bidder_id="bidder-2",
        document_id="doc2",
        document_type="PDF",
    )

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

    # This should not raise an exception
    result: VerificationResult = engine.run(input_data)
    # We don't make any assertions about the findings because the missing data may lead to no findings.
    # The important thing is that it doesn't crash.


# ===========================================================================
# Explicit propagation tests (TASK 6 #7, #8, #9)
# ===========================================================================


def test_explicit_bidder_id_propagation_on_finding_and_trace() -> None:
    """The primary bidder and related bidder IDs must be propagated
    explicitly onto both the finding and the similarity trace.

    The contract requires:

    - ``finding.bidder_id`` is the *primary* bidder (left side).
    - ``finding.related_bidder_ids`` lists the other bidder (right side).
    - ``finding.trace.left_bidder_id`` / ``right_bidder_id`` reflect the
      pair orientation used to detect the anomaly.
    """
    raw_text = "Explicit bidder id propagation test."
    file_hash = "sha256:" + "p" * 62
    metadata = {
        "doc1": {
            "document_type": "PDF",
            "evidence_id": "ev-primary",
            "ocr_confidence": 0.95,
            "document_type_confidence": 0.9,
            "issuer": "Test Issuer",
            "authorization_number": "AUTH-PROP",
            "issue_date": date(2024, 1, 1),
            "valid_until": date(2025, 1, 1),
            "bidder_name": "Bidder A",
            "territory": "Territory X",
        },
        "doc2": {
            "document_type": "PDF",
            "evidence_id": "ev-other",
            "ocr_confidence": 0.95,
            "document_type_confidence": 0.9,
            "issuer": "Test Issuer",
            "authorization_number": "AUTH-PROP",
            "issue_date": date(2024, 1, 1),
            "valid_until": date(2025, 1, 1),
            "bidder_name": "Bidder B",
            "territory": "Territory X",
        },
    }
    artifact_store = InMemoryDocumentArtifactStore(
        raw_texts={"doc1": raw_text, "doc2": raw_text},
        file_hashes={"doc1": file_hash, "doc2": file_hash},
        metadata={k: _make_meta(v) for k, v in metadata.items()},
    )
    engine = VerificationEngine(artifact_store=artifact_store)

    ev1 = make_evidence(
        evidence_id="ev-primary",
        bidder_id="bidder-primary",
        document_id="doc1",
        document_type="PDF",
    )
    ev2 = make_evidence(
        evidence_id="ev-other",
        bidder_id="bidder-other",
        document_id="doc2",
        document_type="PDF",
    )

    input_data = VerificationInput(
        bidder_id="bidder-primary",
        evidence=[ev1],
        compliance_results=[],
        identity_findings=[],
        bidder_corpus=[
            BidderSummary(
                bidder_id="bidder-other",
                evidence=[ev2],
                compliance_results=[],
                identity_findings=[],
                verification_records=[],
            )
        ],
    )

    result: VerificationResult = engine.run(input_data)

    assert len(result.findings) == 1
    finding = result.findings[0]

    # Finding scoped to the primary bidder.
    assert finding.bidder_id == "bidder-primary"
    # Other bidder is preserved on the finding.
    assert finding.related_bidder_ids == ["bidder-other"]

    # The trace must carry the explicit left/right bidder IDs.
    assert finding.trace is not None
    assert finding.trace.left_bidder_id == "bidder-primary"
    assert finding.trace.right_bidder_id == "bidder-other"
    # The trace must also carry the explicit document IDs that were compared.
    assert finding.trace.left_document_id == "doc1"
    assert finding.trace.right_document_id == "doc2"


def test_evidence_refs_propagation_deterministic() -> None:
    """Evidence refs on the finding must be drawn from the actual
    ``Evidence`` items (and ``DocumentMeta.evidence_id``) that the
    detector looked at, and they must be preserved verbatim.

    Two-bidder exact-reuse case, with a single evidence per document,
    so we can assert exact equality on the resulting ``evidence_refs``.
    """
    raw_text = "Evidence ref propagation test."
    file_hash = "sha256:" + "q" * 62
    metadata = {
        "doc1": {
            "document_type": "PDF",
            "evidence_id": "ev-primary",
            "ocr_confidence": 0.95,
            "document_type_confidence": 0.9,
            "issuer": "Test Issuer",
            "authorization_number": "AUTH-EVR",
            "issue_date": date(2024, 2, 1),
            "valid_until": date(2025, 2, 1),
            "bidder_name": "Bidder A",
            "territory": "Territory X",
        },
        "doc2": {
            "document_type": "PDF",
            "evidence_id": "ev-other",
            "ocr_confidence": 0.95,
            "document_type_confidence": 0.9,
            "issuer": "Test Issuer",
            "authorization_number": "AUTH-EVR",
            "issue_date": date(2024, 2, 1),
            "valid_until": date(2025, 2, 1),
            "bidder_name": "Bidder B",
            "territory": "Territory X",
        },
    }
    artifact_store = InMemoryDocumentArtifactStore(
        raw_texts={"doc1": raw_text, "doc2": raw_text},
        file_hashes={"doc1": file_hash, "doc2": file_hash},
        metadata={k: _make_meta(v) for k, v in metadata.items()},
    )
    engine = VerificationEngine(artifact_store=artifact_store)

    ev1 = make_evidence(
        evidence_id="ev-primary",
        bidder_id="bidder-1",
        document_id="doc1",
        document_type="PDF",
    )
    ev2 = make_evidence(
        evidence_id="ev-other",
        bidder_id="bidder-2",
        document_id="doc2",
        document_type="PDF",
    )

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

    result: VerificationResult = engine.run(input_data)

    assert len(result.findings) == 1
    finding = result.findings[0]
    # The detector pulls evidence_refs from the DocumentMeta.evidence_id
    # fields of the two documents, in left-then-right order.
    assert finding.evidence_refs == ["ev-primary", "ev-other"]


def test_verification_refs_populated_when_evidence_ids_match() -> None:
    """When a ``Verification`` record carries an ``evidence_id`` that
    matches the finding's ``evidence_refs``, the orchestrator must
    attach the verification_id to the finding.

    We provide:

    - one Verification on the primary bidder side that links to
      ``ev-primary``
    - one Verification on the corpus bidder side that links to
      ``ev-other``

    Both should be attached to the resulting finding.
    """
    raw_text = "Verification ref matching test."
    file_hash = "sha256:" + "r" * 62
    metadata = {
        "doc1": {
            "document_type": "PDF",
            "evidence_id": "ev-primary",
            "ocr_confidence": 0.95,
            "document_type_confidence": 0.9,
            "issuer": "Test Issuer",
            "authorization_number": "AUTH-VRF",
            "issue_date": date(2024, 3, 1),
            "valid_until": date(2025, 3, 1),
            "bidder_name": "Bidder A",
            "territory": "Territory X",
        },
        "doc2": {
            "document_type": "PDF",
            "evidence_id": "ev-other",
            "ocr_confidence": 0.95,
            "document_type_confidence": 0.9,
            "issuer": "Test Issuer",
            "authorization_number": "AUTH-VRF",
            "issue_date": date(2024, 3, 1),
            "valid_until": date(2025, 3, 1),
            "bidder_name": "Bidder B",
            "territory": "Territory X",
        },
    }
    artifact_store = InMemoryDocumentArtifactStore(
        raw_texts={"doc1": raw_text, "doc2": raw_text},
        file_hashes={"doc1": file_hash, "doc2": file_hash},
        metadata={k: _make_meta(v) for k, v in metadata.items()},
    )
    engine = VerificationEngine(artifact_store=artifact_store)

    ev1 = make_evidence(
        evidence_id="ev-primary",
        bidder_id="bidder-1",
        document_id="doc1",
        document_type="PDF",
    )
    ev2 = make_evidence(
        evidence_id="ev-other",
        bidder_id="bidder-2",
        document_id="doc2",
        document_type="PDF",
    )

    ver_primary = make_verification_record(
        verification_id="ver-primary",
        bidder_id="bidder-1",
    )
    # Verification is a frozen model; attach evidence_id via model_copy.
    ver_primary = ver_primary.model_copy(update={"evidence_id": "ev-primary"})

    ver_other = make_verification_record(
        verification_id="ver-other",
        bidder_id="bidder-2",
    )
    ver_other = ver_other.model_copy(update={"evidence_id": "ev-other"})

    input_data = VerificationInput(
        bidder_id="bidder-1",
        evidence=[ev1],
        compliance_results=[],
        identity_findings=[],
        verification_records=[ver_primary],
        bidder_corpus=[
            BidderSummary(
                bidder_id="bidder-2",
                evidence=[ev2],
                compliance_results=[],
                identity_findings=[],
                verification_records=[ver_other],
            )
        ],
    )

    result: VerificationResult = engine.run(input_data)

    assert len(result.findings) == 1
    finding = result.findings[0]
    # Both Verification records should be attached to the finding in
    # first-encountered order (left first, then right).
    assert set(finding.verification_refs) == {"ver-primary", "ver-other"}
    assert len(finding.verification_refs) == 2


def test_verification_refs_remain_empty_when_evidence_id_does_not_match() -> None:
    """If a Verification record's ``evidence_id`` does not match any
    evidence_ref on the finding, the finding's ``verification_refs``
    must stay empty.
    """
    raw_text = "Verification ref mismatch test."
    file_hash = "sha256:" + "s" * 62
    metadata = {
        "doc1": {
            "document_type": "PDF",
            "evidence_id": "ev-primary",
            "ocr_confidence": 0.95,
            "document_type_confidence": 0.9,
            "issuer": "Test Issuer",
            "authorization_number": "AUTH-NONE",
            "issue_date": date(2024, 4, 1),
            "valid_until": date(2025, 4, 1),
            "bidder_name": "Bidder A",
            "territory": "Territory X",
        },
        "doc2": {
            "document_type": "PDF",
            "evidence_id": "ev-other",
            "ocr_confidence": 0.95,
            "document_type_confidence": 0.9,
            "issuer": "Test Issuer",
            "authorization_number": "AUTH-NONE",
            "issue_date": date(2024, 4, 1),
            "valid_until": date(2025, 4, 1),
            "bidder_name": "Bidder B",
            "territory": "Territory X",
        },
    }
    artifact_store = InMemoryDocumentArtifactStore(
        raw_texts={"doc1": raw_text, "doc2": raw_text},
        file_hashes={"doc1": file_hash, "doc2": file_hash},
        metadata={k: _make_meta(v) for k, v in metadata.items()},
    )
    engine = VerificationEngine(artifact_store=artifact_store)

    ev1 = make_evidence(
        evidence_id="ev-primary",
        bidder_id="bidder-1",
        document_id="doc1",
        document_type="PDF",
    )
    ev2 = make_evidence(
        evidence_id="ev-other",
        bidder_id="bidder-2",
        document_id="doc2",
        document_type="PDF",
    )

    # Verification records exist, but their evidence_id does not match
    # any evidence_ref that the detector will emit.
    ver_unrelated_1 = make_verification_record(
        verification_id="ver-unrelated-1",
        bidder_id="bidder-1",
    )
    ver_unrelated_1 = ver_unrelated_1.model_copy(
        update={"evidence_id": "ev-not-in-finding"}
    )

    ver_unrelated_2 = make_verification_record(
        verification_id="ver-unrelated-2",
        bidder_id="bidder-2",
    )
    ver_unrelated_2 = ver_unrelated_2.model_copy(
        update={"evidence_id": "ev-also-not-in-finding"}
    )

    input_data = VerificationInput(
        bidder_id="bidder-1",
        evidence=[ev1],
        compliance_results=[],
        identity_findings=[],
        verification_records=[ver_unrelated_1],
        bidder_corpus=[
            BidderSummary(
                bidder_id="bidder-2",
                evidence=[ev2],
                compliance_results=[],
                identity_findings=[],
                verification_records=[ver_unrelated_2],
            )
        ],
    )

    result: VerificationResult = engine.run(input_data)

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.verification_refs == []


def test_primary_bidder_in_own_corpus_is_ignored() -> None:
    """If the primary bidder's ID accidentally also appears inside
    ``bidder_corpus``, the orchestrator must skip those pairs to avoid
    self-comparison.
    """
    raw_text = "Self-comparison guard test."
    file_hash = "sha256:" + "t" * 62
    metadata = {
        "doc1": {
            "document_type": "PDF",
            "evidence_id": "ev-primary",
            "ocr_confidence": 0.95,
            "document_type_confidence": 0.9,
            "issuer": "Test Issuer",
            "authorization_number": "AUTH-SELF",
            "issue_date": date(2024, 5, 1),
            "valid_until": date(2025, 5, 1),
            "bidder_name": "Bidder A",
            "territory": "Territory X",
        }
    }
    artifact_store = InMemoryDocumentArtifactStore(
        raw_texts={"doc1": raw_text},
        file_hashes={"doc1": file_hash},
        metadata={k: _make_meta(v) for k, v in metadata.items()},
    )
    engine = VerificationEngine(artifact_store=artifact_store)

    ev_primary = make_evidence(
        evidence_id="ev-primary",
        bidder_id="bidder-1",
        document_id="doc1",
        document_type="PDF",
    )
    # Same bidder, same document - but listed in the corpus.
    ev_self = make_evidence(
        evidence_id="ev-self",
        bidder_id="bidder-1",
        document_id="doc1",
        document_type="PDF",
    )

    input_data = VerificationInput(
        bidder_id="bidder-1",
        evidence=[ev_primary],
        compliance_results=[],
        identity_findings=[],
        bidder_corpus=[
            BidderSummary(
                bidder_id="bidder-1",  # <-- primary bidder in its own corpus
                evidence=[ev_self],
                compliance_results=[],
                identity_findings=[],
                verification_records=[],
            )
        ],
    )

    result: VerificationResult = engine.run(input_data)
    # No self-comparison should produce a finding.
    assert result.findings == []


def test_empty_artifact_store_returns_empty_findings() -> None:
    """If the artifact store has no data at all, the engine must
    return an empty findings list without raising.
    """
    artifact_store = InMemoryDocumentArtifactStore()
    engine = VerificationEngine(artifact_store=artifact_store)

    ev1 = make_evidence(
        evidence_id="ev1",
        bidder_id="bidder-1",
        document_id="doc1",
        document_type="PDF",
    )
    ev2 = make_evidence(
        evidence_id="ev2",
        bidder_id="bidder-2",
        document_id="doc2",
        document_type="PDF",
    )

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

    result: VerificationResult = engine.run(input_data)
    assert result.findings == []

