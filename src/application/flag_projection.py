"""Projection of engine outputs into durable boolean flag states.

This module is intentionally small and read-only with respect to the
domain: it *projects* the flags already decided by the Compliance Engine
(``ComplianceResult.flags``), the AI Verification Engine
(``VerificationFinding.flag_id``) and the cross-document identity
verifier (``IdentityFinding.flag_id``) into :class:`FlagStateRecord`
rows whose ``is_set`` is ``True`` and whose provenance references are
real artifact IDs.

It does not invent flags, does not re-derive evidence, and does not
contain a second flag registry: every flag ID is validated against the
canonical registry via ``get_flag_definition``.

Flags that are absent from every engine output are simply not set; the
snapshot materializer (``infrastructure.flags.materialize_flag_snapshot``)
is responsible for explicit ``false`` defaults over the configured flag
universe. Missing evidence therefore never becomes a positive result.
"""

from __future__ import annotations

from compliance_engine.flags import get_flag_definition
from compliance_engine.models import ComplianceResult, IdentityFinding
from ai_verification.models.contracts import VerificationFinding
from infrastructure.persistence.records import FlagStateRecord

#: Provenance tag for flag states written by the application projection.
PROJECTION_SOURCE = "APPLICATION_PROJECTION"


def compliance_result_id(bidder_id: str, requirement_id: str) -> str:
    """Deterministic durable ID for one persisted compliance result."""
    return f"res:{bidder_id}:{requirement_id}"


def compliance_finding_id(
    bidder_id: str, requirement_id: str, flag_id: str
) -> str:
    """Deterministic durable ID for one finding raised by a rule result."""
    return f"fnd:compliance:{bidder_id}:{requirement_id}:{flag_id}"


def identity_finding_id(bidder_id: str, finding: IdentityFinding) -> str:
    """Deterministic durable ID for one identity verification finding."""
    return (
        f"fnd:identity:{bidder_id}:{finding.flag_id}:"
        f"{finding.left_document_id}:{finding.right_document_id}"
    )


def project_flag_states(
    *,
    bidder_id: str,
    compliance_results: list[ComplianceResult],
    verification_findings: list[VerificationFinding],
    identity_findings: list[IdentityFinding],
    correlation_id: str | None,
    updated_at: float,
) -> list[FlagStateRecord]:
    """Project engine outputs into boolean flag states (sorted by flag ID).

    Every flag that any engine output mentions is validated against the
    canonical registry and becomes ``is_set=True`` with the union of the
    contributing finding / evidence / verification references.
    """
    aggregation: dict[str, dict[str, set[str]]] = {}

    def accumulate(
        flag_id: str,
        *,
        finding_ref: str,
        evidence_refs: list[str],
        verification_refs: list[str],
    ) -> None:
        canonical = get_flag_definition(flag_id).flag_id
        entry = aggregation.setdefault(
            canonical,
            {"finding_refs": set(), "evidence_refs": set(), "verification_refs": set()},
        )
        entry["finding_refs"].add(finding_ref)
        entry["evidence_refs"].update(evidence_refs)
        entry["verification_refs"].update(verification_refs)

    for result in compliance_results:
        for flag_id in result.flags:
            accumulate(
                flag_id,
                finding_ref=compliance_finding_id(
                    bidder_id, result.requirement_id, flag_id
                ),
                evidence_refs=list(result.evidence_refs),
                verification_refs=list(result.verification_refs),
            )

    for finding in verification_findings:
        accumulate(
            finding.flag_id,
            finding_ref=finding.finding_id,
            evidence_refs=list(finding.evidence_refs),
            verification_refs=list(finding.verification_refs),
        )

    for finding in identity_findings:
        accumulate(
            finding.flag_id,
            finding_ref=identity_finding_id(bidder_id, finding),
            evidence_refs=list(finding.evidence_refs),
            verification_refs=[],
        )

    return [
        FlagStateRecord(
            bidder_id=bidder_id,
            flag_id=flag_id,
            is_set=True,
            source=PROJECTION_SOURCE,
            finding_refs=sorted(refs["finding_refs"]),
            evidence_refs=sorted(refs["evidence_refs"]),
            verification_refs=sorted(refs["verification_refs"]),
            correlation_id=correlation_id,
            updated_at=updated_at,
        )
        for flag_id, refs in sorted(aggregation.items())
    ]


__all__ = [
    "PROJECTION_SOURCE",
    "compliance_finding_id",
    "compliance_result_id",
    "identity_finding_id",
    "project_flag_states",
]
