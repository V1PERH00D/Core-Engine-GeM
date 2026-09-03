"""Domain contracts for the AI Verification Engine.

These models define the top-level input / output boundary between the
Compliance Engine and the AI Verification Engine. They are intentionally
narrow: the verification engine consumes existing public artefacts
(``Evidence``, ``ComplianceResult``, ``IdentityFinding``) and emits
``VerificationFinding`` objects whose flag IDs are drawn from the
canonical verification flag registry.

Nothing in this module performs verification, scoring, or anomaly
detection. It is a contract layer only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from compliance_engine.flags import (
    FlagSeverity,
    UnknownFlagError,
    get_flag_definition,
)
from compliance_engine.models import (
    ComplianceResult,
    Evidence,
    IdentityFinding,
)
from compliance_engine.models.verification import Verification

from ai_verification.cross_bidder.trace import SimilarityTrace
# ---------------------------------------------------------------------------
# Shared scalar aliases
# ---------------------------------------------------------------------------

# Re-export the canonical 0..1 confidence alias from the Compliance Engine
# rather than re-declaring a parallel constraint, so that semantics stay
# aligned across both engines.
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


# ---------------------------------------------------------------------------
# Cross-bidder corpus
# ---------------------------------------------------------------------------


class BidderSummary(BaseModel):
    """Minimal cross-bidder context for one other bidder.

    The AI Verification Engine needs to compare this bidder against
    others. To keep the contract self-contained but still re-use the
    Compliance Engine's public models, a corpus entry is the same set of
    artefacts the engine already owns for one bid (evidence, compliance
    results, identity findings), scoped under that bidder's ``bidder_id``.

    Anomaly algorithms for cross-bidder comparison will be added in a
    later step; this model only fixes the shape of the input.
    """

    bidder_id: str = Field(
        ..., description="Identifier of the other bidder being summarised."
    )
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="Evidence submitted by the other bidder.",
    )
    compliance_results: list[ComplianceResult] = Field(
        default_factory=list,
        description="Compliance results produced by the Compliance Engine "
        "for the other bidder.",
    )
    identity_findings: list[IdentityFinding] = Field(
        default_factory=list,
        description="Identity findings produced by the Compliance Engine "
        "for the other bidder.",
    )
    verification_records: list[Verification] = Field(
        default_factory=list,
        description="Verification records produced by the Compliance Engine "
        "for the other bidder.",
    )


# ---------------------------------------------------------------------------
# Top-level input / output
# ---------------------------------------------------------------------------


class VerificationInput(BaseModel):
    """Input bundle for a single :meth:`VerificationEngine.run` call.

    Holds the artefacts the Compliance Engine already produced for one
    bidder plus an optional cross-bidder corpus for comparison. The
    verification engine does not re-evaluate compliance; it consumes
    these artefacts as-is.
    """

    bidder_id: str = Field(..., description="Identifier of the bidder being verified.")
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="All evidence items submitted by this bidder.",
    )
    compliance_results: list[ComplianceResult] = Field(
        default_factory=list,
        description="Per-requirement outcomes produced by the Compliance Engine.",
    )
    identity_findings: list[IdentityFinding] = Field(
        default_factory=list,
        description="Cross-document identity findings produced by the "
        "Compliance Engine.",
    )
    verification_records: list[Verification] = Field(
        default_factory=list,
        description="Verification records produced by government "
        "providers during the compliance engine run for this bidder.",
    )
    bidder_corpus: list[BidderSummary] = Field(
        default_factory=list,
        description="Optional corpus of other bidders for cross-bidder "
        "comparison. Empty when cross-bidder analysis is not requested.",
    )


class VerificationFinding(BaseModel):
    """One explainable, confidence-calibrated verification finding.

    The flag ID must exist in the canonical verification flag registry;
    ``severity`` is looked up from that registry so callers cannot attach
    an arbitrary severity to a flag. ``confidence`` is the engine's own
    confidence in the finding (separate from any upstream extraction
    confidence on individual evidence fields).
    """

    finding_id: str = Field(..., description="Unique identifier for this finding.")
    bidder_id: str = Field(
        ..., description="Bidder this finding applies to."
    )
    flag_id: str = Field(
        ...,
        description="Machine-readable flag ID. Must exist in the canonical "
        "verification flag registry.",
    )
    severity: FlagSeverity = Field(
        ...,
        description="Severity copied from the canonical flag definition. "
        "Callers should not set this independently of ``flag_id``.",
    )
    confidence: Confidence = Field(
        ...,
        description="Engine's confidence in this finding, in the closed "
        "interval [0.0, 1.0]. Distinct from upstream extraction "
        "confidence on individual evidence fields.",
    )
    explanation: str = Field(
        ..., description="Human-readable explanation of the finding."
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="IDs of evidence items this finding is based on. "
        "Values are preserved as supplied by the Compliance Engine.",
    )
    verification_refs: list[str] = Field(
        default_factory=list,
        description="IDs of upstream verification artefacts (e.g. "
        "Verification records from the Compliance Engine) this "
        "finding references.",
    )
    related_bidder_ids: list[str] = Field(
        default_factory=list,
        description="Other bidder IDs involved in this finding (used for "
        "cross-bidder findings). Empty for single-bidder findings.",
    )
    trace: SimilarityTrace | None = Field(
    default=None,
    description="Structured similarity evidence supporting this finding.",
    )
    @field_validator("flag_id")
    @classmethod
    def _validate_flag_id(cls, v: str) -> str:
        """Reject flag IDs that are not present in the canonical registry.

        Raises the Compliance Engine's :class:`UnknownFlagError` so the
        AI Verification Engine stays aligned with the existing error
        semantics rather than introducing a parallel error type.
        """
        definition = get_flag_definition(v)
        # Return the canonical form so casing/whitespace variants get
        # normalised against the registry.
        return definition.flag_id

    @field_validator("evidence_refs", "verification_refs", "related_bidder_ids")
    @classmethod
    def _preserve_reference_lists(cls, v: list[str]) -> list[str]:
        """Reference lists must be preserved verbatim.

        The AI Verification Engine does not mutate, deduplicate, or
        reorder evidence / verification / bidder references — those are
        owned by the Compliance Engine.
        """
        return list(v)


class VerificationResult(BaseModel):
    """Output bundle for a single :meth:`VerificationEngine.run` call.

    The verification engine never assigns a final compliance score or a
    final eligibility decision; it only produces a list of findings
    scoped to a single bidder, with the time the run completed.
    """

    bidder_id: str = Field(
        ..., description="Bidder whose findings this result covers."
    )
    findings: list[VerificationFinding] = Field(
        default_factory=list,
        description="Findings produced by the AI Verification Engine for "
        "this bidder. May be empty.",
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Wall-clock time at which the result was assembled.",
    )


__all__ = [
    "BidderSummary",
    "Confidence",
    "VerificationFinding",
    "VerificationInput",
    "VerificationResult",
]
