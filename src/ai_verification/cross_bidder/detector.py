"""Cross-bidder document anomaly detector.

Implements the approved architecture:

1. Candidate selection (deterministic blocking)
2. Document comparison (byte hash, normalized hash, lexical Dice, semantic cosine)
3. Metadata corroboration
4. Template gate
5. Evidence-quality evaluation
6. Confidence calculation
7. Finding emission with canonical flags
8. Similarity trace population
9. Deduplication

The SEMANTIC layer is consulted ONLY after EXACT, NORMALIZED and LEXICAL
have failed to establish a stronger reuse condition. Embeddings are
produced by an injected :class:`EmbeddingProvider`; the detector never
hard-codes a particular commercial API. A failing or unavailable
provider is represented in the trace as
``SimilarityLayer.UNKNOWN`` with ``embedding_model`` unset; the detector
never fabricates a similarity score of zero to mask provider failure.

Evidence quality
----------------

The detector accepts an optional :class:`EvidenceQualityEvaluator`
(typically a :class:`DocumentMetaQualityEvaluator`). When supplied --
and it is by default -- the detector evaluates the per-document
quality of both sides of the pair, combines them into a per-pair
assessment, and:

* Populates the new typed quality fields on
  :class:`QualitySignals` (``quality_state``, ``quality_reasons``,
  ``completeness``, ``ocr_quality``, ``field_quality``,
  ``metadata_reliability``).
* Uses the assessment to apply a conservative quality gate on the
  SEMANTIC layer via
  :func:`ai_verification.evidence_quality.should_allow_semantic_finding`.
  EXACT, NORMALIZED and LEXICAL are unaffected.
* Continues to feed the existing cross-bidder confidence formula
  with the legacy ``ocr_confidence`` / ``field_confidence``
  fields, which the detector populates from the new assessment's
  component scores. The existing confidence formula is preserved.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from ai_verification.cross_bidder.embedding import (
    EmbeddingProvider,
    UnavailableEmbeddingProvider,
    cosine_similarity,
)
from ai_verification.cross_bidder.trace import (
    CorroborationSignals,
    QualitySignals,
    SimilarityLayer,
    SimilarityTrace,
    TemplateGate,
    TemplateGateStatus,
)

from compliance_engine.flags import get_flag_definition, FLAG_REGISTRY

from ai_verification.evidence_quality import (
    DocumentMetaQualityEvaluator,
    EvidenceQualityAssessment,
    EvidenceQualityEvaluator,
    QualityState,
    should_allow_semantic_finding,
)

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

from .normalization import NORMALIZATION_VERSION, normalize_text, normalized_text_hash

# Default cosine similarity threshold for the SEMANTIC layer.
# Cosine similarity in this project is interpreted in [0.0, 1.0]; 0.85
# is the cut-off above which two normalized documents are deemed
# semantically near-duplicate. The threshold is configurable at the
# detector call site.
DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD = 0.85

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
# Semantic comparison
# ---------------------------------------------------------------------------


def _semantic_similarity(
    left_meta,
    right_meta,
    artifact_store,
    left_doc_id,
    right_doc_id,
    *,
    embedding_provider: EmbeddingProvider,
):
    """Compute semantic cosine similarity between two documents.

    Returns a tuple ``(score, available)``:

    * ``(score, True)`` -- a real cosine similarity in ``[0.0, 1.0]``.
    * ``(0.0, False)``  -- the semantic layer is unavailable for this
      pair. The detector must not use the score; the trace records the
      layer as ``SimilarityLayer.UNKNOWN`` with ``embedding_model``
      unset, distinguishable from a "low similarity" finding.

    The function never fabricates a score when the provider is
    unavailable; it never silently maps an exception to ``0.0``.
    """
    left_raw = artifact_store.get_raw_text(left_doc_id)
    right_raw = artifact_store.get_raw_text(right_doc_id)
    if left_raw is None or right_raw is None:
        return 0.0, False
    left_norm = normalize_text(left_raw)
    right_norm = normalize_text(right_raw)
    if not left_norm or not right_norm:
        return 0.0, False

    try:
        left_vector = embedding_provider.embed(left_norm)
        right_vector = embedding_provider.embed(right_norm)
    except Exception:
        # Any provider-level exception is treated as "unavailable";
        # the trace is responsible for recording the absence.
        return 0.0, False

    if left_vector is None or right_vector is None:
        return 0.0, False

    try:
        score = cosine_similarity(left_vector, right_vector)
    except Exception:
        return 0.0, False

    return score, True


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
# Evidence-quality integration
# ---------------------------------------------------------------------------


def _combine_pair_assessments(
    left: EvidenceQualityAssessment,
    right: EvidenceQualityAssessment,
) -> EvidenceQualityAssessment:
    """Combine two per-document assessments into one per-pair
    assessment.

    Combination rules:

    * ``ocr_quality`` = ``min(left.ocr_quality, right.ocr_quality)``,
      mirroring the existing cross-bidder confidence formula's
      ``Q = min(ocr_confidence, field_confidence)``.
    * ``field_quality`` = ``min(left.field_quality, right.field_quality)``.
    * ``completeness`` = ``min(left.completeness, right.completeness)``.
    * ``metadata_reliability`` = ``min(left.metadata_reliability, right.metadata_reliability)``.
    * ``quality_score`` = ``min(left.quality_score, right.quality_score)``.
      Conservative: the worst side of the pair drives the overall
      number, so the confidence formula cannot be inflated by
      cherry-picking the better side.
    * ``state`` is the *worst* state in the ``GOOD`` < ``DEGRADED`` <
      ``UNKNOWN`` ordering: if either side is ``UNKNOWN`` the pair is
      ``UNKNOWN``; else if either side is ``DEGRADED`` the pair is
      ``DEGRADED``; else ``GOOD``.
    * ``reasons`` = union of left and right reasons, deduplicated,
      sorted by their canonical declaration order.
    """
    from ai_verification.evidence_quality.assessment import (
        QualityComponentScores,
    )
    from ai_verification.evidence_quality.state import QualityReason

    def _min_state(
        a: QualityState, b: QualityState
    ) -> QualityState:
        order = {QualityState.GOOD: 0, QualityState.DEGRADED: 1, QualityState.UNKNOWN: 2}
        return a if order[a] >= order[b] else b

    combined_components = QualityComponentScores(
        ocr_quality=min(left.components.ocr_quality, right.components.ocr_quality),
        field_quality=min(left.components.field_quality, right.components.field_quality),
        completeness=min(left.components.completeness, right.components.completeness),
        metadata_reliability=min(
            left.components.metadata_reliability,
            right.components.metadata_reliability,
        ),
    )
    combined_score = min(left.quality_score, right.quality_score)
    combined_state = _min_state(left.state, right.state)
    seen: set[QualityReason] = set()
    ordered: list[QualityReason] = []
    for reason in list(left.reasons) + list(right.reasons):
        if reason not in seen:
            seen.add(reason)
            ordered.append(reason)

    return EvidenceQualityAssessment(
        state=combined_state,
        quality_score=combined_score,
        components=combined_components,
        reasons=ordered,
    )


def _build_quality_signals(
    left_meta,
    right_meta,
    assessment: EvidenceQualityAssessment,
) -> QualitySignals:
    """Populate a :class:`QualitySignals` from an assessment.

    The three legacy fields (``ocr_confidence``, ``field_confidence``,
    ``quality_score``) are populated from the assessment's component
    scores and overall score, so the existing cross-bidder
    confidence formula continues to consume them unchanged.

    The new typed fields are populated from the assessment's
    state, reasons, and per-component scores.
    """
    return QualitySignals(
        ocr_confidence=float(assessment.components.ocr_quality),
        field_confidence=float(assessment.components.field_quality),
        quality_score=float(assessment.quality_score),
        quality_state=str(assessment.state),
        quality_reasons=[str(r) for r in assessment.reasons],
        completeness=float(assessment.components.completeness),
        ocr_quality=float(assessment.components.ocr_quality),
        field_quality=float(assessment.components.field_quality),
        metadata_reliability=float(
            assessment.components.metadata_reliability
        ),
    )


def _evaluate_pair_quality(
    left_meta,
    right_meta,
    left_document_id: str,
    right_document_id: str,
    artifact_store,
    quality_evaluator: EvidenceQualityEvaluator,
) -> EvidenceQualityAssessment:
    """Run the per-pair quality pipeline.

    The detector calls this once per pair. It evaluates each side
    with the supplied evaluator and combines the two assessments
    using :func:`_combine_pair_assessments`.
    """
    if isinstance(quality_evaluator, DocumentMetaQualityEvaluator):
        left_assessment = quality_evaluator.evaluate_for_document(
            left_document_id, left_meta
        )
        right_assessment = quality_evaluator.evaluate_for_document(
            right_document_id, right_meta
        )
    else:
        # Generic evaluator path: callers inject a custom evaluator
        # and we still call it with the same signals it would have
        # seen via the artifact store. For backwards compatibility,
        # custom evaluators are passed the pre-built signals bundle.
        from ai_verification.evidence_quality import (
            build_signals_for_document,
        )

        left_signals = build_signals_for_document(
            left_document_id, left_meta, artifact_store
        )
        right_signals = build_signals_for_document(
            right_document_id, right_meta, artifact_store
        )
        left_assessment = quality_evaluator.evaluate(left_signals)
        right_assessment = quality_evaluator.evaluate(right_signals)
    return _combine_pair_assessments(left_assessment, right_assessment)


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
    *,
    embedding_provider: Optional[EmbeddingProvider] = None,
    semantic_similarity_threshold: float = DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD,
    quality_evaluator: Optional[EvidenceQualityEvaluator] = None,
):
    """Detect cross-bidder document anomalies between two documents.

    Returns (findings, trace). Findings is a list of VerificationFinding objects.

    The SEMANTIC layer is consulted ONLY when EXACT, NORMALIZED and LEXICAL
    have all failed to establish a stronger reuse condition. Embeddings
    are produced by the injected ``embedding_provider``; if no provider
    is supplied, an :class:`UnavailableEmbeddingProvider` is used so the
    detector still behaves deterministically.

    Provider failure does **not** map to a similarity score of zero;
    it is recorded as ``SimilarityLayer.UNKNOWN`` with ``embedding_model``
    unset, which is distinguishable in the audit trace from a finding
    of "low semantic similarity".

    The optional ``quality_evaluator`` is the dependency-injection
    seam for the evidence-quality subsystem. When ``None`` (the
    default) the detector uses a
    :class:`DocumentMetaQualityEvaluator` bound to ``artifact_store``.
    The evaluator is consulted for every pair; its assessment
    populates the new typed fields on :class:`QualitySignals` and
    drives the conservative semantic-layer gate.
    """
    if embedding_provider is None:
        embedding_provider = UnavailableEmbeddingProvider()
    if quality_evaluator is None:
        if hasattr(artifact_store, "get_metadata") and hasattr(
            artifact_store, "get_raw_text"
        ):
            from ai_verification.cross_bidder.document_artifact_store import (
                DocumentArtifactStore,
            )
            if isinstance(artifact_store, DocumentArtifactStore):
                quality_evaluator = DocumentMetaQualityEvaluator(
                    artifact_store=artifact_store
                )
            else:
                quality_evaluator = DocumentMetaQualityEvaluator(
                    artifact_store=artifact_store
                )
        else:
            quality_evaluator = DocumentMetaQualityEvaluator()

    # Load metadata if not provided
    if left_meta is None:
        left_meta = artifact_store.get_metadata(left_document_id) if hasattr(artifact_store, "get_metadata") else None
    if right_meta is None:
        right_meta = artifact_store.get_metadata(right_document_id) if hasattr(artifact_store, "get_metadata") else None

    if left_meta is None or right_meta is None:
        from ai_verification.cross_bidder.document_artifact_store import DocumentMeta
        left_meta = left_meta or DocumentMeta(document_type="UNKNOWN", ocr_confidence=1.0, document_type_confidence=1.0)
        right_meta = right_meta or DocumentMeta(document_type="UNKNOWN", ocr_confidence=1.0, document_type_confidence=1.0)

    # Evidence-quality evaluation runs once per pair, *before*
    # candidate blocking, so an UNKNOWN quality result can be
    # recorded even if a same-bidder pair is suppressed by the
    # blocking check. The result is captured in the trace.
    pair_quality = _evaluate_pair_quality(
        left_meta,
        right_meta,
        left_document_id,
        right_document_id,
        artifact_store,
        quality_evaluator,
    )

    # Candidate blocking
    if not _candidate_blocking(left_meta, right_meta):
        return [], _make_empty_trace(
            left_document_id,
            right_document_id,
            left_bidder_id,
            right_bidder_id,
        )

    # Byte hash comparison
    byte_hash_result = _byte_hash_match(left_meta, right_meta, artifact_store, left_document_id, right_document_id)

    # Normalized hash comparison
    norm_hash_result = _normalized_hash_match(left_meta, right_meta, artifact_store, left_document_id, right_document_id)

    # Lexical similarity
    dice_score = _lexical_dice(left_meta, right_meta, artifact_store, left_document_id, right_document_id)

    # Semantic similarity is consulted ONLY after EXACT / NORMALIZED /
    # LEXICAL have failed to establish a stronger reuse condition.
    semantic_score: float | None = None
    semantic_available: bool = False
    semantic_threshold_used: float = semantic_similarity_threshold

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
        winning_layer = "LEXICAL"
        similarity_score = dice_score
        flag_id = "CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE"
    else:
        # EXACT, NORMALIZED and LEXICAL failed. Before consulting
        # the SEMANTIC layer, run the conservative quality gate.
        # EXACT/NORMALIZED/LEXICAL reuse are unaffected; only the
        # semantic layer depends on extraction quality.
        if not should_allow_semantic_finding(pair_quality):
            return [], _make_empty_trace(
                left_document_id, right_document_id,
                left_bidder_id, right_bidder_id,
                semantic_consulted=False,
                semantic_available=False,
                semantic_score=None,
                semantic_threshold=None,
                embedding_model_name=None,
            )
        # Consult the SEMANTIC layer via the injected embedding
        # provider. The provider is allowed to be unavailable; in
        # that case the layer is recorded as UNKNOWN with
        # embedding_model unset (set later in this function).
        semantic_score, semantic_available = _semantic_similarity(
            left_meta,
            right_meta,
            artifact_store,
            left_document_id,
            right_document_id,
            embedding_provider=embedding_provider,
        )
        if (
            semantic_available
            and semantic_score >= semantic_threshold_used
        ):
            winning_layer = "SEMANTIC"
            similarity_score = semantic_score
            threshold = semantic_threshold_used
            flag_id = "CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE"
        else:
            return [], _make_empty_trace(
                left_document_id, right_document_id,
                left_bidder_id, right_bidder_id,
                semantic_consulted=True,
                semantic_available=semantic_available,
                semantic_score=semantic_score,
                semantic_threshold=semantic_threshold_used,
                embedding_model_name=embedding_provider.model_name(),
            )

    # Metadata corroboration
    corroboration = _calculate_corroboration(left_meta, right_meta)

    # Template gate
    tg = _template_gate(left_meta, right_meta)

    # Quality signals -- populated from the evidence-quality
    # assessment. The three legacy scalar fields continue to drive
    # the existing confidence formula, which is preserved exactly.
    quality = _build_quality_signals(left_meta, right_meta, pair_quality)

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

    # The trace records the embedding model identifier ONLY when the
    # SEMANTIC layer actually fired. For EXACT, NORMALIZED and LEXICAL
    # wins the embedding model is left unset.
    trace_embedding_model: str | None = None
    if winning_layer == "SEMANTIC":
        trace_embedding_model = embedding_provider.model_name()

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
        embedding_model=trace_embedding_model,
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


def _make_empty_trace(
    left_document_id, right_document_id, left_bidder_id, right_bidder_id,
    *,
    semantic_consulted: bool = False,
    semantic_available: bool = False,
    semantic_score: float | None = None,
    semantic_threshold: float | None = None,
    embedding_model_name: str | None = None,
):
    """Create an empty trace when no finding is emitted.

    When ``semantic_consulted`` is ``True``, the trace records:

    * ``similarity_score`` is set to the semantic score if available, or
      ``0.0`` if the provider was unavailable (NEVER a fabricated zero
      from a real cosine computation).
    * ``threshold`` is set to the semantic threshold used.
    * ``embedding_model`` is set to the provider's model name if it
      was deterministically known, else ``None``.

    When ``semantic_consulted`` is ``False`` (e.g. candidate blocked,
    template mismatch before semantic consultation), the trace stays
    fully empty and the audit reader can tell that semantic was not
    consulted at all.
    """
    from ai_verification.cross_bidder.trace import SimilarityTrace, CorroborationSignals, QualitySignals, TemplateGate, TemplateGateStatus

    if semantic_consulted:
        score_for_trace = float(semantic_score) if semantic_score is not None else 0.0
        threshold_for_trace = (
            float(semantic_threshold)
            if semantic_threshold is not None
            else DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD
        )
        # Record the embedding model identifier when the provider
        # exposes it. This makes the audit trace distinguish:
        #
        # * ``embedding_model = "m"`` + ``similarity_score = 0.0``
        #     -- provider was queried, score was computed, fell below
        #     threshold (or was zero because vectors were orthogonal).
        # * ``embedding_model = None`` + ``similarity_score = 0.0``
        #     -- provider was unavailable or exception was caught.
        embedding_for_trace: str | None = embedding_model_name
    else:
        score_for_trace = 0.0
        threshold_for_trace = 0.80
        embedding_for_trace = None

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
        similarity_score=score_for_trace,
        threshold=threshold_for_trace,
        corroboration=CorroborationSignals(
            same_issuer=None, same_authorization_number=None, same_issue_date=None, validity_overlap=None
        ),
        quality=QualitySignals(ocr_confidence=1.0, field_confidence=1.0, quality_score=1.0),
        template_gate=TemplateGate(status=TemplateGateStatus.UNKNOWN, score=0.0, matched_fields=[], mismatched_fields=[], unknown_fields=["authorization_number", "issue_date", "bidder_name", "territory"]),
        confidence=0.0,
        embedding_model=embedding_for_trace,

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

def compare_two_documents(
    bidder_id,
    other_bidder_id,
    left_doc_id,
    right_doc_id,
    artifact_store,
    *,
    embedding_provider: Optional[EmbeddingProvider] = None,
    semantic_similarity_threshold: float = DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD,
    quality_evaluator: Optional[EvidenceQualityEvaluator] = None,
):
    """Compare two documents from potentially different bidders.

    Optional ``embedding_provider``, ``semantic_similarity_threshold``
    and ``quality_evaluator`` are forwarded to the detector. If
    absent, the detector behaves exactly as before for embeddings
    (it stops at the LEXICAL layer because the default
    :class:`UnavailableEmbeddingProvider` returns ``None`` from
    every call) and uses a default :class:`DocumentMetaQualityEvaluator`
    bound to ``artifact_store`` for quality.
    """
    detect_kwargs: dict = {
        "embedding_provider": embedding_provider,
        "semantic_similarity_threshold": semantic_similarity_threshold,
    }
    if quality_evaluator is not None:
        detect_kwargs["quality_evaluator"] = quality_evaluator
    findings, trace = detect_cross_bidder_anomalies(
        left_bidder_id=bidder_id,
        right_bidder_id=other_bidder_id,
        left_document_id=left_doc_id,
        right_document_id=right_doc_id,
        artifact_store=artifact_store,
        **detect_kwargs,
    )
    return findings, trace
