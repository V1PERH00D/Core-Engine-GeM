"""Document-scoring wiring: feeds the EXISTING Core DocumentScoringEngine.

This module owns NO scoring logic. All deductions, weights, thresholds,
traffic-light boundaries and severity semantics stay inside the single
authoritative implementation — ``ai_verification.document_scoring
.DocumentScoringEngine`` — and the canonical flag registry
(``compliance_engine.flags.get_flag_definition``). Nothing here infers
flags, assigns severities, or recalculates scores.

The integration layer only assembles the REAL upstream inputs:

* ``documents`` -> :class:`DocumentInput` records built by the Module 1/2
  adapter from the same Module 1/2 document records the Evidence was
  built from (same document ids, same canonical document types);
* ``evidence`` -> the exact ``Evidence`` objects Module 4 consumed;
* ``findings`` -> the final Module 4 ``VerificationFinding`` objects, so
  scoring always happens AFTER the deterministic flags exist;
* ``compliance_results`` / ``verification_records`` -> remain EMPTY until
  the future Module 3 (see ``future_module3.py``) supplies authoritative
  results. They are never fabricated here — the engine's existing no-
  compliance/no-verification behaviour applies;
* ``quality_by_document_id`` -> ``None`` unless Module 4 actually
  produced ``EvidenceQualityAssessment`` objects; the current Module 1/2
  wiring does not, so no quality deduction is ever invented.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from compliance_engine.models import (
    ComplianceResult,
    Evidence,
    IdentityFinding,
    Requirement,
)
from compliance_engine.models.verification import Verification

from ai_verification.document_scoring import (
    BidderDocumentScore,
    DocumentInput,
    DocumentScoringEngine,
)
from ai_verification.evidence_quality import EvidenceQualityAssessment
from ai_verification.models.contracts import VerificationFinding

#: Status persisted on the scoring record when the engine produced a score.
SCORING_STATUS_SCORED = "SCORED"

# Module 1/2 has no tender-requirement knowledge today (see the integration
# spec: do NOT invent required-document lists), so the scorer's default
# expected-document logic receives an empty requirement set. When real
# requirements exist later they are simply passed through this parameter.
DEFAULT_REQUIREMENTS: tuple[Requirement, ...] = ()


def score_bidder_documents(
    bidder_id: str,
    *,
    submission_id: Optional[str] = None,
    documents: Sequence[DocumentInput] = (),
    requirements: Sequence[Requirement] = (),
    evidence: Sequence[Evidence] = (),
    compliance_results: Sequence[ComplianceResult] = (),
    verification_records: Sequence[Verification] = (),
    findings: Sequence[VerificationFinding] = (),
    identity_findings: Sequence[IdentityFinding] = (),
    quality_by_document_id: Optional[
        Mapping[str, EvidenceQualityAssessment]
    ] = None,
    scoring_engine: Optional[DocumentScoringEngine] = None,
) -> BidderDocumentScore:
    """Score one bidder's documents with the EXISTING Core engine.

    Delegates 100% of scoring behaviour to
    :class:`ai_verification.document_scoring.DocumentScoringEngine`,
    which uses the canonical flag registry (``get_flag_definition``) to
    decide which findings are material. No severity, deduction, weight,
    or threshold is defined here.
    """
    engine = scoring_engine or DocumentScoringEngine()  # DEFAULT_POLICY
    return engine.score(
        str(bidder_id),
        submission_id=submission_id,
        documents=list(documents),
        requirements=list(requirements),
        evidence=list(evidence),
        compliance_results=list(compliance_results),
        verification_records=list(verification_records),
        findings=list(findings),
        identity_findings=list(identity_findings),
        quality_by_document_id=quality_by_document_id,
    )


__all__ = [
    "DEFAULT_REQUIREMENTS",
    "SCORING_STATUS_SCORED",
    "score_bidder_documents",
]
