"""Deterministic explanation generation.

This milestone provides a deterministic, evidence-grounded fallback
generator: it composes a concise and a detailed explanation from the
finding it explains (flag + explanation text) and its real reference
lists. It never calls a network, never uses an LLM, and never invents
grounding — every ``GroundingReference`` points at a supplied real ID.

A production generator (e.g. a model-backed generator) can implement the
same :class:`ExplanationGenerator` protocol and is injected in place of
the fallback; the persistence contract is identical.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, field_validator

from ai_verification.explanations.models import (
    ExplanationGenerationMetadata,
    GroundedExplanation,
    GroundingKind,
    GroundingReference,
)
from ai_verification.explanations.facts import StructuredFact
from ai_verification.explanations.grounding import ExplanationGrounding
from ai_verification.models.contracts import VerificationFinding


class ExplanationRequest(BaseModel):
    bidder_id: str
    flag_id: str
    flag_active: bool
    finding: VerificationFinding | None = None
    evidence_refs: list[str] = []
    verification_refs: list[str] = []
    comparison_trace_ref: str | None = None
    correlation_id: str | None = None

    # Rich grounding inputs (all optional, backward compatible).
    finding_refs: list[str] = []
    document_refs: list[str] = []
    comparison_refs: list[str] = []
    trace_refs: list[str] = []
    facts: list[StructuredFact] = []
    uncertainties: list[str] = []
    locale: str | None = None

    @field_validator("flag_id")
    @classmethod
    def _validate_flag_id(cls, v: str) -> str:
        from compliance_engine.flags import get_flag_definition

        return get_flag_definition(v).flag_id

    @property
    def flag_state(self) -> bool:
        """Boolean alias mirroring ``flag_active`` (canonical state naming)."""

        return self.flag_active

    def build_grounding(self) -> ExplanationGrounding:
        """Assemble the explicit grounding object from this request."""

        all_finding_refs = list(self.finding_refs)
        if self.finding is not None:
            all_finding_refs.append(self.finding.finding_id)
        trace_refs = list(self.trace_refs)
        if self.comparison_trace_ref is not None:
            trace_refs.append(self.comparison_trace_ref)

        # Facts contribute their own source/document/verification pointers.
        for fact in self.facts:
            if fact.source_ref:
                self.evidence_refs.append(fact.source_ref)
            if fact.document_ref:
                self.document_refs.append(fact.document_ref)
            if fact.verification_ref:
                self.verification_refs.append(fact.verification_ref)

        return ExplanationGrounding(
            evidence_refs=tuple(self.evidence_refs),
            verification_refs=tuple(self.verification_refs),
            document_refs=tuple(self.document_refs),
            finding_refs=tuple(all_finding_refs),
            comparison_refs=tuple(self.comparison_refs),
            trace_refs=tuple(trace_refs),
        )


class ExplanationGenerator(Protocol):
    def explain(self, request: ExplanationRequest) -> GroundedExplanation: ...


def _grounding(request: ExplanationRequest) -> list[GroundingReference]:
    refs: list[GroundingReference] = []
    for ref in request.evidence_refs:
        refs.append(GroundingReference(kind=GroundingKind.EVIDENCE, ref_id=ref))
    for ref in request.verification_refs:
        refs.append(
            GroundingReference(kind=GroundingKind.VERIFICATION, ref_id=ref)
        )
    if request.comparison_trace_ref is not None:
        refs.append(
            GroundingReference(
                kind=GroundingKind.COMPARISON_TRACE,
                ref_id=request.comparison_trace_ref,
            )
        )
    if request.finding is not None:
        refs.append(
            GroundingReference(
                kind=GroundingKind.VERIFICATION_FINDING,
                ref_id=request.finding.finding_id,
            )
        )
    return refs


class DeterministicFallbackExplanationGenerator:
    """Evidence-grounded, deterministic explanation generator."""

    def __init__(self, *, generator_name: str = "deterministic_fallback") -> None:
        self._name = generator_name

    def explain(
        self, request: ExplanationRequest
    ) -> GroundedExplanation:
        state_word = "active" if request.flag_active else "inactive"
        if request.finding is not None:
            concise = (
                f"Flag {request.finding.flag_id} is {state_word}: "
                f"{request.finding.explanation}"
            )
            detail = (
                f"Flag {request.finding.flag_id} is {state_word} "
                "based on a verification finding with step-by-step "
                f"explanation: {request.finding.explanation}"
            )
            finding_refs = [request.finding.finding_id]
        else:
            concise = f"Flag {request.flag_id} is {state_word}."
            detail = (
                f"Flag {request.flag_id} was set to {state_word} without "
                "a supporting finding record."
            )
            finding_refs = []

        grounding = _grounding(request)
        explanation_id = GroundedExplanation.allocate_explanation_id(
            request.bidder_id, request.flag_id, request.flag_active
        )
        return GroundedExplanation(
            explanation_id=explanation_id,
            bidder_id=request.bidder_id,
            flag_id=request.flag_id,
            flag_active=request.flag_active,
            finding_refs=finding_refs,
            concise_text=concise,
            detailed_text=detail,
            grounding=grounding,
            generation=ExplanationGenerationMetadata(
                generator=self._name,
                deterministic_fallback=True,
                correlation_id=request.correlation_id,
            ),
        )


__all__ = [
    "DeterministicFallbackExplanationGenerator",
    "ExplanationGenerator",
    "ExplanationRequest",
]