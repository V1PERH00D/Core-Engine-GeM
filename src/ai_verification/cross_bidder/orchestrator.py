"""Cross-bidder document-pair orchestrator.

This module is a thin layer on top of the existing
``detect_cross_bidder_anomalies`` detector. Its only responsibilities
are:

1. Enumerate document pairs across the primary bidder and the corpus
   bidders, in a stable, deterministic order.
2. Skip pairs that cannot legitimately be compared (same bidder,
   different document types, missing artifact metadata).
3. De-duplicate at the pair level so the same document pair is never
   compared twice within a single run.
4. Preserve explicit ``bidder_id`` on the left/right sides.
5. Attach ``verification_refs`` to each emitted finding by matching
   the findings ``evidence_refs`` against ``Verification.evidence_id``
   values present in the current input.
6. Never fabricate data: any document whose metadata or raw text is
   missing is silently skipped.
7. Forward an injected :class:`EmbeddingProvider` and configurable
   semantic similarity threshold to the detector without owning any
   provider / network / credentials logic of its own.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

from compliance_engine.models import Evidence
from compliance_engine.models.verification import Verification

from ai_verification.cross_bidder.document_artifact_store import DocumentArtifactStore
from ai_verification.cross_bidder.detector import (
    DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD,
    detect_cross_bidder_anomalies,
)
from ai_verification.cross_bidder.embedding import (
    EmbeddingProvider,
    UnavailableEmbeddingProvider,
)
from ai_verification.evidence_quality import EvidenceQualityEvaluator
from ai_verification.models.contracts import VerificationFinding


# ---------------------------------------------------------------------------
# Bidder index construction
# ---------------------------------------------------------------------------


def _unique_documents(
    evidence: Iterable[Evidence],
) -> List[Tuple[str, str]]:
    """Return (document_id, document_type) pairs in first-seen order.

    The primary bidder may submit several evidence items that all
    reference the same ``document_id``; the orchestrator only needs
    one entry per document, so we deduplicate on ``document_id`` while
    preserving the order in which documents were first observed.
    This gives deterministic pair enumeration across runs.
    """
    seen: set[str] = set()
    docs: List[Tuple[str, str]] = []
    for ev in evidence:
        if ev.document_id in seen:
            continue
        seen.add(ev.document_id)
        docs.append((ev.document_id, ev.document_type))
    return docs


def _collect_verification_index(
    verification_records: Iterable[Verification],
) -> dict[str, str]:
    """Build an ``evidence_id -> verification_id`` index.

    The index is intentionally a one-to-one mapping per
    ``evidence_id``: if multiple verification records somehow point
    at the same ``evidence_id``, the first one observed wins. This
    keeps the orchestrator deterministic and avoids fabricating
    associations for evidence items that have no verification
    record.
    """
    index: dict[str, str] = {}
    for record in verification_records:
        if record.evidence_id is None:
            continue
        index.setdefault(record.evidence_id, record.verification_id)
    return index


# ---------------------------------------------------------------------------
# Verification reference attachment
# ---------------------------------------------------------------------------


def _attach_verification_refs(
    findings: Sequence[VerificationFinding],
    *,
    left_verification_index: dict[str, str],
    right_verification_index: dict[str, str],
) -> List[VerificationFinding]:
    """Return new findings with verification_refs populated from indices.

    The detector does not have access to the Compliance Engines
    verification records, so it always emits
    ``verification_refs=[]``. The orchestrator is the place where
    evidence_id-based associations are resolved, because it is the
    only layer that has both the findings and the verification
    records available.

    The mapping is a *real* association: we only attach a
    ``verification_id`` to a finding if the underlying
    ``Verification.evidence_id`` matches one of the findings
    ``evidence_refs``. We never invent IDs.
    """
    augmented: List[VerificationFinding] = []
    for finding in findings:
        verification_refs: List[str] = []
        for evidence_id in finding.evidence_refs:
            for index in (
                left_verification_index,
                right_verification_index,
            ):
                candidate = index.get(evidence_id)
                if (
                    candidate is not None
                    and candidate not in verification_refs
                ):
                    verification_refs.append(candidate)
        if verification_refs:
            finding = finding.model_copy(
                update={"verification_refs": verification_refs}
            )
        augmented.append(finding)
    return augmented


# ---------------------------------------------------------------------------
# Pair enumeration
# ---------------------------------------------------------------------------


def _enumerate_pairs(
    primary_bidder_id: str,
    primary_docs: Sequence[Tuple[str, str]],
    corpus: Sequence[Tuple[str, Sequence[Tuple[str, str]]]],
) -> List[Tuple[str, str, str, str]]:
    """Enumerate ``(left_bidder, left_doc, right_bidder, right_doc)`` tuples.

    - Only pairs across different bidder IDs are considered.
    - The primary bidder is always the *left* side. This keeps the
      emitted ``bidder_id`` of every finding equal to the primary
      bidder, which is the contract documented on
      ``VerificationFinding``.
    - Pair identity is canonical: we sort on the
      ``(left_doc, right_doc)`` pair so the same logical pair is
      never produced twice even if two corpus bidders refer to the
      same document.
    - Cross-comparison between corpus bidders is intentionally out of
      scope: the current ``VerificationInput`` contract is "compare
      the primary bidder to every corpus bidder", and we honour that
      minimum.
    """
    pairs: List[Tuple[str, str, str, str]] = []
    seen_pairs: set[Tuple[str, str]] = set()
    for other_bidder_id, other_docs in corpus:
        if other_bidder_id == primary_bidder_id:
            continue
        for left_doc_id, _ in primary_docs:
            for right_doc_id, _ in other_docs:
                if left_doc_id == right_doc_id:
                    continue
                pair_key = tuple(sorted((left_doc_id, right_doc_id)))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                pairs.append(
                    (
                        primary_bidder_id,
                        left_doc_id,
                        other_bidder_id,
                        right_doc_id,
                    )
                )
    return pairs


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class CrossBidderOrchestrator:
    """Drive the cross-bidder detector across a VerificationInput bundle.

    The orchestrator is stateless and side-effect free apart from
    calling the supplied artifact store. It is safe to construct
    once and reuse across many ``run`` calls.

    The ``embedding_provider`` is injected at construction time. The
    orchestrator never opens a network, never holds credentials, and
    never fabricates embeddings -- it only forwards the provider to
    the detector.
    """

    def __init__(
        self,
        artifact_store: DocumentArtifactStore,
        *,
        embedding_provider: Optional[EmbeddingProvider] = None,
        semantic_similarity_threshold: float = DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD,
        quality_evaluator: Optional[EvidenceQualityEvaluator] = None,
    ) -> None:
        self._artifact_store = artifact_store
        self._embedding_provider: EmbeddingProvider = (
            embedding_provider or UnavailableEmbeddingProvider()
        )
        self._semantic_similarity_threshold = float(
            semantic_similarity_threshold
        )
        self._quality_evaluator: Optional[EvidenceQualityEvaluator] = (
            quality_evaluator
        )

    def run(
        self,
        *,
        primary_bidder_id: str,
        primary_evidence: Sequence[Evidence],
        primary_verification_records: Sequence[Verification],
        corpus: Sequence[
            Tuple[
                str,
                Sequence[Evidence],
                Sequence[Verification],
            ]
        ],
    ) -> List[VerificationFinding]:
        """Execute the cross-bidder pipeline and return its findings.

        ``corpus`` is a sequence of
        ``(bidder_id, evidence, verification_records)`` triples
        describing every other bidder to compare against. The
        orchestrator does not mutate any of these inputs; it only
        reads them.
        """
        primary_docs = _unique_documents(primary_evidence)
        if not primary_docs:
            return []

        corpus_index: List[
            Tuple[str, Sequence[Tuple[str, str]]]
        ] = []
        for other_bidder_id, other_evidence, _ in corpus:
            corpus_index.append(
                (other_bidder_id, _unique_documents(other_evidence))
            )

        pairs = _enumerate_pairs(
            primary_bidder_id, primary_docs, corpus_index
        )
        if not pairs:
            return []

        left_verification_index = _collect_verification_index(
            primary_verification_records
        )

        findings: List[VerificationFinding] = []
        detect_kwargs: dict = {
            "embedding_provider": self._embedding_provider,
            "semantic_similarity_threshold": self._semantic_similarity_threshold,
        }
        if self._quality_evaluator is not None:
            detect_kwargs["quality_evaluator"] = self._quality_evaluator
        for (
            left_bidder,
            left_doc,
            right_bidder,
            right_doc,
        ) in pairs:
            pair_findings, _ = detect_cross_bidder_anomalies(
                left_bidder_id=left_bidder,
                right_bidder_id=right_bidder,
                left_document_id=left_doc,
                right_document_id=right_doc,
                artifact_store=self._artifact_store,
                **detect_kwargs,
            )
            if not pair_findings:
                continue
            right_verification_records: Sequence[Verification] = []
            for other_bidder_id, _, other_records in corpus:
                if other_bidder_id == right_bidder:
                    right_verification_records = other_records
                    break
            right_verification_index = _collect_verification_index(
                right_verification_records
            )
            findings.extend(
                _attach_verification_refs(
                    pair_findings,
                    left_verification_index=left_verification_index,
                    right_verification_index=right_verification_index,
                )
            )
        return findings


__all__ = ["CrossBidderOrchestrator"]
