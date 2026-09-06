"""Cross-source identity reconciliation engine.

The engine is a thin orchestrator over the lower-level modules in
this subpackage. It accepts an iterable of :class:`Verification`
records and returns:

* an :class:`IdentityAggregation` (the evidence graph),
* a list of :class:`compliance_engine.models.IdentityFinding` for
  the Compliance Engine audit surface,
* a list of :class:`ai_verification.models.VerificationFinding` for
  the AI Verification Engine contract.

The engine never opens the network and never re-queries providers.
It is deterministic and safe to construct once and reuse across
many calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from compliance_engine.models import IdentityFinding
from compliance_engine.models.verification import Verification

from ai_verification.models.contracts import VerificationFinding

from .aggregation import aggregate
from .extraction import extract_observations
from .findings import (
    CROSS_SOURCE_IDENTITY_MISMATCH,
    to_identity_findings,
    to_verification_findings,
)
from .models import IdentityAggregation


@dataclass(frozen=True)
class IdentityReconciliationResult:
    """The complete output of one engine call.

    Attributes
    ----------
    aggregation:
        The per-bidder evidence graph. Holds every observation and
        every pairwise comparison, ordered deterministically.
    identity_findings:
        Compliance Engine findings (already wrapped in the existing
        :class:`IdentityFinding` model).
    verification_findings:
        AI Verification Engine findings (wrapped in
        :class:`VerificationFinding`).
    """

    aggregation: IdentityAggregation
    identity_findings: List[IdentityFinding]
    verification_findings: List[VerificationFinding]


class IdentityReconciliationEngine:
    """Stateless deterministic identity-reconciliation engine."""

    def __init__(self) -> None:
        # No constructor parameters today; the class exists so future
        # configuration (e.g. a configurable normalization version)
        # has a stable injection point without breaking callers.
        return

    def reconcile(
        self,
        verifications: Iterable[Verification],
        *,
        bidder_id: str,
    ) -> IdentityReconciliationResult:
        """Run the engine for one bidder.

        Parameters
        ----------
        verifications:
            All Verification records that belong to ``bidder_id``
            across GST / PAN / UDYAM / MCA. Records belonging to
            other bidders are silently skipped.
        bidder_id:
            The bidder to reconcile. The caller (typically the AI
            Verification Engine) owns the bidder-scoping decision.
        """

        observations = extract_observations(
            verifications, bidder_id=bidder_id
        )
        aggregation = aggregate(observations)
        identity_findings = to_identity_findings(aggregation)
        verification_findings = to_verification_findings(
            aggregation, bidder_id=bidder_id
        )
        return IdentityReconciliationResult(
            aggregation=aggregation,
            identity_findings=identity_findings,
            verification_findings=verification_findings,
        )

    @property
    def flag_id(self) -> str:
        """Return the canonical flag ID the engine emits."""

        return CROSS_SOURCE_IDENTITY_MISMATCH


__all__ = ["IdentityReconciliationEngine", "IdentityReconciliationResult"]