"""Module 3 (compliance/verification) extension point — SATISFIED.

The REAL Module 3 implementation is the Core-Engine-GeM compliance
engine (:class:`compliance_engine.engine.ComplianceEngine` with its real
rules and real provider adapters), wired by
:mod:`app.integration.module3_service`. The integrated flow is:

    Module 1/2  ->  Evidence  ->  Module 3  ->  ComplianceResult[]
                                              + Verification[]
                                     ->  Module 4 identity
                                         reconciliation / enrichment

The protocol below documents the stage contract and is kept for
interface documentation; ``run_module3_for_bidder`` is the concrete
implementation. No Verification records are ever manufactured outside
the real adapters.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from compliance_engine.models import Evidence, Requirement
from compliance_engine.models.verification import Verification


class ComplianceStage(Protocol):
    """Contract a future Module 3 must satisfy.

    Implementations take the bidder's document-level ``Evidence`` (and,
    optionally, the tender/compliance ``Requirement`` set) and produce
    authoritative ``Verification`` records by querying the real external
    sources. They must never fabricate statuses or payloads.
    """

    def run(
        self,
        evidence: Sequence[Evidence],
        requirements: Sequence[Requirement] | None = None,
    ) -> list[Verification]:
        """Produce authoritative Verification records for the evidence."""
        ...


__all__ = ["ComplianceStage"]
