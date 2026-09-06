"""Top-level AI verification engine.

The engine is a thin orchestrator that:

- accepts an optional :class:`DocumentArtifactStore` for cross-bidder
  document checks;
- delegates the actual pair enumeration and finding post-processing
  to :class:`CrossBidderOrchestrator`;
- returns a deterministic :class:`VerificationResult` with a
  timezone-aware UTC ``generated_at``;
- never mutates the input bundle or any of its nested objects.

The optional ``embedding_provider`` is forwarded to the orchestrator
and onward to the cross-bidder detector. The engine itself never opens
a network and never holds provider credentials.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import List, Optional

from .cross_bidder.document_artifact_store import DocumentArtifactStore
from .cross_bidder.embedding import EmbeddingProvider
from .cross_bidder.orchestrator import CrossBidderOrchestrator
from .cross_document.engine import CrossDocumentConsistencyEngine
from .evidence_quality import EvidenceQualityEvaluator
from .identity import IdentityReconciliationEngine
from .models.contracts import (
    VerificationFinding,
    VerificationInput,
    VerificationResult,
)


class VerificationEngine:
    """Run AI verification checks for a bidder."""

    def __init__(
        self,
        artifact_store: Optional[DocumentArtifactStore] = None,
        *,
        embedding_provider: Optional[EmbeddingProvider] = None,
        semantic_similarity_threshold: Optional[float] = None,
        quality_evaluator: Optional[EvidenceQualityEvaluator] = None,
        identity_reconciliation_engine: Optional[
            IdentityReconciliationEngine
        ] = None,
        cross_document_consistency_engine: Optional[
            CrossDocumentConsistencyEngine
        ] = None,
    ) -> None:
        """Initialize the engine with optional sub-engines."""
        self._artifact_store = artifact_store
        self._embedding_provider = embedding_provider
        self._semantic_similarity_threshold = semantic_similarity_threshold
        self._quality_evaluator = quality_evaluator
        self._identity_reconciliation_engine = (
            identity_reconciliation_engine
        )
        self._cross_document_consistency_engine = (
            cross_document_consistency_engine
        )

    def run(self, input: VerificationInput) -> VerificationResult:
        """Return the verification result for a bidder."""
        identity_findings: List[VerificationFinding] = (
            self._run_identity_reconciliation(input)
        )
        cross_document_findings: List[VerificationFinding] = (
            self._run_cross_document_consistency(input)
        )

        if self._artifact_store is None:
            return VerificationResult(
                bidder_id=input.bidder_id,
                findings=identity_findings + cross_document_findings,
                generated_at=datetime.now(UTC),
            )

        kwargs: dict = {}
        if self._embedding_provider is not None:
            kwargs["embedding_provider"] = self._embedding_provider
        if self._semantic_similarity_threshold is not None:
            kwargs["semantic_similarity_threshold"] = (
                self._semantic_similarity_threshold
            )
        if self._quality_evaluator is not None:
            kwargs["quality_evaluator"] = self._quality_evaluator
        orchestrator = CrossBidderOrchestrator(self._artifact_store, **kwargs)
        corpus = [
            (
                summary.bidder_id,
                summary.evidence,
                summary.verification_records,
            )
            for summary in input.bidder_corpus
        ]
        findings: List[VerificationFinding] = orchestrator.run(
            primary_bidder_id=input.bidder_id,
            primary_evidence=input.evidence,
            primary_verification_records=input.verification_records,
            corpus=corpus,
        )

        return VerificationResult(
            bidder_id=input.bidder_id,
            findings=(
                findings + identity_findings + cross_document_findings
            ),
            generated_at=datetime.now(UTC),
        )

    def _run_identity_reconciliation(
        self, input: VerificationInput
    ) -> List[VerificationFinding]:
        if self._identity_reconciliation_engine is None:
            return []
        try:
            result = self._identity_reconciliation_engine.reconcile(
                verifications=input.verification_records,
                bidder_id=input.bidder_id,
            )
        except ValueError:
            return []
        return list(result.verification_findings)

    def _run_cross_document_consistency(
        self, input: VerificationInput
    ) -> List[VerificationFinding]:
        if self._cross_document_consistency_engine is None:
            return []
        try:
            result = self._cross_document_consistency_engine.run(
                evidence=input.evidence,
                bidder_id=input.bidder_id,
            )
        except ValueError:
            return []
        return list(result.verification_findings)


__all__ = ["VerificationEngine"]
