"""Future Module 3 (compliance/verification) extension point — INTERFACE ONLY.

The current integrated flow is:

    Module 1/2  ->  Evidence  ->  Module 4 (CrossDocumentConsistencyEngine)

and the application does NOT depend on Module 3 today. When Module 3 is
built, it slots in as:

    Module 1/2  ->  Evidence  ->  Module 3  ->  Verification[]
                                            ->  Module 4 identity
                                                reconciliation / enrichment

Nothing in the current codebase implements, mocks, or fakes this stage;
no Verification records are ever manufactured here. The protocol below is
the single place where a future Module 3 implementation must plug in. It
returns authoritative ``Verification`` records (from
``compliance_engine.models.verification``) which the already-wired
``IdentityReconciliationEngine`` then consumes.
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
