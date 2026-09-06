"""Typed Pydantic v2 models for the cross-document consistency engine."""


from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from ai_verification.evidence_quality import QualityReason, QualityState


Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class ConsistencyDimension(StrEnum):
    IDENTIFIER = "IDENTIFIER"
    ADDRESS = "ADDRESS"
    DATE = "DATE"
    PRODUCT = "PRODUCT"
    MANUFACTURER = "MANUFACTURER"


class FieldStatus(StrEnum):
    NOT_QUERIED = "NOT_QUERIED"
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class DateRole(StrEnum):
    ISSUE_DATE = "ISSUE_DATE"
    EFFECTIVE_DATE = "EFFECTIVE_DATE"
    EXPIRY_DATE = "EXPIRY_DATE"
    REGISTRATION_DATE = "REGISTRATION_DATE"
    CANCELLATION_DATE = "CANCELLATION_DATE"
    FILING_DATE = "FILING_DATE"
    UNKNOWN = "UNKNOWN"


class IdentifierKind(StrEnum):
    GSTIN = "GSTIN"
    PAN = "PAN"
    UDYAM = "UDYAM"
    CIN = "CIN"
    UDIN = "UDIN"
    GENERIC = "GENERIC"


class IdentifierComparisonOutcome(StrEnum):
    MATCH_EXACT = "MATCH_EXACT"
    MATCH_NORMALIZED = "MATCH_NORMALIZED"
    MISMATCH = "MISMATCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class AddressComparisonOutcome(StrEnum):
    EXACT = "EXACT"
    NORMALIZED_MATCH = "NORMALIZED_MATCH"
    MISMATCH = "MISMATCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class DateComparisonOutcome(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    VALIDITY_CONFLICT = "VALIDITY_CONFLICT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ProductComparisonOutcome(StrEnum):
    EXACT = "EXACT"
    NORMALIZED_MATCH = "NORMALIZED_MATCH"
    MISMATCH = "MISMATCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ManufacturerComparisonOutcome(StrEnum):
    MATCH_EXACT = "MATCH_EXACT"
    MATCH_NORMALIZED = "MATCH_NORMALIZED"
    MISMATCH = "MISMATCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class FieldObservation(BaseModel):
    """One extracted field, classified into a consistency dimension."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bidder_id: str
    document_id: str
    document_type: str
    field_name: str
    evidence_id: str

    original_value: Any
    normalized_value: str | None
    dimension: ConsistencyDimension | None
    identifier_kind: IdentifierKind | None = None
    date_role: DateRole | None = None
    status: FieldStatus
    evidence_confidence: float | None = None
    field_confidence: float | None = None
    ocr_confidence: float | None = None
    quality_state: QualityState | None = None
    quality_score: float | None = None
    quality_reasons: tuple[QualityReason, ...] = ()
    is_comparable: bool = True

    def short_reference(self) -> str:
        return f"{self.document_id}:{self.field_name}"


class PairwiseComparison(BaseModel):
    """One pairwise comparison between two FieldObservations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bidder_id: str
    dimension: ConsistencyDimension

    left_document_id: str
    right_document_id: str
    left_document_type: str
    right_document_type: str
    left_field_name: str
    right_field_name: str
    left_evidence_id: str
    right_evidence_id: str

    left_original: Any
    right_original: Any
    left_normalized: str | None
    right_normalized: str | None

    outcome: str
    normalization_version: str
    comparability_reason: str
    is_self_comparison: bool = False

    left_confidence: float | None = None
    right_confidence: float | None = None

    left_quality_state: QualityState | None = None
    right_quality_state: QualityState | None = None
    left_quality_score: float | None = None
    right_quality_score: float | None = None
    left_quality_reasons: tuple[QualityReason, ...] = ()
    right_quality_reasons: tuple[QualityReason, ...] = ()

    explanation: str

    def is_mismatch(self) -> bool:
        return self.outcome.endswith("MISMATCH") and not self.outcome.endswith(
            "INSUFFICIENT_EVIDENCE"
        )


def outcome_for_dimension(
    dimension: ConsistencyDimension, value: str
) -> StrEnum:
    table: dict[ConsistencyDimension, type[StrEnum]] = {
        ConsistencyDimension.IDENTIFIER: IdentifierComparisonOutcome,
        ConsistencyDimension.ADDRESS: AddressComparisonOutcome,
        ConsistencyDimension.DATE: DateComparisonOutcome,
        ConsistencyDimension.PRODUCT: ProductComparisonOutcome,
        ConsistencyDimension.MANUFACTURER: ManufacturerComparisonOutcome,
    }
    enum_cls = table[dimension]
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise ValueError(
            f"Outcome {value!r} is not a valid outcome for dimension "
            f"{dimension!r}"
        ) from exc


class DimensionSummary(BaseModel):
    """Per-dimension summary of comparisons."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: ConsistencyDimension
    total_comparisons: int
    matches: int
    mismatches: int
    insufficient_evidence: int


class CrossDocumentAggregation(BaseModel):
    """Per-bidder cross-document consistency picture."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bidder_id: str
    observations: tuple[FieldObservation, ...]
    comparisons: tuple[PairwiseComparison, ...]
    dimension_summaries: tuple[DimensionSummary, ...]
    mismatching_comparisons: tuple[PairwiseComparison, ...]
    insufficient_evidence_comparisons: tuple[PairwiseComparison, ...]
    normalization_version: str
    evaluation_date_iso: str | None = None

    @property
    def has_material_mismatch(self) -> bool:
        return bool(self.mismatching_comparisons)

    @property
    def mismatch_count(self) -> int:
        return len(self.mismatching_comparisons)

    @property
    def comparison_count(self) -> int:
        return len(self.comparisons)

    def summary(self) -> dict[str, Any]:
        return {
            "bidder_id": self.bidder_id,
            "normalization_version": self.normalization_version,
            "observation_count": len(self.observations),
            "comparison_count": self.comparison_count,
            "mismatch_count": self.mismatch_count,
            "insufficient_evidence_count": len(
                self.insufficient_evidence_comparisons
            ),
            "has_material_mismatch": self.has_material_mismatch,
            "dimension_summaries": [
                {
                    "dimension": s.dimension.value,
                    "total_comparisons": s.total_comparisons,
                    "matches": s.matches,
                    "mismatches": s.mismatches,
                    "insufficient_evidence": s.insufficient_evidence,
                }
                for s in self.dimension_summaries
            ],
        }


__all__ = [
    "AddressComparisonOutcome",
    "Confidence",
    "ConsistencyDimension",
    "CrossDocumentAggregation",
    "DateComparisonOutcome",
    "DateRole",
    "DimensionSummary",
    "FieldObservation",
    "FieldStatus",
    "IdentifierComparisonOutcome",
    "IdentifierKind",
    "ManufacturerComparisonOutcome",
    "PairwiseComparison",
    "ProductComparisonOutcome",
    "outcome_for_dimension",
]