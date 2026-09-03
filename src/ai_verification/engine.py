"""Top-level AI verification engine."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import List, Tuple, Dict, Set, Optional

from .models.contracts import VerificationInput, VerificationResult
from .cross_bidder.detector import detect_cross_bidder_anomalies
from .cross_bidder.document_artifact_store import DocumentArtifactStore


class VerificationEngine:
    """Run AI verification checks for a bidder."""

    def __init__(self, artifact_store: Optional[DocumentArtifactStore] = None) -> None:
        """Initialize the engine with an optional artifact store for cross-bidder checks."""
        self._artifact_store = artifact_store

    def run(self, input: VerificationInput) -> VerificationResult:
        """Return the verification result for a bidder, including cross-bidder findings if possible."""
        findings: List[VerificationFinding] = []

        # If we don't have an artifact store, we cannot perform cross-bidder document checks.
        if self._artifact_store is None:
            return VerificationResult(
                bidder_id=input.bidder_id,
                findings=findings,
                generated_at=datetime.now(UTC),
            )

        # Build a list of bidders: the current bidder and the corpus bidders.
        # Each bidder is represented by (bidder_id, list of (document_id, document_type) from evidence)
        bidders: List[Tuple[str, List[Tuple[str, str]]]] = []

        # Current bidder
        current_docs: List[Tuple[str, str]] = []
        for evidence in input.evidence:
            # We assume that for a given document_id, the document_type is consistent across evidence.
            current_docs.append((evidence.document_id, evidence.document_type))
        # Deduplicate by document_id per bidder (keep first occurrence)
        seen: Set[str] = set()
        unique_current: List[Tuple[str, str]] = []
        for doc_id, doc_type in current_docs:
            if doc_id not in seen:
                seen.add(doc_id)
                unique_current.append((doc_id, doc_type))
        bidders.append((input.bidder_id, unique_current))

        # Corpus bidders
        for corp in input.bidder_corpus:
            corp_docs: List[Tuple[str, str]] = []
            for evidence in corp.evidence:
                corp_docs.append((evidence.document_id, evidence.document_type))
            seen = set()
            unique_corp: List[Tuple[str, str]] = []
            for doc_id, doc_type in corp_docs:
                if doc_id not in seen:
                    seen.add(doc_id)
                    unique_corp.append((doc_id, doc_type))
            bidders.append((corp.bidder_id, unique_corp))

        # Compare each pair of bidders (different bidders only)
        n = len(bidders)
        for i in range(n):
            bidder_i_id, bidder_i_docs = bidders[i]
            for j in range(i + 1, n):
                bidder_j_id, bidder_j_docs = bidders[j]
                # Avoid comparing the same bidder (shouldn't happen due to i<j, but keep for safety)
                if bidder_i_id == bidder_j_id:
                    continue
                # Compare each document from bidder i with each document from bidder j
                for doc_id_i, doc_type_i in bidder_i_docs:
                    for doc_id_j, doc_type_j in bidder_j_docs:
                        # Only compare if document types match (early skip)
                        if doc_type_i != doc_type_j:
                            continue
                        # Call the detector for this pair of documents
                        pair_findings, _ = detect_cross_bidder_anomalies(
                            left_bidder_id=bidder_i_id,
                            right_bidder_id=bidder_j_id,
                            left_document_id=doc_id_i,
                            right_document_id=doc_id_j,
                            artifact_store=self._artifact_store,
                        )
                        findings.extend(pair_findings)

        return VerificationResult(
            bidder_id=input.bidder_id,
            findings=findings,
            generated_at=datetime.now(UTC),
        )


__all__ = ["VerificationEngine"]
