"""Audit events and flag-lineage reconstruction.

Every durable write that matters is paired with an append-only
:class:`AuditEventRecord` whose ``aggregate_type``/``aggregate_id`` point
at a real entity ID. Together these records let the system reconstruct::

    submission -> documents -> evidence -> verification
               -> compliance -> finding -> explanation -> flag snapshot

:func:`build_flag_lineage` gathers that chain by real IDs from the
repositories. No reference is ever fabricated.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from infrastructure.persistence.records import (
    AuditEventRecord,
    ComplianceResultRecord,
    DocumentRecord,
    EvidenceRecord,
    ExplanationRecord,
    FindingRecord,
    FlagSnapshotRecord,
    FlagStateRecord,
    SubmissionRecord,
    VerificationRecord,
)


def new_event_id() -> str:
    """Return a unique audit event ID (UUID-based)."""
    return f"evt:{uuid.uuid4().hex}"


def audit_event(
    *,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    created_at: float,
) -> AuditEventRecord:
    return AuditEventRecord(
        event_id=new_event_id(),
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=dict(payload or {}),
        correlation_id=correlation_id,
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# Lineage result
# ---------------------------------------------------------------------------


class FlagLineage(BaseModel):
    bidder_id: str
    flag_id: str
    flag_state: FlagStateRecord | None = None
    submissions: list[SubmissionRecord] = Field(default_factory=list)
    documents: list[DocumentRecord] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    verifications: list[VerificationRecord] = Field(default_factory=list)
    compliance_results: list[ComplianceResultRecord] = Field(default_factory=list)
    findings: list[FindingRecord] = Field(default_factory=list)
    explanations: list[ExplanationRecord] = Field(default_factory=list)
    snapshots: list[FlagSnapshotRecord] = Field(default_factory=list)


def build_flag_lineage(
    repos: Any,
    bidder_id: str,
    flag_id: str,
) -> FlagLineage:
    """Reconstruct the full lineage for one bidder flag by real IDs."""
    state = repos.flags.get_state(bidder_id, flag_id)

    finding_refs: set[str] = set()
    evidence_refs: set[str] = set()
    verification_refs: set[str] = set()
    if state is not None:
        finding_refs.update(state.finding_refs)
        evidence_refs.update(state.evidence_refs)
        verification_refs.update(state.verification_refs)

    findings = [repos.findings.get(fid) for fid in sorted(finding_refs)]
    findings = [f for f in findings if f is not None]

    for finding in findings:
        evidence_refs.update(finding.evidence_refs)
        verification_refs.update(finding.verification_refs)

    evidence = [repos.evidence.get(eid) for eid in sorted(evidence_refs)]
    evidence = [e for e in evidence if e is not None]

    verifications = [
        repos.verifications.get(vid) for vid in sorted(verification_refs)
    ]
    verifications = [v for v in verifications if v is not None]

    document_ids = {e.document_id for e in evidence}
    documents = [repos.documents.get(did) for did in sorted(document_ids)]
    documents = [d for d in documents if d is not None]

    submission_ids = {d.submission_id for d in documents if d.submission_id}
    submissions = [repos.submissions.get(sid) for sid in sorted(submission_ids)]
    submissions = [s for s in submissions if s is not None]

    compliance_results = repos.compliance_results.list_by_bidder(bidder_id)
    explanations = repos.explanations.list_by_flag(bidder_id, flag_id)
    snapshots = repos.flags.list_snapshots(bidder_id)

    return FlagLineage(
        bidder_id=bidder_id,
        flag_id=flag_id,
        flag_state=state,
        submissions=submissions,
        documents=documents,
        evidence=evidence,
        verifications=verifications,
        compliance_results=compliance_results,
        findings=findings,
        explanations=explanations,
        snapshots=snapshots,
    )


__all__ = ["FlagLineage", "audit_event", "build_flag_lineage", "new_event_id"]