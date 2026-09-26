"""Application-boundary request/response models.

The application layer orchestrates the existing engines (Compliance
Engine, AI Verification Engine, Explanation Engine) and the persistence
infrastructure. It contains **no** compliance logic of its own: it never
evaluates rules, never decides boolean flag states, and never computes
severity or risk.

These models define two things only:

* the *input* boundary -- a validated :class:`BidderSubmission`; and
* the *output* boundary -- :class:`ApplicationResult`, whose
  ``compliance`` member is the exact, boolean-only downstream contract::

      {"bidder_id": "...", "flags": {"<CANONICAL_FLAG_ID>": true/false}}

  All supplementary detail (verification statuses, finding IDs,
  explanation text, processing state) lives in *separate* fields so the
  compliance payload can never drift.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ai_verification.document_scoring.models import BidderDocumentScore
from ai_verification.models.contracts import BidderSummary
from compliance_engine.models import Evidence, Requirement
from infrastructure.errors import PermanentValidationError


class InvalidSubmissionError(PermanentValidationError):
    """The submission failed boundary validation; retry cannot change it."""


class SubmissionDocument(BaseModel):
    """One submitted document at the application boundary.

    ``content`` is handed to the infrastructure ArtifactStore by the
    processing coordinator; only the artifact reference and content hash
    are persisted durably.
    """

    document_id: str
    document_type: str
    content: bytes = b""
    metadata: dict[str, Any] = Field(default_factory=dict)


class BidderSubmission(BaseModel):
    """One bidder's tender submission, ready for compliance processing."""

    bidder_id: str
    submission_id: str
    documents: list[SubmissionDocument] = Field(min_length=1)
    evidence: list[Evidence] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    bidder_corpus: list[BidderSummary] = Field(
        default_factory=list,
        description=(
            "Other bidders' artefacts for cross-bidder comparison. Empty "
            "when cross-bidder analysis is not requested."
        ),
    )
    correlation_id: str | None = None

    @field_validator("requirements", mode="after")
    @classmethod
    def _restore_typed_parameters(
        cls, requirements: list[Requirement]
    ) -> list[Requirement]:
        """Restore domain-typed parameter values after JSON transport.

        Queue payloads are JSON, so a ``datetime.date`` requirement
        parameter arrives as an ISO string. The rule contract expects a
        real ``date`` object; this boundary normalization restores it.
        Malformed values are left untouched for the rule to reject.
        """
        from datetime import date

        for requirement in requirements:
            raw = requirement.parameters.get("evaluation_date")
            if isinstance(raw, str):
                try:
                    requirement.parameters["evaluation_date"] = (
                        date.fromisoformat(raw)
                    )
                except ValueError:
                    pass
        return requirements

    @model_validator(mode="after")
    def _validate_consistency(self) -> "BidderSubmission":
        document_ids = [d.document_id for d in self.documents]
        if len(set(document_ids)) != len(document_ids):
            raise ValueError("Duplicate document_id values in one submission.")
        known = set(document_ids)
        for item in self.evidence:
            if item.bidder_id != self.bidder_id:
                raise ValueError(
                    f"Evidence {item.evidence_id!r} belongs to bidder "
                    f"{item.bidder_id!r}, not submission bidder "
                    f"{self.bidder_id!r}."
                )
            if item.document_id not in known:
                raise ValueError(
                    f"Evidence {item.evidence_id!r} references unknown "
                    f"document {item.document_id!r}."
                )
        return self

    @classmethod
    def validate_or_raise(cls, data: Any) -> "BidderSubmission":
        """Validate ``data`` or raise :class:`InvalidSubmissionError`."""
        from pydantic import ValidationError

        try:
            return (
                cls.model_validate(data)
                if not isinstance(data, cls)
                else data
            )
        except ValidationError as exc:
            raise InvalidSubmissionError(
                f"Invalid bidder submission: {exc.error_count()} "
                f"validation error(s).",
                cause=exc,
            ) from exc


# ---------------------------------------------------------------------------
# Output boundary
# ---------------------------------------------------------------------------


class CompliancePayload(BaseModel):
    """The exact, boolean-only external compliance contract.

    No severity, no risk score, no counts -- the procurement officer (and
    any downstream consumer) receives booleans only.
    """

    model_config = {"extra": "forbid"}

    bidder_id: str
    flags: dict[str, bool]


class RequirementOutcome(BaseModel):
    """Supplementary per-requirement outcome (not part of the contract)."""

    requirement_id: str
    capability: str
    status: str
    rule_id: str | None = None
    flags: list[str] = Field(default_factory=list)


class VerificationSummary(BaseModel):
    """Supplementary verification status. The raw provider payload is
    deliberately NOT exposed here; use the durable record for audit."""

    verification_id: str
    capability: str
    source: str
    status: str
    queried_identifier: str | None = None


class FindingSummary(BaseModel):
    """Supplementary finding reference (not part of the contract).

    Carries the finding's real provenance (evidence / verification refs,
    related bidders, cross-bidder trace where applicable) plus the link to
    the grounded explanation of its flag, so downstream consumers can join
    finding -> explanation without re-running anything.
    """

    finding_id: str
    flag_id: str | None = None
    finding_type: str
    related_bidder_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    verification_refs: list[str] = Field(default_factory=list)
    trace: dict[str, Any] | None = None
    explanation_id: str | None = None


class ExplanationSummary(BaseModel):
    """Supplementary explanation reference (not part of the contract).

    ``fallback_used`` and ``provider``/``model`` distinguish a
    model-generated explanation from the deterministic fallback for audit.
    The reference lists are exactly the grounding the explanation was
    allowed to cite; no explanation text ever enters the boolean
    compliance payload.
    """

    explanation_id: str
    flag_id: str
    text: str
    fallback_used: bool
    validation_status: str | None = None
    detailed_text: str | None = None
    provider: str | None = None
    model: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    verification_refs: list[str] = Field(default_factory=list)
    finding_refs: list[str] = Field(default_factory=list)
    document_refs: list[str] = Field(default_factory=list)
    trace_refs: list[str] = Field(default_factory=list)


class ProcessingSummary(BaseModel):
    """Supplementary processing state (not part of the contract)."""

    submission_id: str
    stage: str
    correlation_id: str | None = None
    snapshot_id: str


class ApplicationResult(BaseModel):
    """Application-level result: the boolean contract plus separate detail.

    ``compliance`` IS the external contract. Every other field is
    supplementary and structurally separate; no amount of detail can
    change the boolean decision because the decision was made upstream by
    the deterministic engines.
    """

    compliance: CompliancePayload
    processing: ProcessingSummary
    document_score: "BidderDocumentScore | None" = None
    requirements: list[RequirementOutcome] = Field(default_factory=list)
    verifications: list[VerificationSummary] = Field(default_factory=list)
    findings: list[FindingSummary] = Field(default_factory=list)
    explanations: list[ExplanationSummary] = Field(default_factory=list)

    def compliance_payload(self) -> dict[str, Any]:
        """Return exactly ``{"bidder_id": ..., "flags": {...}}``."""
        return self.compliance.model_dump()

    def findings_payload(self) -> dict[str, Any]:
        """Return the downstream findings/explanations contract::

            {"bidder_id": "...",
             "findings": [{"finding_id": ..., "flag_id": ...,
                           "explanation": ..., "evidence_refs": [...],
                           "verification_refs": [...],
                           "related_bidder_ids": [...], "trace": ...}]}

        Fully separate from :meth:`compliance_payload`: explanations never
        enter the boolean-only flags payload.
        """
        explanation_by_flag = {e.flag_id: e for e in self.explanations}
        findings: list[dict[str, Any]] = []
        for finding in self.findings:
            explanation = (
                explanation_by_flag.get(finding.flag_id)
                if finding.flag_id
                else None
            )
            findings.append(
                {
                    "finding_id": finding.finding_id,
                    "flag_id": finding.flag_id,
                    "explanation": (
                        explanation.text if explanation is not None else None
                    ),
                    "evidence_refs": list(finding.evidence_refs),
                    "verification_refs": list(finding.verification_refs),
                    "related_bidder_ids": list(finding.related_bidder_ids),
                    "trace": finding.trace,
                }
            )
        return {"bidder_id": self.compliance.bidder_id, "findings": findings}

    def set_flags(self) -> dict[str, bool]:
        """Return only the flags that are TRUE, for human review."""
        return {
            flag_id: value
            for flag_id, value in self.compliance.flags.items()
            if value
        }

    def to_display_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


__all__ = [
    "ApplicationResult",
    "BidderSubmission",
    "CompliancePayload",
    "ExplanationSummary",
    "FindingSummary",
    "InvalidSubmissionError",
    "ProcessingSummary",
    "RequirementOutcome",
    "SubmissionDocument",
    "VerificationSummary",
]
