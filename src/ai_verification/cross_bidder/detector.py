"""Cross-bidder document anomaly detector.

Implements the approved architecture:

1. Candidate selection (deterministic blocking)
2. Document comparison (byte hash, normalized hash, lexical Dice)
3. Metadata corroboration
4. Template gate
5. Confidence calculation
6. Finding emission with canonical flags
7. Similarity trace population
8. Deduplication

No LLM, no embeddings, no fraud/eligibility decisions.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from ai_verification.cross_bidder.trace import (
    CorroborationSignals,
    QualitySignals,
    SimilarityLayer,
    SimilarityTrace,
    TemplateGate,
    TemplateGateStatus,
)

from compliance_engine.flags import get_flag_definition, FLAG_REGISTRY

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

from .normalization import NORMALIZATION_VERSION, normalize_text, normalized_text_hash

# ---------------------------------------------------------------------------
# Candidate blocking
# ---------------------------------------------------------------------------


def _candidate_blocking(left_meta, right_meta):
    """Determine whether two document metadata entries should be compared."""
    if getattr(left_meta, "bidder_name", None) is not None and getattr(
        right_meta, "bidder_name", None
    ) is not None:
        if left_meta.bidder_name == right_meta.bidder_name:
            return False
    if left_meta.document_type != right_meta.document_type:
        return False
    return True


# ---------------------------------------------------------------------------
# Document comparison stages
# ---------------------------------------------------------------------------

def _byte_hash_match(left_meta, right_meta, artifact_store, left_doc_id, right_doc_id):
    """Check exact file-hash match. Returns 1.0 or None."""
    left_hash = artifact_store.get_file_hash(left_doc_id)
    right_hash = artifact_store.get_file_hash(right_doc_id)
    if left_hash is not None and right_hash is not None and left_hash == right_hash:
        return 1.0
    return None


def _normalized_hash_match(left_meta, right_meta, artifact_store, left_doc_id, right_doc_id):
    """Check normalized-text hash match. Returns 1.0 or None."""
    left_raw = artifact_store.get_raw_text(left_doc_id)
    right_raw = artifact_store.get_raw_text(right_doc_id)
    if left_raw is None or right_raw is None:
        return None
    left_hash = normalized_text_hash(left_raw)
    right_hash = normalized_text_hash(right_raw)
    if left_hash == right_hash:
        return 1.0
    return None


def _lexical_dice(left_meta, right_meta, artifact_store, left_doc_id, right_doc_id):
    """Calculate character 4-gram Sørensen-Dice similarity. Returns dice or None."""
    left_raw = artifact_store.get_raw_text(left_doc_id)
    right_raw = artifact_store.get_raw_text(right_doc_id)
    if left_raw is None or right_raw is None:
        return None
    left_norm = normalize_text(left_raw)
    right_norm = normalize_text(right_raw)
    if not left_norm or not right_norm:
        return None
    left_grams = set(left_norm[i:i+4] for i in range(max(0, len(left_norm)-3)))
    right_grams = set(right_norm[i:i+4] for i in range(max(0, len(right_norm)-3)))
    if not left_grams or not right_grams:
        return None
    intersection = len(left_grams & right_grams)
    union = len(left_grams | right_grams)
    if union == 0:
        return None
    return 2.0 * intersection / (len(left_grams) + len(right_grams))


# ---------------------------------------------------------------------------
# Metadata corroboration
# ---------------------------------------------------------------------------

def _calculate_corroboration(left_meta, right_meta):
    """Calculate corroboration signals from available metadata."""
    same_issuer = None
    same_authorization_number = None
    same_issue_date = None
    validity_overlap = None

    left_issuer = getattr(left_meta, "issuer", None)
    right_issuer = getattr(right_meta, "issuer", None)
    if left_issuer is not None and right_issuer is not None:
        same_issuer = left_issuer == right_issuer

    left_auth = getattr(left_meta, "authorization_number", None)
    right_auth = getattr(right_meta, "authorization_number", None)
    if left_auth is not None and right_auth is not None:
        same_authorization_number = left_auth == right_auth

    left_date = getattr(left_meta, "issue_date", None)
    right_date = getattr(right_meta, "issue_date", None)
    if left_date is not None and right_date is not None:
        same_issue_date = left_date == right_date

    left_valid = getattr(left_meta, "valid_until", None)
    right_valid = getattr(right_meta, "valid_until", None)
    if left_valid is not None and right_valid is not None:
        left_issue = getattr(left_meta, "issue_date", None)
        right_issue = getattr(right_meta, "issue_date", None)
        if left_issue is not None and right_issue is not None:
            try:
                latest_issue = max(left_issue, right_issue)
                earliest_valid = min(left_valid, right_valid)
                validity_overlap = latest_issue <= earliest_valid
            except Exception:
                validity_overlap = None

    return CorroborationSignals(
        same_issuer=same_issuer,
        same_authorization_number=same_authorization_number,
        same_issue_date=same_issue_date,
        validity_overlap=validity_overlap,
    )


# ---------------------------------------------------------------------------
# Template gate
# ---------------------------------------------------------------------------

def _template_gate(left_meta, right_meta):
    """Determine template gate status."""
    matched_fields = []
    mismatched_fields = []
    unknown_fields = []

    left_auth = getattr(left_meta, "authorization_number", None)
    right_auth = getattr(right_meta, "authorization_number", None)
    if left_auth is not None and right_auth is not None:
        if left_auth == right_auth:
            matched_fields.append("authorization_number")
        else:
            mismatched_fields.append("authorization_number")
    else:
        unknown_fields.append("authorization_number")

    left_date = getattr(left_meta, "issue_date", None)
    right_date = getattr(right_meta, "issue_date", None)
    if left_date is not None and right_date is not None:
        if left_date == right_date:
            matched_fields.append("issue_date")
        else:
            mismatched_fields.append("issue_date")
    else:
        unknown_fields.append("issue_date")

    left_territory = getattr(left_meta, "territory", None)
    right_territory = getattr(right_meta, "territory", None)
    if left_territory is not None and right_territory is not None:
        if left_territory == right_territory:
            matched_fields.append("territory")
        else:
            mismatched_fields.append("territory")
    else:
        unknown_fields.append("territory")

    if unknown_fields and not matched_fields:
        status = TemplateGateStatus.UNKNOWN
        score = 0.0
    elif not matched_fields and mismatched_fields:
        status = TemplateGateStatus.MISMATCH
        score = 0.0
    else:
        status = TemplateGateStatus.MATCH
        known_with_info = [
            f for f in ["authorization_number", "issue_date", "territory"]
            if getattr(left_meta, f, None) is not None or getattr(right_meta, f, None) is not None
        ]
        if known_with_info:
            score = len(matched_fields) / len(known_with_info)
        else:
            score = 1.0

    return TemplateGate(status=status, score=score, matched_fields=matched_fields, mismatched_fields=mismatched_fields, unknown_fields=unknown_fields)


# ---------------------------------------------------------------------------
# Confidence calculation
# ---------------------------------------------------------------------------

def _calculate_confidence(similarity_score, corroboration, quality, template_gate):
    """Calculate final confidence per approved formula."""
    S = similarity_score

    signal_values = []
    if corroboration.same_issuer is not None:
        signal_values.append(1.0 if corroboration.same_issuer else 0.0)
    if corroboration.same_authorization_number is not None:
        signal_values.append(1.0 if corroboration.same_authorization_number else 0.0)
    if corroboration.same_issue_date is not None:
        signal_values.append(1.0 if corroboration.same_issue_date else 0.0)
    if corroboration.validity_overlap is not None:
        signal_values.append(1.0 if corroboration.validity_overlap else 0.0)

    C = sum(signal_values) / len(signal_values) if signal_values else 0.0
    Q = min(quality.ocr_confidence, quality.field_confidence)
    T = template_gate.score

    raw = 0.60 * S + 0.25 * C + 0.15 * Q
    clamped = max(0.0, min(1.0, raw))
    confidence = clamped * T
    return confidence


# ---------------------------------------------------------------------------
# Finding emission helpers
# ---------------------------------------------------------------------------

def _make_explanation_reused(trace, corroboration, quality):
    """Build explanation string for REUSED finding."""
    parts = []
    if trace.template_gate.status.value == "MATCH":
        parts.append("Template gate matches; ")
    if trace.layer.value == "EXACT":
        parts.append("Document exact byte reuse detected across bidders. ")
    elif trace.layer.value == "NORMALIZED":
        parts.append("Document normalized-text reuse detected across bidders. ")
    if trace.left_file_hash:
        parts.append(f"Left file hash: {trace.left_file_hash}; ")
    if trace.right_file_hash:
        parts.append(f"Right file hash: {trace.right_file_hash}; ")
    parts.append(
        f"Normalized text hashes: {trace.left_norm_text_hash} / {trace.right_norm_text_hash}; "
    )
    parts.append(
        f"Similarity score: {trace.similarity_score:.2f} (threshold: {trace.threshold:.2f}); "
    )
    parts.append(
        f"Corroboration: same_issuer={corroboration.same_issuer}, same_authorization_number={corroboration.same_authorization_number}, same_issue_date={corroboration.same_issue_date}, validity_overlap={corroboration.validity_overlap}; "
    )
    parts.append(
        f"Quality: ocr_confidence={quality.ocr_confidence}, field_confidence={quality.field_confidence}; "
    )
    parts.append(
        f"Template gate: {trace.template_gate.status} (score={trace.template_gate.score:.2f})"
    )
    return "".join(parts)


def _make_explanation_near_duplicate(trace, corroboration, quality):
    """Build explanation string for NEAR_DUPLICATE finding."""
    parts = []
    parts.append(
        f"Lexical near-duplicate detected (Dice coefficient: {trace.similarity_score:.2f} >= 0.80); "
    )
    parts.append("Document content is similar but not identical across bidders. ")
    if trace.left_file_hash:
        parts.append(f"Left file hash: {trace.left_file_hash}; ")
    if trace.right_file_hash:
        parts.append(f"Right file hash: {trace.right_file_hash}; ")
    parts.append(
        f"Normalized text hashes: {trace.left_norm_text_hash} / {trace.right_norm_text_hash}; "
    )
    parts.append(
        f"Similarity score: {trace.similarity_score:.2f} (threshold: {trace.threshold:.2f}); "
    )
    parts.append(
        f"Corroboration: same_issuer={corroboration.same_issuer}, same_authorization_number={corroboration.same_authorization_number}, same_issue_date={corroboration.same_issue_date}, validity_overlap={corroboration.validity_overlap}; "
    )
    parts.append(
        f"Quality: ocr_confidence={quality.ocr_confidence}, field_confidence={quality.field_confidence}; "
    )
    parts.append(
        f"Template gate: {trace.template_gate.status} (score={trace.template_gate.score:.2f})"
    )
    return "".join(parts)


# ---------------------------------------------------------------------------
# Finding emission
# ---------------------------------------------------------------------------

def _emit_reused_finding(left_meta, right_meta, artifact_store, trace, flag_id, corroboration, quality, left_document_id, right_document_id, left_bidder_id, right_bidder_id):
    """Emit a REUSED finding."""
    from ai_verification.models.contracts import VerificationFinding

    try:
        flag_def = get_flag_definition(flag_id)
        severity = flag_def.severity
    except Exception:
        severity = "HIGH"

    evidence_refs = []
    if hasattr(left_meta, "evidence_id") and left_meta.evidence_id:
        evidence_refs.append(left_meta.evidence_id)
    if hasattr(right_meta, "evidence_id") and right_meta.evidence_id:
        evidence_refs.append(right_meta.evidence_id)

    explanation = _make_explanation_reused(trace, corroboration, quality)

    finding = VerificationFinding(
        finding_id=f"cross-bidder-{flag_id}-{left_document_id}-{right_document_id}",
        bidder_id=left_bidder_id,
        flag_id=flag_id,
        severity=severity,
        confidence=trace.confidence,
        explanation=explanation,
        evidence_refs=evidence_refs,
        verification_refs=[],
        related_bidder_ids=[right_bidder_id] if left_bidder_id != right_bidder_id else [],
        trace=trace,
    )
    return finding


def _emit_near_duplicate_finding(left_meta, right_meta, artifact_store, trace, flag_id, corroboration, quality, left_document_id, right_document_id, left_bidder_id, right_bidder_id):
    """Emit a NEAR_DUPLICATE finding."""
    from ai_verification.models.contracts import VerificationFinding

    try:
        flag_def = get_flag_definition(flag_id)
        severity = flag_def.severity
    except Exception:
        severity = "MEDIUM"

    evidence_refs = []
    if hasattr(left_meta, "evidence_id") and left_meta.evidence_id:
        evidence_refs.append(left_meta.evidence_id)
    if hasattr(right_meta, "evidence_id") and right_meta.evidence_id:
        evidence_refs.append(right_meta.evidence_id)

    explanation = _make_explanation_near_duplicate(trace, corroboration, quality)

    finding = VerificationFinding(
        finding_id=f"cross-bidder-{flag_id}-{left_document_id}-{right_document_id}",
        bidder_id=left_bidder_id,
        flag_id=flag_id,
        severity=severity,
        confidence=trace.confidence,
        explanation=explanation,
        evidence_refs=evidence_refs,
        verification_refs=[],
        related_bidder_ids=[right_bidder_id] if left_bidder_id != right_bidder_id else [],
        trace=trace,
    )
    return finding


# ---------------------------------------------------------------------------
# Main detection pipeline
# ---------------------------------------------------------------------------

def detect_cross_bidder_anomalies(
    left_bidder_id, right_bidder_id, left_document_id, right_document_id, artifact_store,
    left_meta=None, right_meta=None,
):
    """Detect cross-bidder document anomalies between two documents.

    Returns (findings, trace). Findings is a list of VerificationFinding objects.
    """
    # Load metadata if not provided
    if left_meta is None:
        left_meta = artifact_store.get_metadata(left_document_id) if hasattr(artifact_store, "get_metadata") else None
    if right_meta is None:
        right_meta = artifact_store.get_metadata(right_document_id) if hasattr(artifact_store, "get_metadata") else None

    if left_meta is None or right_meta is None:
        from ai_verification.cross_bidder.document_artifact_store import DocumentMeta
        left_meta = left_meta or DocumentMeta(document_type="UNKNOWN", ocr_confidence=1.0, document_type_confidence=1.0)
        right_meta = right_meta or DocumentMeta(document_type="UNKNOWN", ocr_confidence=1.0, document_type_confidence=1.0)

    # Candidate blocking
    if not _candidate_blocking(left_meta, right_meta):
        return [], _make_empty_trace(left_document_id, right_document_id, left_bidder_id, right_bidder_id)

    # Byte hash comparison
    byte_hash_result = _byte_hash_match(left_meta, right_meta, artifact_store, left_document_id, right_document_id)

    # Normalized hash comparison
    norm_hash_result = _normalized_hash_match(left_meta, right_meta, artifact_store, left_document_id, right_document_id)

    # Lexical similarity
    dice_score = _lexical_dice(left_meta, right_meta, artifact_store, left_document_id, right_document_id)

    # Determine winning layer and similarity score
    winning_layer = None
    similarity_score = 0.0
    threshold = 0.80
    flag_id = None

    if byte_hash_result == 1.0:
        winning_layer = "EXACT"
        similarity_score = 1.0
        flag_id = "CROSS_BIDDER_DOCUMENT_REUSED"
    elif norm_hash_result == 1.0:
        winning_layer = "NORMALIZED"
        similarity_score = 1.0
        flag_id = "CROSS_BIDDER_DOCUMENT_REUSED"
    elif dice_score is not None and dice_score >= 0.80:
        print(f"DEBUG: dice_score={dice_score}, entering LEXICAL branch")
        winning_layer = "LEXICAL"
        similarity_score = dice_score
        flag_id = "CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE"
    else:
        print(f"DEBUG: dice_score={dice_score}, byte_hash={byte_hash_result}, norm_hash={norm_hash_result}, entering ELSE branch")
        return [], _make_empty_trace(left_document_id, right_document_id, left_bidder_id, right_bidder_id)

    # Metadata corroboration
    corroboration = _calculate_corroboration(left_meta, right_meta)

    # Template gate
    tg = _template_gate(left_meta, right_meta)

    # Quality signals
    quality = QualitySignals(
        ocr_confidence=(
            (getattr(left_meta, "ocr_confidence", 1.0) + getattr(right_meta, "ocr_confidence", 1.0)) / 2
        ),
        field_confidence=(
            (getattr(left_meta, "document_type_confidence", 1.0) + getattr(right_meta, "document_type_confidence", 1.0)) / 2
        ),
        quality_score=1.0,
    )

    # Confidence calculation
    confidence = _calculate_confidence(similarity_score, corroboration, quality, tg)

    # Enforce minimum confidence for NEAR_DUPLICATE
    if flag_id == "CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE" and confidence < 0.70:
        return [], _make_empty_trace(left_document_id, right_document_id, left_bidder_id, right_bidder_id)

    # Find emission
    primary_bidder = left_bidder_id
    counterpart_bidder = right_bidder_id

    evidence_refs = []
    if hasattr(left_meta, "evidence_id") and left_meta.evidence_id:
        evidence_refs.append(left_meta.evidence_id)
    if hasattr(right_meta, "evidence_id") and right_meta.evidence_id:
        evidence_refs.append(right_meta.evidence_id)

    # Build SimilarityTrace
    left_raw = artifact_store.get_raw_text(left_document_id) if hasattr(artifact_store, "get_raw_text") else ""
    right_raw = artifact_store.get_raw_text(right_document_id) if hasattr(artifact_store, "get_raw_text") else ""

    trace = SimilarityTrace(
        layer=SimilarityLayer(winning_layer),
        left_document_id=left_document_id,
        right_document_id=right_document_id,
        left_bidder_id=left_bidder_id,
        right_bidder_id=right_bidder_id,
        doc_type=getattr(left_meta, "document_type", "UNKNOWN"),
        left_file_hash=artifact_store.get_file_hash(left_document_id) if hasattr(artifact_store, "get_file_hash") else None,
        right_file_hash=artifact_store.get_file_hash(right_document_id) if hasattr(artifact_store, "get_file_hash") else None,
        left_norm_text_hash=normalized_text_hash(left_raw),
        right_norm_text_hash=normalized_text_hash(right_raw),

        normalization_version=NORMALIZATION_VERSION,
        similarity_score=similarity_score,
        threshold=threshold,
        corroboration=corroboration,
        quality=quality,
        template_gate=tg,
        confidence=confidence,
        embedding_model=None,
    )

    # Emit finding
    findings = []

    if flag_id == "CROSS_BIDDER_DOCUMENT_REUSED":
        if tg.status.value == "MATCH" and confidence >= 0.70:
            if primary_bidder != counterpart_bidder:
                finding = _emit_reused_finding(left_meta, right_meta, artifact_store, trace, flag_id, corroboration, quality, left_document_id, right_document_id, left_bidder_id, right_bidder_id)
                findings.append(finding)
    elif flag_id == "CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE":
        if tg.status.value == "MATCH" and confidence >= 0.70:
            if primary_bidder != counterpart_bidder:
                finding = _emit_near_duplicate_finding(left_meta, right_meta, artifact_store, trace, flag_id, corroboration, quality, left_document_id, right_document_id, left_bidder_id, right_bidder_id)
                findings.append(finding)

    return findings, trace


def _make_empty_trace(left_document_id, right_document_id, left_bidder_id, right_bidder_id):
    """Create an empty trace when no comparison is done."""
    from ai_verification.cross_bidder.trace import SimilarityTrace, CorroborationSignals, QualitySignals, TemplateGate, TemplateGateStatus

    return SimilarityTrace(
        layer=SimilarityLayer.UNKNOWN,
        left_document_id=left_document_id,
        right_document_id=right_document_id,
        left_bidder_id=left_bidder_id,
        right_bidder_id=right_bidder_id,
        doc_type="UNKNOWN",
        left_file_hash=None,
        right_file_hash=None,
        left_norm_text_hash=None,
        right_norm_text_hash=None,

        normalization_version=NORMALIZATION_VERSION,
        similarity_score=0.0,
        threshold=0.80,
        corroboration=CorroborationSignals(
            same_issuer=None, same_authorization_number=None, same_issue_date=None, validity_overlap=None
        ),
        quality=QualitySignals(ocr_confidence=1.0, field_confidence=1.0, quality_score=1.0),
        template_gate=TemplateGate(status=TemplateGateStatus.UNKNOWN, score=0.0, matched_fields=[], mismatched_fields=[], unknown_fields=["authorization_number", "issue_date", "bidder_name", "territory"]),
        confidence=0.0,
        embedding_model=None,

    )


# ---------------------------------------------------------------------------
# Deduplication helper
# ---------------------------------------------------------------------------

def _pair_identity(doc_type, left_doc_id, right_doc_id):
    """Canonical pair identity for deduplication."""
    sorted_ids = sorted([left_doc_id, right_doc_id])
    return f"{doc_type}:{sorted_ids[0]}:{sorted_ids[1]}"


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def compare_two_documents(bidder_id, other_bidder_id, left_doc_id, right_doc_id, artifact_store):
    """Compare two documents from potentially different bidders."""
    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id=bidder_id,
        right_bidder_id=other_bidder_id,
        left_document_id=left_doc_id,
        right_document_id=right_doc_id,
        artifact_store=artifact_store,
    )
    return findings, trace
