"""Cross-document consistency engine (the public orchestrator)."""


from dataclasses import dataclass
from typing import Iterable, List, Optional

from compliance_engine.models import Evidence

from ai_verification.models.contracts import VerificationFinding

from .aggregation import aggregate
from .comparison import compare_all
from .findings import to_verification_findings
from .models import CrossDocumentAggregation

# Import via the fully-qualified package path and read the
# attribute off the module. Same style as the package
# __init__.py; avoids the brittle ``from .extraction import ...``
# form under partial-load in Python 3.14.
import ai_verification.cross_document.extraction as _extraction_mod
QualityLookup = _extraction_mod.QualityLookup
extract_observations = _extraction_mod.extract_observations
del _extraction_mod


@dataclass(frozen=True)
class CrossDocumentConsistencyResult:
    aggregation: CrossDocumentAggregation
    verification_findings: List[VerificationFinding]


class CrossDocumentConsistencyEngine:
    """Stateless deterministic cross-document consistency engine."""

    def __init__(
        self,
        *,
        evaluation_date_iso: Optional[str] = None,
    ) -> None:
        self._evaluation_date_iso = evaluation_date_iso

    def run(
        self,
        evidence: Iterable[Evidence],
        *,
        bidder_id: str,
        quality_lookup: Optional[QualityLookup] = None,
    ) -> CrossDocumentConsistencyResult:
        observations = extract_observations(
            evidence,
            bidder_id=bidder_id,
            quality_lookup=quality_lookup,
        )
        if not observations:
            raise ValueError(
                "CrossDocumentConsistencyEngine.run() requires at least one "
                "Evidence for the given bidder; got an empty list."
            )

        comparisons = compare_all(
            observations,
            evaluation_date_iso=self._evaluation_date_iso,
        )
        aggregation = aggregate(
            bidder_id,
            observations,
            comparisons,
            evaluation_date_iso=self._evaluation_date_iso,
        )
        findings = to_verification_findings(aggregation)
        return CrossDocumentConsistencyResult(
            aggregation=aggregation,
            verification_findings=findings,
        )


__all__ = [
    "CrossDocumentConsistencyEngine",
    "CrossDocumentConsistencyResult",
]
