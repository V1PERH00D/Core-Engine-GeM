"""Typed models for cross-source bidder identity reconciliation.

All models use ``extra="forbid"`` so unknown fields are rejected at
construction time, which keeps the wire/audit surface auditable.

The models intentionally stay independent of the Compliance Engine
provider schemas: the engine consumes already-normalized
``Verification`` records and never re-reads raw provider payloads.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ComparisonOutcome(StrEnum):
    """Outcome of comparing two identity observations.

    The engine NEVER declares one source universally authoritative:
    every outcome is computed from the per-pair evidence only.
    """

    MATCH_EXACT = "MATCH_EXACT"
    MATCH_NORMALIZED = "MATCH_NORMALIZED"
    MISMATCH = "MISMATCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class SourceAvailability(StrEnum):
    """Per-source availability classification.

    Distinct from the upstream ``VerificationStatus``: the engine
    collapses the richer set into a small, identity-focused taxonomy.
    """

    NOT_QUERIED = "NOT_QUERIED"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    VERIFIED = "VERIFIED"
    VERIFIED_WITHOUT_NAME = "VERIFIED_WITHOUT_NAME"
    INACTIVE = "INACTIVE"


# ---------------------------------------------------------------------------
# Observations and comparisons
# ---------------------------------------------------------------------------


class IdentityObservation(BaseModel):
    """One verified-identity observation drawn from a single source.

    The engine builds one ``IdentityObservation`` per
    ``Verification`` record that carries an identity-bearing field
    (e.g. GST ``legal_name``, PAN ``name_on_pan``, Udyam
    ``enterprise_name``, MCA ``company_name``).

    Both ``original_name`` and ``normalized_name`` are retained so the
    audit trail records what was received and what the normalization
    rules produced.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(
        ...,
        description=(
            "Authoritative source label. One of: GST, PAN, UDYAM, MCA."
        ),
    )
    bidder_id: str = Field(
        ..., description="Identifier of the bidder this observation belongs to."
    )
    verification_id: str = Field(
        ...,
        description=(
            "Verification ID of the upstream Verification record. "
            "Preserved verbatim; never fabricated."
        ),
    )
    original_name: str | None = Field(
        ...,
        description=(
            "Original identity-bearing value as reported by the source "
            "adapter. ``None`` when the value was missing on the wire."
        ),
    )
    normalized_name: str | None = Field(
        ...,
        description=(
            "Versioned deterministic normalization of ``original_name``. "
            "``None`` when ``original_name`` is ``None`` or normalization "
            "collapsed to an empty string."
        ),
    )
    source_status: SourceAvailability = Field(
        ...,
        description=(
            "Identity-focused classification of the upstream "
            "Verification status."
        ),
    )
    queried_identifier: str | None = Field(
        ...,
        description=(
            "The identifier that was queried against the source "
            "(e.g. GSTIN, PAN, Udyam number, CIN). ``None`` when the "
            "Verification record did not record one."
        ),
    )
    evidence_ref: str | None = Field(
        ...,
        description=(
            "Evidence ID of the evidence item that triggered the query. "
            "``None`` when the upstream Verification did not carry one."
        ),
    )
    document_ref: str | None = Field(
        ...,
        description=(
            "Document ID of the underlying bidder-submitted document, "
            "when available. ``None`` when not recorded."
        ),
    )
    normalization_version: str = Field(
        ...,
        description=(
            "Name-normalization version used to produce ``normalized_name``. "
            "Always set so audit consumers can verify the rules."
        ),
    )


class IdentityPairwiseComparison(BaseModel):
    """Result of comparing two ``IdentityObservation`` objects.

    The comparison is symmetric: ``left``/``right`` only affect the
    human-readable explanation, not the outcome classification.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    left_source: str = Field(
        ..., description="Source label of the left observation."
    )
    right_source: str = Field(
        ..., description="Source label of the right observation."
    )
    left_verification_id: str = Field(
        ..., description="Verification ID of the left observation."
    )
    right_verification_id: str = Field(
        ..., description="Verification ID of the right observation."
    )
    outcome: ComparisonOutcome = Field(
        ...,
        description=(
            "Computed outcome of the comparison. Always one of "
            "MATCH_EXACT / MATCH_NORMALIZED / MISMATCH / "
            "INSUFFICIENT_EVIDENCE."
        ),
    )
    left_original: str | None = Field(
        ..., description="Original name on the left side (verbatim)."
    )
    right_original: str | None = Field(
        ..., description="Original name on the right side (verbatim)."
    )
    left_normalized: str | None = Field(
        ..., description="Normalized name on the left side."
    )
    right_normalized: str | None = Field(
        ..., description="Normalized name on the right side."
    )
    explanation: str = Field(
        ...,
        description=(
            "Deterministic, human-readable explanation of why this "
            "outcome was reached. Contains no secrets."
        ),
    )
    left_evidence_ref: str | None = Field(
        ..., description="Evidence ID of the left observation, if any."
    )
    right_evidence_ref: str | None = Field(
        ..., description="Evidence ID of the right observation, if any."
    )
    left_document_ref: str | None = Field(
        ..., description="Document ID of the left observation, if any."
    )
    right_document_ref: str | None = Field(
        ..., description="Document ID of the right observation, if any."
    )
    left_queried_identifier: str | None = Field(
        ..., description="Queried identifier on the left side, if any."
    )
    right_queried_identifier: str | None = Field(
        ..., description="Queried identifier on the right side, if any."
    )


class IdentityAggregation(BaseModel):
    """Aggregate view of a single bidder's identity evidence.

    Holds every pairwise comparison so a future policy layer can
    decide how to act without the engine itself baking in policy.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    bidder_id: str = Field(
        ..., description="Identifier of the bidder being aggregated."
    )
    observations: tuple[IdentityObservation, ...] = Field(
        ...,
        description=(
            "All identity observations extracted from the supplied "
            "Verification records, in first-seen order."
        ),
    )
    comparisons: tuple[IdentityPairwiseComparison, ...] = Field(
        ...,
        description=(
            "All pairwise comparisons, in a deterministic "
            "(left_source, right_source) order."
        ),
    )
    verified_sources: tuple[str, ...] = Field(
        ...,
        description=(
            "Sources whose observation was VERIFIED with a "
            "non-empty normalized name, in first-seen order."
        ),
    )
    insufficient_sources: tuple[str, ...] = Field(
        ...,
        description=(
            "Sources that were not sufficiently evidenced to take "
            "part in a comparison (e.g. unavailable, NOT_FOUND, "
            "verified-but-name-missing, inactive, or not queried), in "
            "first-seen order."
        ),
    )
    disagreeing_pairs: tuple[IdentityPairwiseComparison, ...] = Field(
        ...,
        description=(
            "Pairwise comparisons whose outcome is MISMATCH, in the "
            "same order as ``comparisons``."
        ),
    )
    normalization_version: str = Field(
        ...,
        description=(
            "Normalization version used to produce every normalized "
            "name in this aggregation."
        ),
    )

    @property
    def verified_count(self) -> int:
        """Return the number of sources with verified identity names."""
        return len(self.verified_sources)

    @property
    def disagreeing_pair_count(self) -> int:
        """Return the number of pairwise mismatches observed."""
        return len(self.disagreeing_pairs)

    @property
    def has_material_mismatch(self) -> bool:
        """Return True iff at least one pairwise MISMATCH exists."""
        return bool(self.disagreeing_pairs)

    def summary(self) -> dict[str, Any]:
        """Return a small JSON-safe summary of the aggregation.

        Intended for logs and human inspection. Does NOT include raw
        values, only counts and ordered source labels.
        """

        return {
            "bidder_id": self.bidder_id,
            "normalization_version": self.normalization_version,
            "verified_sources": list(self.verified_sources),
            "insufficient_sources": list(self.insufficient_sources),
            "verified_count": self.verified_count,
            "comparison_count": len(self.comparisons),
            "disagreeing_pair_count": self.disagreeing_pair_count,
            "has_material_mismatch": self.has_material_mismatch,
        }


# ---------------------------------------------------------------------------
# Convenience alias
# ---------------------------------------------------------------------------

#: Re-exported here so downstream consumers can import every public
#: type from a single module if they prefer.
OptionalStr = Optional[str]

__all__ = [
    "ComparisonOutcome",
    "IdentityAggregation",
    "IdentityObservation",
    "IdentityPairwiseComparison",
    "OptionalStr",
    "SourceAvailability",
]