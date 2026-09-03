"""Deterministic unit tests for the cross-bidder document anomaly detector.

Tests cover all 17 required scenarios from the specification.
No network, LLM, embeddings, or random values used.
"""

import pytest
from datetime import date

from ai_verification.cross_bidder import (
    NORMALIZATION_VERSION,
    detect_cross_bidder_anomalies,
    compare_two_documents,
)
from ai_verification.cross_bidder.document_artifact_store import (
    DocumentArtifactStore,
    DocumentMeta,
    InMemoryDocumentArtifactStore,
)
from ai_verification.cross_bidder.detector import _candidate_blocking
from compliance_engine.flags import FLAG_REGISTRY, get_flag_definition


# ---------------------------------------------------------------------------
# Helper: make an InMemoryArtifactStore with full control
# ---------------------------------------------------------------------------

def make_store(
    *,
    left_raw=None,
    right_raw=None,
    left_hash=None,
    right_hash=None,
    left_meta=None,
    right_meta=None,
):
    """Create an InMemoryDocumentArtifactStore with optional pre-set values."""
    raw_texts = {}
    file_hashes = {}
    metadata = {}

    if left_raw is not None:
        raw_texts["doc-left"] = left_raw
    if right_raw is not None:
        raw_texts["doc-right"] = right_raw
    if left_hash is not None:
        file_hashes["doc-left"] = left_hash
    if right_hash is not None:
        file_hashes["doc-right"] = right_hash

    if left_meta is not None:
        metadata["doc-left"] = left_meta
    if right_meta is not None:
        metadata["doc-right"] = right_meta

    return InMemoryDocumentArtifactStore(
        raw_texts=raw_texts,
        file_hashes=file_hashes,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Direct DocumentMeta construction helpers (per-test)
# ---------------------------------------------------------------------------

def make_left_meta(**overrides):
    """Create a left-document DocumentMeta, default bidder_name='bidder-A'."""
    default = DocumentMeta(
        document_type="OEM_AUTH",
        issuer="ACME",
        authorization_number="AUTH-123",
        issue_date=date(2026, 1, 10),
        valid_until=date(2027, 1, 10),
        bidder_name="bidder-A",
        territory="India",
        ocr_confidence=0.95,
        document_type_confidence=0.99,
    )
    # Apply overrides
    for k, v in overrides.items():
        setattr(default, k, v)
    return default


def make_right_meta(**overrides):
    """Create a right-document DocumentMeta, default bidder_name='bidder-B'."""
    default = DocumentMeta(
        document_type="OEM_AUTH",
        issuer="ACME",
        authorization_number="AUTH-123",
        issue_date=date(2026, 1, 10),
        valid_until=date(2027, 1, 10),
        bidder_name="bidder-B",
        territory="India",
        ocr_confidence=0.95,
        document_type_confidence=0.99,
    )
    for k, v in overrides.items():
        setattr(default, k, v)
    return default


# ===========================================================================
# 1. exact byte duplicate -> REUSED
# ===========================================================================

def test_exact_byte_duplicate_reused():
    """Same file hash -> CROSS_BIDDER_DOCUMENT_REUSED (REUSED)."""
    left_meta = make_left_meta(evidence_id="ev-left")
    right_meta = make_right_meta(evidence_id="ev-right")

    store = make_store(
        left_raw="Exact same document content for byte comparison.",
        right_raw="Exact same document content for byte comparison.",
        left_hash="abc123",
        right_hash="abc123",
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.flag_id == "CROSS_BIDDER_DOCUMENT_REUSED"
    assert finding.confidence >= 0.70, f"Expected confidence >= 0.70, got {finding.confidence}"
    assert trace.template_gate.status.name == "MATCH"
    assert "ev-left" in finding.evidence_refs
    assert "ev-right" in finding.evidence_refs
    assert "bidder-B" in finding.related_bidder_ids
    assert trace.similarity_score == 1.0
    assert trace.left_file_hash == "abc123"
    assert trace.right_file_hash == "abc123"


# ===========================================================================
# 2. normalized-text duplicate with different file hashes -> REUSED
# ===========================================================================

def test_normalized_text_duplicate_reused():
    """Same content after normalization but different file hashes -> REUSED."""
    left_meta = make_left_meta(evidence_id="ev-left")
    right_meta = make_right_meta(evidence_id="ev-right")

    store = make_store(
        left_raw="  Hello   World!  OEM  auth  text   ",
        right_raw="hello world OEM auth text",
        left_hash="hash-left-different",
        right_hash="hash-right-different",
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.flag_id == "CROSS_BIDDER_DOCUMENT_REUSED"
    assert finding.confidence >= 0.70, f"Expected confidence >= 0.70, got {finding.confidence}"
    assert trace.template_gate.status.name == "MATCH"
    assert trace.left_norm_text_hash == trace.right_norm_text_hash
    assert "ev-left" in finding.evidence_refs
    assert "ev-right" in finding.evidence_refs


# ===========================================================================
# 3. lexical near-duplicate + matching identifiers -> NEAR_DUPLICATE
# ===========================================================================

def test_lexical_nearest_duplicate():
    """Lexical Dice >= 0.80 + matching identifiers -> NEAR_DUPLICATE."""
    left_meta = make_left_meta(evidence_id="ev-left")
    right_meta = make_right_meta(
        evidence_id="ev-right",
        authorization_number="AUTH-123",
        issue_date=date(2026, 1, 10),
    )

    store = make_store(
        left_raw="OEM authorization for ACME India manufacturing",
        right_raw="OEM authorization for ACME India mfg",
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.flag_id == "CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE"
    assert trace.similarity_score >= 0.80, f"Expected Dice >= 0.80, got {trace.similarity_score}"
    assert finding.confidence >= 0.70, f"Expected confidence >= 0.70, got {finding.confidence}"
    assert trace.template_gate.status.name == "MATCH"
    assert "bidder-B" in finding.related_bidder_ids


# ===========================================================================
# 4. legitimate shared template + different identifiers -> no finding
# ===========================================================================

def test_legitimate_shared_template_no_finding():
    """Same boilerplate but different identifiers -> no finding."""
    left_meta = make_left_meta(evidence_id="ev-left")
    right_meta = make_right_meta(
        evidence_id="ev-right",
        authorization_number="AUTH-456",
        issue_date=date(2025, 6, 1),
    )

    store = make_store(
        left_raw="OEM authorization boilerplate text with standard terms",
        right_raw="OEM authorization boilerple text with different terms",
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert len(findings) == 0, f"Expected no findings, got {len(findings)}: {findings}"
    assert trace is not None


# ===========================================================================
# 5. different document types -> no finding
# ===========================================================================

def test_different_document_types_no_finding():
    """Different document_types are blocked by candidate blocking."""
    left_meta = make_left_meta(document_type="OEM_AUTH")
    right_meta = make_right_meta(document_type="GST")

    store = make_store(
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert len(findings) == 0, f"Expected no findings for different doc types, got {len(findings)}"
    assert trace.similarity_score == 0.0


# ===========================================================================
# 6. same bidder -> no finding
# ===========================================================================

def test_same_bidder_no_finding():
    """Comparing documents from the same bidder produces no finding."""
    left_meta = make_left_meta(bidder_name="bidder-A")
    right_meta = make_right_meta(bidder_name="bidder-A")

    store = make_store(
        left_raw="Some content",
        right_raw="Some other content",
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-A",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert len(findings) == 0, f"Expected no findings for same bidder, got {len(findings)}"
    assert trace.similarity_score == 0.0


# ===========================================================================
# 7. UNKNOWN identifier state handled correctly
# ===========================================================================

def test_unknown_identifier_state():
    """Missing identifiers should result in UNKNOWN template gate, not MISMATCH."""
    left_meta = make_left_meta(evidence_id="ev-left")
    # Remove identifier info by overriding to None-like state
    left_meta.issuer = None
    left_meta.authorization_number = None
    left_meta.issue_date = None

    right_meta = make_right_meta(evidence_id="ev-right")

    store = make_store(
        left_raw="Some content",
        right_raw="Some similar content",
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert len(findings) == 0, f"Expected no findings for UNKNOWN identifiers, got {len(findings)}"
    assert trace.template_gate.status.name == "UNKNOWN"


# ===========================================================================
# 8. short text -> lexical stage skipped
# ===========================================================================

def test_short_text_lexical_skipped():
    """Very short documents should skip lexical comparison."""
    left_meta = make_left_meta(evidence_id="ev-left")
    right_meta = make_right_meta(evidence_id="ev-right", bidder_name="bidder-B")

    store = make_store(
        left_raw="AB",
        right_raw="CD",
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert len(findings) == 0, f"Expected no findings for short text, got {len(findings)}"


# ===========================================================================
# 9. poor OCR reduces confidence
# ===========================================================================

def test_poor_ocr_reduces_confidence():
    """Low OCR confidence should reduce the final finding confidence."""
    left_meta = make_left_meta(ocr_confidence=0.4, evidence_id="ev-left")
    right_meta = make_right_meta(ocr_confidence=0.4, evidence_id="ev-right", bidder_name="bidder-B")

    store = make_store(
        left_raw="Same content here",
        right_raw="Same content here",
        left_hash="abc123",
        right_hash="abc123",
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert len(findings) == 1
    assert findings[0].flag_id == "CROSS_BIDDER_DOCUMENT_REUSED"
    # Confidence should be lower due to poor OCR
    assert findings[0].confidence < 1.0, f"Expected reduced confidence with poor OCR, got {findings[0].confidence}"


# ===========================================================================
# 10. unrelated documents -> no finding
# ===========================================================================

def test_unrelated_documents_no_finding():
    """Completely unrelated documents should produce no finding."""
    left_meta = make_left_meta(evidence_id="ev-left")
    right_meta = make_right_meta(evidence_id="ev-right", bidder_name="bidder-B")

    store = make_store(
        left_raw=" completely different content about something ",
        right_raw="totally unrelated document about another thing",
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert len(findings) == 0, f"Expected no findings for unrelated docs, got {len(findings)}"


# ===========================================================================
# 11. duplicate pair emitted once
# ===========================================================================

def test_duplicate_pair_emitted_once():
    """A document pair should produce at most one finding."""
    left_meta = make_left_meta(evidence_id="ev-left")
    right_meta = make_right_meta(evidence_id="ev-right", bidder_name="bidder-B")

    store = make_store(
        left_raw="Duplicate content",
        right_raw="Duplicate content",
        left_hash="abc123",
        right_hash="abc123",
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert len(findings) == 1, f"Expected exactly 1 finding, got {len(findings)}"


# ===========================================================================
# 12. evidence references contain both sides
# ===========================================================================

def test_evidence_references_both_sides():
    """Finding evidence_refs should contain both document's evidence IDs."""
    left_meta = make_left_meta(evidence_id="ev-doc-left")
    right_meta = make_right_meta(evidence_id="ev-doc-right", bidder_name="bidder-B")

    store = make_store(
        left_raw="Content A",
        right_raw="Content B",
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert len(findings) == 1
    eff = findings[0].evidence_refs
    assert "ev-doc-left" in eff, f"ev-doc-left missing from {eff}"
    assert "ev-doc-right" in eff, f"ev-doc-right missing from {eff}"


# ===========================================================================
# 13. related bidder IDs correct
# ===========================================================================

def test_related_bidder_ids_correct():
    """related_bidder_ids should contain the counterpart bidder ID."""
    left_meta = make_left_meta(evidence_id="ev-left")
    right_meta = make_right_meta(evidence_id="ev-right", bidder_name="bidder-B")

    store = make_store(
        left_raw="Content",
        right_raw="Content",
        left_hash="abc123",
        right_hash="abc123",
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert len(findings) == 1
    assert "bidder-B" in findings[0].related_bidder_ids
    assert findings[0].bidder_id == "bidder-A"


# ===========================================================================
# 14. SimilarityTrace populated
# ===========================================================================

def test_similarity_trace_populated():
    """SimilarityTrace should be fully populated with all fields."""
    left_meta = make_left_meta(evidence_id="ev-left")
    right_meta = make_right_meta(evidence_id="ev-right", bidder_name="bidder-B")

    store = make_store(
        left_raw="Content for trace test",
        right_raw="Content for trace test",
        left_hash="hash-left",
        right_hash="hash-right",
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert trace is not None
    assert trace.layer is not None
    assert trace.left_document_id == "doc-left"
    assert trace.right_document_id == "doc-right"
    assert trace.left_bidder_id == "bidder-A"
    assert trace.right_bidder_id == "bidder-B"
    assert trace.doc_type == "OEM_AUTH"
    assert trace.normalization_version == NORMALIZATION_VERSION
    assert trace.similarity_score == 1.0
    assert trace.threshold == 0.80
    assert trace.embedding_model is None
    assert trace.corroboration is not None
    assert trace.quality is not None
    assert trace.template_gate is not None


# ===========================================================================
# 15. normalization version recorded
# ===========================================================================

def test_normalization_version_recorded():
    """The normalization version should be recorded in the trace."""
    left_meta = make_left_meta(evidence_id="ev-left")
    right_meta = make_right_meta(evidence_id="ev-right", bidder_name="bidder-B")

    store = make_store(
        left_raw="Some content",
        right_raw="Some content",
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert trace is not None
    assert trace.normalization_version == NORMALIZATION_VERSION
    assert NORMALIZATION_VERSION == "v1"


# ===========================================================================
# 16. missing raw text handled safely
# ===========================================================================

def test_missing_raw_text_handled_safely():
    """Missing raw text should not crash the detector."""
    left_meta = make_left_meta(evidence_id="ev-left")
    right_meta = make_right_meta(evidence_id="ev-right", bidder_name="bidder-B")

    store = make_store(
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert trace is not None


# ===========================================================================
# 17. missing file hash handled safely
# ===========================================================================

def test_missing_file_hash_handled_safely():
    """Missing file hash should not crash the detector."""
    left_meta = make_left_meta(evidence_id="ev-left")
    right_meta = make_right_meta(evidence_id="ev-right", bidder_name="bidder-B")

    store = make_store(
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id="bidder-A",
        right_bidder_id="bidder-B",
        left_document_id="doc-left",
        right_document_id="doc-right",
        artifact_store=store,
    )

    assert trace is not None


# ===========================================================================
# Additional: compare_two_documents wrapper test
# ===========================================================================

def test_compare_two_documents_wrapper():
    """Test the compare_two_documents convenience wrapper."""
    left_meta = make_left_meta(evidence_id="ev-left")
    right_meta = make_right_meta(evidence_id="ev-right", bidder_name="bidder-B")

    store = make_store(
        left_raw="Same content for wrapper test",
        right_raw="Same content for wrapper test",
        left_hash="abc123",
        right_hash="abc123",
        left_meta=left_meta,
        right_meta=right_meta,
    )

    findings, trace = compare_two_documents(
        bidder_id="bidder-A",
        other_bidder_id="bidder-B",
        left_doc_id="doc-left",
        right_doc_id="doc-right",
        artifact_store=store,
    )

    assert len(findings) == 1
    assert findings[0].flag_id == "CROSS_BIDDER_DOCUMENT_REUSED"


# ===========================================================================
# Edge case: blocking with same issuer preference
# ===========================================================================

def test_same_issuer_preference():
    """Same issuer should be preferred as candidate but not hard-block different issuers."""
    left_meta = make_left_meta(issuer="ACME")
    right_meta = make_right_meta(issuer="ACME")

    result = _candidate_blocking(left_meta, right_meta)
    assert result is True, f"Expected True (not blocked), got {result}"

    # Different issuers should also not be blocked
    left_meta2 = make_left_meta(issuer="X")
    right_meta2 = make_right_meta(issuer="Y")
    result2 = _candidate_blocking(left_meta2, right_meta2)
    assert result2 is True


# ===========================================================================
# Edge case: verification that existing flags still work
# ===========================================================================

def test_existing_flags_still_valid():
    """Verify that the existing registry flags are unaffected."""
    assert len(FLAG_REGISTRY) > 0
    definition = get_flag_definition("GSTIN_MISSING")
    assert definition.flag_id == "GSTIN_MISSING"
    assert definition.severity.name == "HIGH"
    assert definition.capability == "GST / GSTN"
