"""Bridge from Compliance Engine outputs to durable persistence.

This module is the *only* seam where a
:class:`~compliance_engine.models.engine_models.EngineResult` is turned
into durable records. The Compliance Engine itself remains
persistence-free: it knows nothing about repositories, units of work,
or PostgreSQL. Callers hand this writer the normalized submission and
the engine result, and the writer maps them onto the existing durable
records through the existing repository protocols and the existing
unit-of-work transaction boundary.

Scope rule: this writer persists *Compliance Engine outputs only* —
submission/document/evidence provenance, compliance results, and
verification records. It deliberately never writes findings,
explanations, flag states, snapshots, risk, or any other downstream
AI Verification artefact.

Provenance rule: the upstream ``file_hash`` is upstream-supplied
provenance and is stored in ``DocumentRecord.metadata["file_hash"]``.
It is *not* written to ``content_hash``, which remains reserved for
the hash computed from raw document bytes by the artifact store.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Callable

from compliance_engine.models.engine_models import EngineResult
from compliance_engine.models.ingestion import NormalizedSubmission
from compliance_engine.models.result import ComplianceResult
from compliance_engine.models.verification import Verification

from infrastructure.audit import audit_event
from infrastructure.persistence.records import (
    BidderRecord,
    ComplianceResultRecord,
    DocumentRecord,
    EvidenceRecord,
    SubmissionRecord,
    VerificationRecord,
)
from infrastructure.pipeline import ProcessingStage


def _default_clock() -> float:
    return time.time()


def _result_id(submission_id: str, bidder_id: str, requirement_id: str) -> str:
    """Stable surrogate id for one compliance outcome within a submission."""
    key = f"compliance_result:{submission_id}:{bidder_id}:{requirement_id}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

def _to_verification_record(
    verification: Verification, *, created_at: float
) -> VerificationRecord:
    return VerificationRecord(
        verification_id=verification.verification_id,
        bidder_id=verification.bidder_id,
        capability=verification.capability,
        source=verification.source,
        queried_identifier=verification.queried_identifier,
        status=str(verification.status),
        data=dict(verification.data),
        query=None if verification.query is None else dict(verification.query),
        raw_response=verification.raw_response,
        retrieved_at=verification.retrieved_at.timestamp(),
        latency_ms=verification.latency_ms,
        correlation_id=verification.correlation_id,
        transport_status_code=verification.transport_status_code,
        evidence_id=verification.evidence_id,
        document_id=verification.document_id,
        created_at=created_at,
    )


def _to_compliance_result_record(
    result: ComplianceResult,
    *,
    submission_id: str,
    bidder_id: str,
    now: float,
) -> ComplianceResultRecord:
    return ComplianceResultRecord(
        result_id=_result_id(submission_id, bidder_id, result.requirement_id),
        submission_id=submission_id,
        bidder_id=bidder_id,
        requirement_id=result.requirement_id,
        capability=result.capability,
        status=str(result.status),
        reason=result.reason,
        expected=result.expected,
        actual=result.actual,
        rule_id=result.rule_id,
        evidence_refs=list(result.evidence_refs),
        verification_refs=list(result.verification_refs),
        flags=list(result.flags),
        created_at=now,
        updated_at=now,
    )

def _persist_documents_and_evidence(
    uow: Any,
    submission: NormalizedSubmission,
    clock: Callable[[], float],
) -> None:
    """Persist document provenance and field-level evidence.

    Existing documents are left untouched so an artifact-store
    ``content_hash`` is never clobbered; upstream ``file_hash`` and
    other document-level provenance live in ``metadata``.
    """
    for document in submission.documents:
        created_at = clock()
        if uow.repos.documents.get(document.document_id) is None:
            metadata: dict[str, Any] = {
                "source": "upstream_extraction",
                "doc_type_confidence": document.doc_type_confidence,
                "ocr_confidence": document.ocr_confidence,
            }
            if document.file_hash is not None:
                metadata["file_hash"] = document.file_hash
            if document.grounding is not None:
                metadata["grounding"] = document.grounding.model_dump(mode="json")
            uow.repos.documents.add(
                DocumentRecord(
                    document_id=document.document_id,
                    submission_id=submission.submission_id,
                    bidder_id=submission.bidder_id,
                    document_type=document.doc_type,
                    content_hash=None,
                    metadata={k: v for k, v in metadata.items() if v is not None},
                    created_at=created_at,
                )
            )
        for evidence in document.evidence:
            if uow.repos.evidence.get(evidence.evidence_id) is not None:
                continue
            uow.repos.evidence.add(
                EvidenceRecord(
                    evidence_id=evidence.evidence_id,
                    bidder_id=submission.bidder_id,
                    document_id=evidence.document_id,
                    field_name=evidence.field_name,
                    document_type=evidence.document_type,
                    value=evidence.value,
                    confidence=evidence.confidence,
                    page=evidence.page,
                    bbox=None if evidence.bbox is None else list(evidence.bbox),
                    missing_reason=evidence.missing_reason,
                    created_at=created_at,
                )
            )


def persist_engine_result(
    submission: NormalizedSubmission,
    result: EngineResult,
    *,
    uow: Any,
    clock: Callable[[], float] | None = None,
    correlation_id: str | None = None,
) -> None:
    """Persist one engine evaluation durably within a single unit of work.

    ``submission`` is the normalized upstream envelope (the provenance
    source); ``result`` is the :class:`EngineResult` produced from that
    submission's evidence. When both supply ``submission_id`` /
    ``bidder_id`` they must agree.

    All writes (documents, evidence, verifications, compliance results)
    share the caller-provided unit of work, so they commit or roll back
    atomically; one append-only audit event records the bridge write.
    """
    if clock is None:
        clock = _default_clock

    submission_id = submission.submission_id
    bidder_id = submission.bidder_id
    if result.submission_id is not None and result.submission_id != submission_id:
        raise ValueError(
            f"EngineResult.submission_id {result.submission_id!r} does not "
            f"match NormalizedSubmission.submission_id {submission_id!r}."
        )
    if result.bidder_id is not None and result.bidder_id != bidder_id:
        raise ValueError(
            f"EngineResult.bidder_id {result.bidder_id!r} does not match "
            f"NormalizedSubmission.bidder_id {bidder_id!r}."
        )

    verification_count = 0

    with uow:
        if uow.repos.bidders.get(bidder_id) is None:
            now = clock()
            uow.repos.bidders.add(
                BidderRecord(bidder_id=bidder_id, created_at=now, updated_at=now)
            )
        if uow.repos.submissions.get(submission_id) is None:
            now = clock()
            uow.repos.submissions.add(
                SubmissionRecord(
                    submission_id=submission_id,
                    bidder_id=bidder_id,
                    stage=ProcessingStage.INGESTED.value,
                    correlation_id=correlation_id,
                    created_at=now,
                    updated_at=now,
                )
            )

        _persist_documents_and_evidence(uow, submission, clock)

        for verification in result.verification_records:
            uow.repos.verifications.save(
                _to_verification_record(verification, created_at=clock())
            )
            verification_count += 1

        for compliance in result.compliance_results:
            uow.repos.compliance_results.save(
                _to_compliance_result_record(
                    compliance,
                    submission_id=submission_id,
                    bidder_id=bidder_id,
                    now=clock(),
                )
            )

        uow.repos.audit.add(
            audit_event(
                aggregate_type="SUBMISSION",
                aggregate_id=submission_id,
                event_type="ENGINE_RESULT_PERSISTED",
                payload={
                    "submission_id": submission_id,
                    "bidder_id": bidder_id,
                    "documents": len(submission.documents),
                    "evidence": len(submission.evidence),
                    "verifications": verification_count,
                    "compliance_results": len(result.compliance_results),
                },
                correlation_id=correlation_id,
                created_at=clock(),
            )
        )


__all__ = ["persist_engine_result"]
