"""Output contract for the top-level compliance engine.

The engine's output carries only the artefacts the engine itself produces
from the evidence it received: per-requirement compliance outcomes and
the identifying metadata (bidder_id, submission_id, evaluated_at) that
the consumer needs to correlate results back to a submission. The
``identity_findings`` field is retained for downstream/serialization
compatibility and remains empty in engine-produced results.

Scoring, risk, AI recommendation, and bid-level aggregation are
out-of-scope future components of this same system; they consume
``EngineResult`` rather than living on it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from compliance_engine.models.finding import IdentityFinding
from compliance_engine.models.result import ComplianceResult
from compliance_engine.models.verification import Verification


class EngineResult(BaseModel):
    """All outputs of a single ``ComplianceEngine.run`` invocation.

    ``compliance_results`` and ``identity_findings`` are sibling fields
    because ``IdentityFinding`` is an anomaly-detection output, not a
    compliance result. The engine does not execute cross-document
    identity verification; ``identity_findings`` is always empty when
    the result is produced by :class:`ComplianceEngine` and is retained
    only for downstream/serialization compatibility. ``bidder_id`` is
    derived from the evidence by the
    engine and is best-effort: it is ``None`` when no evidence was
    supplied. ``submission_id`` is supplied by the caller (typically
    from ``NormalizedSubmission``) so the result can be correlated back
    to the originating submission; it is not derived or fabricated.
    ``evaluated_at`` is the wall-clock time the engine finished
    assembling the result.
    """

    bidder_id: str | None = None
    submission_id: str | None = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    compliance_results: list[ComplianceResult] = Field(default_factory=list)
    identity_findings: list[IdentityFinding] = Field(default_factory=list)
    verification_records: list[Verification] = Field(
        default_factory=list,
        description="Every Verification object produced by providers during this engine run.",
    )

